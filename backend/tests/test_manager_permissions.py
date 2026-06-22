import io
import zipfile

from models.announcement import Announcement
from models.checklist import ChecklistOpinion
from models.discussion import Discussion
from models.inquiry import Inquiry
from models.review_stage import PhaseType, ReviewStage
from models.user import UserRole
from routers import reviews as reviews_router


def test_manager_can_read_limited_user_directory(
    client, db_session, make_user, make_reviewer
):
    _, headers = make_user(UserRole.MANAGER, name="관리원")
    reviewer_user, reviewer, _ = make_reviewer(group_no=4)
    reviewer_user.phone = "010-1234-5678"
    db_session.commit()

    res = client.get("/api/users", headers=headers, params={"size": 100})

    assert res.status_code == 200
    item = next(u for u in res.json()["items"] if u["id"] == reviewer_user.id)
    assert item["name"] == reviewer_user.name
    assert item["email"] == reviewer_user.email
    assert item["role"] == "reviewer"
    assert item["phone"] == "010-1234-5678"
    assert item["group_no"] == reviewer.group_no
    assert item["setup_status"] is None
    assert item["kakao_token_status"] is None


def test_manager_cannot_mutate_users(client, make_user):
    _, headers = make_user(UserRole.MANAGER)
    target, _ = make_user(UserRole.REVIEWER)

    create_res = client.post(
        "/api/users",
        headers=headers,
        json={
            "name": "신규관리대상",
            "email": "new-manager-target@example.com",
            "role": "reviewer",
        },
    )
    update_res = client.patch(
        f"/api/users/{target.id}",
        headers=headers,
        json={"name": "변경불가"},
    )
    delete_res = client.delete(f"/api/users/{target.id}", headers=headers)

    assert create_res.status_code == 403
    assert update_res.status_code == 403
    assert delete_res.status_code == 403


def test_manager_can_read_core_pages_and_review_files(
    client, db_session, make_user, make_building
):
    manager, headers = make_user(UserRole.MANAGER)
    building = make_building(mgmt_no="MGR-READ-001")
    announcement = Announcement(
        author_id=manager.id,
        author_name=manager.name,
        title="관리원 공지 조회",
        content="공지 내용",
    )
    discussion = Discussion(
        author_id=manager.id,
        author_name=manager.name,
        title="관리원 토론 조회",
        content="토론 내용",
    )
    opinion = ChecklistOpinion(
        item_key="manager-checklist",
        author_id=manager.id,
        author_name=manager.name,
        content="체크리스트 의견",
    )
    db_session.add_all([announcement, discussion, opinion])
    db_session.commit()
    db_session.refresh(announcement)
    db_session.refresh(discussion)

    assert client.get("/api/buildings/stats", headers=headers).status_code == 200
    assert client.get("/api/buildings", headers=headers).status_code == 200
    assert client.get(f"/api/buildings/{building.id}", headers=headers).status_code == 200
    assert client.get("/api/buildings/reviewer-names", headers=headers).status_code == 200
    assert client.get("/api/ledger/export", headers=headers).status_code == 200
    assert client.get("/api/announcements", headers=headers).status_code == 200
    assert client.get(
        f"/api/announcements/{announcement.id}",
        headers=headers,
    ).status_code == 200
    assert client.post(
        "/api/announcements",
        headers=headers,
        json={"title": "관리원 작성 불가", "content": "내용"},
    ).status_code == 403
    assert client.get("/api/discussions", headers=headers).status_code == 200
    assert client.get(
        f"/api/discussions/{discussion.id}",
        headers=headers,
    ).status_code == 200
    assert client.get(
        "/api/checklist/opinions/summary",
        headers=headers,
    ).status_code == 200
    assert client.get(
        "/api/checklist/items/manager-checklist/opinions",
        headers=headers,
    ).status_code == 200
    assert client.get("/api/reviews/files", headers=headers).status_code == 200
    assert client.delete(
        "/api/reviews/files",
        headers=headers,
        params={"key": "reviews/test.xlsm"},
    ).status_code == 403


def test_review_files_include_building_and_reviewer_metadata(
    client, db_session, make_user, make_building, monkeypatch
):
    _, headers = make_user(UserRole.MANAGER)
    building = make_building(mgmt_no="FILE-META-001")
    s3_key = "reviews/예비검토/2026-06-21/FILE-META-001.xlsm"
    stage = ReviewStage(
        building_id=building.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
        reviewer_name="업로드검토위원",
        s3_file_key=s3_key,
    )
    db_session.add(stage)
    db_session.commit()

    monkeypatch.setattr(
        reviews_router,
        "list_review_files",
        lambda prefix="reviews/": [
            {
                "key": s3_key,
                "phase": "예비검토",
                "date": "2026-06-21",
                "filename": "FILE-META-001.xlsm",
                "size": 1024,
                "last_modified": "2026-06-21T12:00:00+00:00",
            }
        ],
    )

    res = client.get("/api/reviews/files", headers=headers)

    assert res.status_code == 200
    item = res.json()[0]
    assert item["mgmt_no"] == "FILE-META-001"
    assert item["building_id"] == building.id
    assert item["stage_id"] == stage.id
    assert item["reviewer_name"] == "업로드검토위원"


def test_review_files_download_zip_returns_single_archive(
    client, make_user, monkeypatch
):
    _, headers = make_user(UserRole.MANAGER)
    files = {
        "reviews/preliminary/2026-06-21/ZIP-001.xlsm": b"first-review",
        "reviews/preliminary/2026-06-21/ZIP-002.xlsm": b"second-review",
    }

    def fake_stream_s3_file_to_writer(key, writer):
        data = files[key]
        writer.write(data)
        return len(data)

    monkeypatch.setattr(
        reviews_router,
        "stream_s3_file_to_writer",
        fake_stream_s3_file_to_writer,
    )

    res = client.post(
        "/api/reviews/files/download-zip",
        headers=headers,
        json={
            "keys": list(files.keys()),
            "archive_name": "예비검토_2026-06-21.zip",
        },
    )

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/zip")
    with zipfile.ZipFile(io.BytesIO(res.content)) as archive:
        assert sorted(archive.namelist()) == ["ZIP-001.xlsm", "ZIP-002.xlsm"]
        assert archive.read("ZIP-001.xlsm") == b"first-review"
        assert archive.read("ZIP-002.xlsm") == b"second-review"


def test_review_files_download_zip_rejects_non_review_keys(client, make_user):
    _, headers = make_user(UserRole.MANAGER)

    res = client.post(
        "/api/reviews/files/download-zip",
        headers=headers,
        json={"keys": ["announcements/1/file.pdf"]},
    )

    assert res.status_code == 400


def test_manager_can_read_inquiries_but_not_reply_or_delete(
    client, db_session, make_user, make_building
):
    _, headers = make_user(UserRole.MANAGER)
    submitter, _ = make_user(UserRole.REVIEWER, name="문의자")
    building = make_building(mgmt_no="MGR-INQ-001")
    inquiry = Inquiry(
        building_id=building.id,
        mgmt_no=building.mgmt_no,
        phase="preliminary",
        submitter_id=submitter.id,
        submitter_name=submitter.name,
        content="확인 요청",
    )
    db_session.add(inquiry)
    db_session.commit()
    db_session.refresh(inquiry)

    list_res = client.get("/api/reviews/inquiries", headers=headers)
    reply_res = client.patch(
        f"/api/reviews/inquiry/{inquiry.id}",
        headers=headers,
        json={"reply": "관리원 답변 불가", "status": "completed"},
    )
    delete_res = client.delete(f"/api/reviews/inquiry/{inquiry.id}", headers=headers)

    assert list_res.status_code == 200
    assert list_res.json()["total"] == 1
    assert reply_res.status_code == 403
    assert delete_res.status_code == 403


def test_manager_can_read_inappropriate_review_but_not_change_it(
    client, db_session, make_user, make_building
):
    _, headers = make_user(UserRole.MANAGER)
    building = make_building(mgmt_no="MGR-BAD-001")
    stage = ReviewStage(
        building_id=building.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
        inappropriate_review_needed=True,
    )
    db_session.add(stage)
    db_session.commit()
    db_session.refresh(stage)

    list_res = client.get("/api/reviews/inappropriate", headers=headers)
    notes_res = client.get(f"/api/reviews/inappropriate/{stage.id}/notes", headers=headers)
    decision_res = client.patch(
        f"/api/reviews/inappropriate/{stage.id}",
        headers=headers,
        json={"decision": "confirmed_serious"},
    )
    note_create_res = client.post(
        f"/api/reviews/inappropriate/{stage.id}/notes",
        headers=headers,
        json={"content": "관리원 의견 등록 불가"},
    )

    assert list_res.status_code == 200
    assert list_res.json()["total"] == 1
    assert notes_res.status_code == 200
    assert decision_res.status_code == 403
    assert note_create_res.status_code == 403
