"""도서 재접수 시 검토서 제출 이력 초기화 회귀 테스트.

- 같은 단계의 stage가 검토서 제출 이력을 가진 채로 도서가 다시 접수되면
  제출 이력 + S3 키 + InappropriateNote가 모두 정리되어야 한다.
- 이력이 없는 stage 재접수는 doc_received_at만 갱신되고 부수효과가 없어야 한다.
"""

from datetime import date, timedelta

from models.audit_log import AuditLog
from models.inappropriate_note import InappropriateNote
from models.review_stage import PhaseType, ResultType, ReviewStage
from models.user import UserRole


def _admin_headers(make_user):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    return headers


def test_re_receive_clears_submitted_review(
    client, db_session, make_user, make_building
):
    headers = _admin_headers(make_user)
    building = make_building(mgmt_no="RE-0001")

    # 검토서 제출까지 끝난 예비검토 stage를 강제로 만든다.
    submitted_at = date.today() - timedelta(days=3)
    stage = ReviewStage(
        building_id=building.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
        doc_received_at=submitted_at - timedelta(days=10),
        report_due_date=submitted_at - timedelta(days=1),
        report_submitted_at=submitted_at,
        reviewer_name="검토위원A",
        result=ResultType.PASS,
        review_opinion="OK",
        defect_type_1="defect-1",
        s3_file_key="reviews/preliminary/2026/04/RE-0001.xlsm",
        inappropriate_review_needed=True,
    )
    db_session.add(stage)
    db_session.commit()
    db_session.refresh(stage)

    note = InappropriateNote(
        stage_id=stage.id,
        author_id=1,
        author_name="간사",
        content="부적합 의견",
    )
    db_session.add(note)
    # 운영 시나리오: 어떤 이유로 building이 다시 접수 상태로 환원되어 있다.
    building.current_phase = "doc_received"
    db_session.commit()

    res = client.post(
        "/api/distribution/receive",
        headers=headers,
        json={"mgmt_nos": ["RE-0001"]},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["updated"] == 1

    db_session.expire_all()
    refreshed = db_session.query(ReviewStage).filter_by(id=stage.id).one()
    # 검토서 제출 이력은 모두 초기화
    assert refreshed.report_submitted_at is None
    assert refreshed.reviewer_name is None
    assert refreshed.result is None
    assert refreshed.review_opinion is None
    assert refreshed.defect_type_1 is None
    assert refreshed.s3_file_key is None
    assert refreshed.inappropriate_review_needed is False
    # 도서 접수 정보는 갱신
    assert refreshed.doc_received_at == date.today()
    assert refreshed.report_due_date == date.today() + timedelta(days=14)

    # InappropriateNote 자식 행도 함께 정리
    notes_left = (
        db_session.query(InappropriateNote)
        .filter(InappropriateNote.stage_id == stage.id)
        .count()
    )
    assert notes_left == 0

    # 호출 단위 reset 감사 로그가 1건 남는다
    reset_logs = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "reset", AuditLog.target_type == "review_stage")
        .all()
    )
    assert len(reset_logs) == 1
    assert reset_logs[0].after_data["reset_count"] == 1


def test_re_receive_without_history_does_not_log_reset(
    client, db_session, make_user, make_building
):
    """검토서 이력이 없는 stage를 재접수해도 reset 감사 로그가 남지 않아야 한다."""
    headers = _admin_headers(make_user)
    building = make_building(mgmt_no="RE-0002")

    stage = ReviewStage(
        building_id=building.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
        doc_received_at=date.today() - timedelta(days=5),
        report_due_date=date.today() + timedelta(days=9),
    )
    db_session.add(stage)
    building.current_phase = "doc_received"
    db_session.commit()

    res = client.post(
        "/api/distribution/receive",
        headers=headers,
        json={"mgmt_nos": ["RE-0002"]},
    )
    assert res.status_code == 200, res.text

    reset_logs = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "reset", AuditLog.target_type == "review_stage")
        .all()
    )
    assert reset_logs == []


def test_re_receive_clears_only_inappropriate_note(
    client, db_session, make_user, make_building
):
    """제출 필드는 비어 있고 InappropriateNote만 남은 stage도 재접수 시 정리된다."""
    headers = _admin_headers(make_user)
    building = make_building(mgmt_no="RE-0003")

    stage = ReviewStage(
        building_id=building.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
        doc_received_at=date.today() - timedelta(days=5),
        report_due_date=date.today() + timedelta(days=9),
    )
    db_session.add(stage)
    db_session.commit()
    db_session.refresh(stage)

    db_session.add(InappropriateNote(
        stage_id=stage.id, author_id=1, author_name="간사", content="잔여 의견",
    ))
    building.current_phase = "doc_received"
    db_session.commit()

    res = client.post(
        "/api/distribution/receive",
        headers=headers,
        json={"mgmt_nos": ["RE-0003"]},
    )
    assert res.status_code == 200, res.text

    db_session.expire_all()
    notes_left = (
        db_session.query(InappropriateNote)
        .filter(InappropriateNote.stage_id == stage.id)
        .count()
    )
    assert notes_left == 0


def test_re_receive_clears_objection_only_history(
    client, db_session, make_user, make_building
):
    """이의신청 필드만 채워진 stage도 재접수 시 초기화된다."""
    headers = _admin_headers(make_user)
    building = make_building(mgmt_no="RE-0004")

    stage = ReviewStage(
        building_id=building.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
        doc_received_at=date.today() - timedelta(days=5),
        report_due_date=date.today() + timedelta(days=9),
        objection_filed=True,
        objection_content="이의 본문",
        objection_reason="사유",
    )
    db_session.add(stage)
    building.current_phase = "doc_received"
    db_session.commit()
    db_session.refresh(stage)

    res = client.post(
        "/api/distribution/receive",
        headers=headers,
        json={"mgmt_nos": ["RE-0004"]},
    )
    assert res.status_code == 200, res.text

    db_session.expire_all()
    refreshed = db_session.query(ReviewStage).filter_by(id=stage.id).one()
    assert refreshed.objection_filed is False
    assert refreshed.objection_content is None
    assert refreshed.objection_reason is None


def test_re_receive_survives_s3_delete_exception(
    client, db_session, make_user, make_building, monkeypatch
):
    """delete_file이 예외를 던져도 receive는 200으로 정상 응답해야 한다."""
    from routers import distribution as dist_module

    def _boom(_key):
        raise RuntimeError("S3 일시 장애")

    monkeypatch.setattr(dist_module, "delete_file", _boom)

    headers = _admin_headers(make_user)
    building = make_building(mgmt_no="RE-0005")

    stage = ReviewStage(
        building_id=building.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
        doc_received_at=date.today() - timedelta(days=5),
        report_due_date=date.today() + timedelta(days=9),
        report_submitted_at=date.today() - timedelta(days=2),
        s3_file_key="reviews/preliminary/2026/04/RE-0005.xlsm",
    )
    db_session.add(stage)
    building.current_phase = "doc_received"
    db_session.commit()
    db_session.refresh(stage)

    res = client.post(
        "/api/distribution/receive",
        headers=headers,
        json={"mgmt_nos": ["RE-0005"]},
    )
    assert res.status_code == 200, res.text

    db_session.expire_all()
    refreshed = db_session.query(ReviewStage).filter_by(id=stage.id).one()
    assert refreshed.s3_file_key is None
    assert refreshed.report_submitted_at is None
