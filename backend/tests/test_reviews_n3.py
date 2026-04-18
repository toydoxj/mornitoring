"""N3 — reviews.py 잔여 권한(upload/preview, upload, inquiry, my-inquiries) 회귀.

- upload/preview, upload: REVIEWER가 타 건물 mgmt_no로 호출 시 404 (파일 파싱 전 fail-fast)
- inquiry: 본인 담당 외 건물에 문의 등록 불가 → 403
- my-inquiries: submitter_id로만 매칭, 이름 같아도 다른 사용자 문의는 안 보임
"""

import io

from models.inquiry import Inquiry
from models.user import UserRole


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
