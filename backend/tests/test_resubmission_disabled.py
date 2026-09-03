"""재제출 요청 접수를 닫았을 때의 동작 테스트.

운영에서 재제출 요청은 더 이상 받지 않기로 해 `resubmission_request_enabled`
기본값을 False 로 두었다. 접수를 닫아도 이미 들어온 요청의 조회·처리는 계속
되어야 한다(미처리 건이 남아 있기 때문).
"""

from datetime import date

from config import settings
from models.resubmission_request import ResubmissionRequest, ResubmissionStatus
from models.review_stage import PhaseType, ReviewStage
from models.user import UserRole


def _setup_received_building(db_session, make_reviewer, make_building):
    user, reviewer, headers = make_reviewer()
    building = make_building(reviewer_id=reviewer.id, mgmt_no="RS-OFF-0001")
    building.current_phase = "doc_received"
    building.assigned_reviewer_name = user.name
    db_session.add(ReviewStage(
        building_id=building.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
        doc_received_at=date(2026, 8, 1),
        report_due_date=date(2026, 8, 15),
    ))
    db_session.commit()
    return user, headers, building


def test_기본값은_접수_비활성이다():
    assert settings.resubmission_request_enabled is False


def test_접수를_닫으면_신규_요청이_거부된다(
    client, db_session, make_reviewer, make_building
):
    _user, headers, building = _setup_received_building(
        db_session, make_reviewer, make_building
    )

    res = client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "구조계산서 누락"},
        headers=headers,
    )
    assert res.status_code == 403
    assert "종료" in res.json()["detail"]
    assert db_session.query(ResubmissionRequest).count() == 0


def test_상태_엔드포인트가_접수_가능_여부를_알려준다(
    client, make_reviewer
):
    _user, _reviewer, headers = make_reviewer()

    res = client.get("/api/resubmissions/status", headers=headers)
    assert res.status_code == 200
    assert res.json() == {"enabled": False}

    original = settings.resubmission_request_enabled
    settings.resubmission_request_enabled = True
    try:
        res = client.get("/api/resubmissions/status", headers=headers)
        assert res.json() == {"enabled": True}
    finally:
        settings.resubmission_request_enabled = original


def test_접수를_닫아도_기존_요청은_조회되고_처리된다(
    client, db_session, make_user, make_reviewer, make_building
):
    """미처리 32건이 남아 있으므로 조회·처리 경로는 막지 않는다."""
    user, headers, building = _setup_received_building(
        db_session, make_reviewer, make_building
    )
    req = ResubmissionRequest(
        building_id=building.id,
        mgmt_no=building.mgmt_no,
        phase="preliminary",
        from_phase="doc_received",
        reason="접수 종료 전에 들어온 요청",
        requester_id=user.id,
        requester_name=user.name,
        status=ResubmissionStatus.PENDING,
    )
    db_session.add(req)
    db_session.commit()
    db_session.refresh(req)

    # 검토위원 본인 조회
    res = client.get("/api/resubmissions/my", headers=headers)
    assert res.status_code == 200
    assert res.json()["total"] == 1

    # 간사 목록 조회
    _sec, sec_headers = make_user(UserRole.CHIEF_SECRETARY)
    res = client.get("/api/resubmissions", headers=sec_headers)
    assert res.status_code == 200
    assert res.json()["total"] == 1

    # 간사 처리
    res = client.patch(
        f"/api/resubmissions/{req.id}",
        json={"status": "rejected", "handler_memo": "접수 종료로 반려"},
        headers=sec_headers,
    )
    assert res.status_code == 200, res.text
    db_session.expire_all()
    assert req.status == ResubmissionStatus.REJECTED
