"""N3 — reviews.py 잔여 권한(upload/preview, upload, inquiry, my-inquiries) 회귀.

- upload/preview, upload: REVIEWER가 타 건물 mgmt_no로 호출 시 404 (파일 파싱 전 fail-fast)
- inquiry: 본인 담당 외 건물에 문의 등록 불가 → 403
- my-inquiries: submitter_id로만 매칭, 이름 같아도 다른 사용자 문의는 안 보임
"""

import io

from models.inquiry import Inquiry, InquiryStatus
from models.notification_log import NotificationLog
from models.user import UserRole
from services import inquiry_notify


def _fake_xlsx_upload(client, url, headers, mgmt_no, phase):
    """파일 파싱은 실패해도 권한 체크가 먼저 동작함을 검증하는 용도."""
    files = {
        "file": (
            "dummy.xlsx",
            io.BytesIO(b"not a real xlsx"),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }
    return client.post(
        f"{url}?mgmt_no={mgmt_no}&phase={phase}",
        headers=headers,
        files=files,
    )


def test_reviewer_cannot_preview_other_building_upload(
    client, make_reviewer, make_building
):
    _, reviewer_a, headers_a = make_reviewer()
    _, reviewer_b, _ = make_reviewer()
    other = make_building(reviewer_id=reviewer_b.id, mgmt_no="UPLOAD-OTHER-001")

    res = _fake_xlsx_upload(
        client, "/api/reviews/upload/preview", headers_a, other.mgmt_no, "doc_received"
    )
    # 권한 체크가 파일 파싱보다 먼저 → 404 ("건축물을 찾을 수 없습니다")
    assert res.status_code == 404


def test_reviewer_cannot_upload_other_building(
    client, make_reviewer, make_building
):
    _, reviewer_a, headers_a = make_reviewer()
    _, reviewer_b, _ = make_reviewer()
    other = make_building(reviewer_id=reviewer_b.id, mgmt_no="UPLOAD-OTHER-002")

    res = _fake_xlsx_upload(
        client, "/api/reviews/upload", headers_a, other.mgmt_no, "doc_received"
    )
    assert res.status_code == 404


def test_reviewer_cannot_create_inquiry_on_other_building(
    client, make_reviewer, make_building
):
    _, reviewer_a, headers_a = make_reviewer()
    _, reviewer_b, _ = make_reviewer()
    other = make_building(reviewer_id=reviewer_b.id, mgmt_no="INQ-OTHER-001")

    res = client.post(
        "/api/reviews/inquiry",
        headers=headers_a,
        json={"mgmt_no": other.mgmt_no, "phase": "preliminary", "content": "테스트 문의"},
    )
    assert res.status_code == 403


def test_reviewer_can_create_inquiry_on_own_building(
    client, db_session, make_reviewer, make_building
):
    user_a, reviewer_a, headers_a = make_reviewer()
    own = make_building(reviewer_id=reviewer_a.id, mgmt_no="INQ-OWN-001")

    res = client.post(
        "/api/reviews/inquiry",
        headers=headers_a,
        json={"mgmt_no": own.mgmt_no, "phase": "preliminary", "content": "내 문의"},
    )
    assert res.status_code == 200

    db_session.expire_all()
    saved = db_session.query(Inquiry).filter(Inquiry.mgmt_no == own.mgmt_no).first()
    assert saved is not None
    assert saved.submitter_id == user_a.id  # FK가 정확히 기록되어야 함
    assert saved.submitter_name == user_a.name


def test_create_inquiry_notifies_same_group_secretary(
    client, db_session, make_reviewer, make_building, make_user, monkeypatch
):
    user_a, reviewer_a, headers_a = make_reviewer(group_no=1)
    same_secretary, _ = make_user(
        UserRole.SECRETARY,
        name="같은조간사",
        email="same-sec@example.com",
        group_no=1,
    )
    make_user(
        UserRole.SECRETARY,
        name="다른조간사",
        email="other-sec@example.com",
        group_no=2,
    )
    own = make_building(reviewer_id=reviewer_a.id, mgmt_no="INQ-NOTIFY-001")
    sent: list[dict[str, str]] = []

    async def fake_ensure_valid_token(user, db):
        return f"token-{user.id}"

    async def fake_send_message_to_self(access_token, title, description, link_url=""):
        sent.append({
            "access_token": access_token,
            "title": title,
            "description": description,
            "link_url": link_url,
        })
        return {"result_code": 0}

    monkeypatch.setattr(inquiry_notify, "ensure_valid_token", fake_ensure_valid_token)
    monkeypatch.setattr(inquiry_notify, "send_message_to_self", fake_send_message_to_self)

    res = client.post(
        "/api/reviews/inquiry",
        headers=headers_a,
        json={
            "mgmt_no": own.mgmt_no,
            "phase": "preliminary",
            "content": "검토 중 확인 요청",
        },
    )
    assert res.status_code == 200
    assert sent == [{
        "access_token": f"token-{same_secretary.id}",
        "title": "새 문의 - INQ-NOTIFY-001",
        "description": f"검토위원: {user_a.name}\n문의: 검토 중 확인 요청",
        "link_url": "http://localhost:3000/inquiries",
    }]

    db_session.expire_all()
    logs = db_session.query(NotificationLog).all()
    assert len(logs) == 1
    assert logs[0].recipient_id == same_secretary.id
    assert logs[0].template_type == "inquiry_created"
    assert logs[0].channel == "kakao_memo"
    assert logs[0].is_sent is True


def test_create_inquiry_succeeds_when_secretary_token_check_fails(
    client, db_session, make_reviewer, make_building, make_user, monkeypatch
):
    user_a, reviewer_a, headers_a = make_reviewer(group_no=1)
    same_secretary, _ = make_user(
        UserRole.SECRETARY,
        name="토큰오류간사",
        email="token-error-sec@example.com",
        group_no=1,
    )
    own = make_building(reviewer_id=reviewer_a.id, mgmt_no="INQ-TOKEN-FAIL-001")

    async def fake_ensure_valid_token(user, db):
        raise RuntimeError("토큰 갱신 실패")

    monkeypatch.setattr(inquiry_notify, "ensure_valid_token", fake_ensure_valid_token)

    res = client.post(
        "/api/reviews/inquiry",
        headers=headers_a,
        json={
            "mgmt_no": own.mgmt_no,
            "phase": "preliminary",
            "content": "알림 실패와 무관하게 저장",
        },
    )
    assert res.status_code == 200

    db_session.expire_all()
    saved = db_session.query(Inquiry).filter(Inquiry.mgmt_no == own.mgmt_no).first()
    assert saved is not None
    assert saved.submitter_id == user_a.id

    logs = db_session.query(NotificationLog).all()
    assert len(logs) == 1
    assert logs[0].recipient_id == same_secretary.id
    assert logs[0].is_sent is False
    assert "토큰 확인 예외" in (logs[0].error_message or "")


def test_create_inquiry_succeeds_when_notify_unexpectedly_fails(
    client, db_session, make_reviewer, make_building, monkeypatch
):
    user_a, reviewer_a, headers_a = make_reviewer(group_no=1)
    own = make_building(reviewer_id=reviewer_a.id, mgmt_no="INQ-NOTIFY-BOOM-001")

    async def fake_notify_new_inquiry_to_group_secretaries(db, *, inquiry, reviewer):
        raise RuntimeError("예상 밖 알림 오류")

    monkeypatch.setattr(
        inquiry_notify,
        "notify_new_inquiry_to_group_secretaries",
        fake_notify_new_inquiry_to_group_secretaries,
    )

    res = client.post(
        "/api/reviews/inquiry",
        headers=headers_a,
        json={
            "mgmt_no": own.mgmt_no,
            "phase": "preliminary",
            "content": "알림 전체 실패와 무관하게 저장",
        },
    )
    assert res.status_code == 200

    db_session.expire_all()
    saved = db_session.query(Inquiry).filter(Inquiry.mgmt_no == own.mgmt_no).first()
    assert saved is not None
    assert saved.submitter_id == user_a.id


def test_inquiry_owner_can_update_and_delete_open_inquiry(
    client, db_session, make_reviewer, make_building
):
    user, reviewer, headers = make_reviewer(group_no=1)
    building = make_building(reviewer_id=reviewer.id, mgmt_no="INQ-EDIT-001")
    inquiry = Inquiry(
        building_id=building.id,
        mgmt_no=building.mgmt_no,
        phase="preliminary",
        submitter_id=user.id,
        submitter_name=user.name,
        content="수정 전",
    )
    db_session.add(inquiry)
    db_session.commit()
    db_session.refresh(inquiry)

    update_res = client.patch(
        f"/api/reviews/inquiry/{inquiry.id}/content",
        headers=headers,
        json={"content": "수정 후"},
    )
    assert update_res.status_code == 200

    db_session.expire_all()
    refreshed = db_session.query(Inquiry).filter(Inquiry.id == inquiry.id).first()
    assert refreshed.content == "수정 후"

    delete_res = client.delete(f"/api/reviews/inquiry/{inquiry.id}", headers=headers)
    assert delete_res.status_code == 204
    assert db_session.query(Inquiry).filter(Inquiry.id == inquiry.id).first() is None


def test_inquiry_owner_cannot_update_or_delete_completed_inquiry(
    client, db_session, make_reviewer, make_building
):
    user, reviewer, headers = make_reviewer(group_no=1)
    building = make_building(reviewer_id=reviewer.id, mgmt_no="INQ-LOCK-001")
    inquiry = Inquiry(
        building_id=building.id,
        mgmt_no=building.mgmt_no,
        phase="preliminary",
        submitter_id=user.id,
        submitter_name=user.name,
        content="완료 문의",
        status=InquiryStatus.COMPLETED,
    )
    db_session.add(inquiry)
    db_session.commit()
    db_session.refresh(inquiry)

    update_res = client.patch(
        f"/api/reviews/inquiry/{inquiry.id}/content",
        headers=headers,
        json={"content": "수정 시도"},
    )
    assert update_res.status_code == 400

    delete_res = client.delete(f"/api/reviews/inquiry/{inquiry.id}", headers=headers)
    assert delete_res.status_code == 400


def test_same_group_secretary_can_update_and_delete_inquiry(
    client, db_session, make_reviewer, make_building, make_user
):
    reviewer_user, reviewer, _ = make_reviewer(group_no=2)
    secretary, secretary_headers = make_user(
        UserRole.SECRETARY,
        name="2조간사",
        email="sec2@example.com",
        group_no=2,
    )
    building = make_building(reviewer_id=reviewer.id, mgmt_no="INQ-MANAGE-001")
    inquiry = Inquiry(
        building_id=building.id,
        mgmt_no=building.mgmt_no,
        phase="preliminary",
        submitter_id=reviewer_user.id,
        submitter_name=reviewer_user.name,
        content="관리 전",
        status=InquiryStatus.COMPLETED,
    )
    db_session.add(inquiry)
    db_session.commit()
    db_session.refresh(inquiry)

    update_res = client.patch(
        f"/api/reviews/inquiry/{inquiry.id}/content",
        headers=secretary_headers,
        json={"content": "관리 수정"},
    )
    assert update_res.status_code == 200

    db_session.expire_all()
    refreshed = db_session.query(Inquiry).filter(Inquiry.id == inquiry.id).first()
    assert refreshed.content == "관리 수정"

    delete_res = client.delete(
        f"/api/reviews/inquiry/{inquiry.id}",
        headers=secretary_headers,
    )
    assert delete_res.status_code == 204
    assert db_session.query(Inquiry).filter(Inquiry.id == inquiry.id).first() is None


def test_other_group_secretary_cannot_delete_inquiry(
    client, db_session, make_reviewer, make_building, make_user
):
    reviewer_user, reviewer, _ = make_reviewer(group_no=3)
    _, secretary_headers = make_user(
        UserRole.SECRETARY,
        name="다른조간사",
        email="other-group-sec@example.com",
        group_no=4,
    )
    building = make_building(reviewer_id=reviewer.id, mgmt_no="INQ-BLOCK-001")
    inquiry = Inquiry(
        building_id=building.id,
        mgmt_no=building.mgmt_no,
        phase="preliminary",
        submitter_id=reviewer_user.id,
        submitter_name=reviewer_user.name,
        content="다른 조 문의",
    )
    db_session.add(inquiry)
    db_session.commit()
    db_session.refresh(inquiry)

    res = client.delete(f"/api/reviews/inquiry/{inquiry.id}", headers=secretary_headers)
    assert res.status_code == 403


def test_other_group_secretary_cannot_update_inquiry_status(
    client, db_session, make_reviewer, make_building, make_user
):
    reviewer_user, reviewer, _ = make_reviewer(group_no=5)
    _, secretary_headers = make_user(
        UserRole.SECRETARY,
        name="5조아닌간사",
        email="not-group5-sec@example.com",
        group_no=6,
    )
    building = make_building(reviewer_id=reviewer.id, mgmt_no="INQ-PATCH-BLOCK-001")
    inquiry = Inquiry(
        building_id=building.id,
        mgmt_no=building.mgmt_no,
        phase="preliminary",
        submitter_id=reviewer_user.id,
        submitter_name=reviewer_user.name,
        content="다른 조 상태 변경 차단",
    )
    db_session.add(inquiry)
    db_session.commit()
    db_session.refresh(inquiry)

    res = client.patch(
        f"/api/reviews/inquiry/{inquiry.id}",
        headers=secretary_headers,
        json={"status": "completed"},
    )
    assert res.status_code == 403


def test_my_inquiries_only_returns_own_by_submitter_id(
    client, db_session, make_user
):
    """동명이인 사용자 2명이 같은 이름이지만, my-inquiries는 submitter_id로만 매칭."""
    user_a, headers_a = make_user(UserRole.REVIEWER, name="홍길동", email="a@example.com")
    user_b, headers_b = make_user(UserRole.REVIEWER, name="홍길동", email="b@example.com")

    # 둘 다 직접 Inquiry insert (B의 문의)
    inquiry_b = Inquiry(
        building_id=1,
        mgmt_no="ANY-001",
        phase="preliminary",
        submitter_id=user_b.id,
        submitter_name=user_b.name,
        content="B의 문의",
    )
    db_session.add(inquiry_b)
    db_session.commit()

    res = client.get("/api/reviews/my-inquiries", headers=headers_a)
    assert res.status_code == 200
    payload = res.json()
    assert payload["total"] == 0  # A는 자기 문의 0건

    res2 = client.get("/api/reviews/my-inquiries", headers=headers_b)
    assert res2.status_code == 200
    payload2 = res2.json()
    assert payload2["total"] == 1
