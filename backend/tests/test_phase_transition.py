"""building.current_phase 전환 가드 + 영구 로그 회귀.

- transition_phase 헬퍼 매트릭스 (통과/거부) 단위 테스트
- distribution.receive 가 RECEIVE 트리거 + 로그를 남기는지
- reviews.upload 가 출발 _received 일 때만 phase 전환 / 그 외엔 phase 불변 + 로그 X
- POST /buildings/{id}/phase 가 매트릭스 외 변경을 400 으로 거부
- PATCH /buildings/{id} 에서 current_phase 필드는 더 이상 받지 않음 (서버 사이드에서 무시)
- assignments.assign 신규 배정 시 INITIAL 로그
"""

import pytest

from models.phase_transition_log import PhaseTransitionLog
from models.user import UserRole
from services.phase_transition import (
    InvalidPhaseTransition,
    next_phase_for,
    transition_phase,
)


# ===== 헬퍼 단위 매트릭스 =====

@pytest.mark.parametrize("trigger,from_phase,expected", [
    ("initial", None, "assigned"),
    ("initial", "", "assigned"),
    ("receive", "assigned", "doc_received"),
    ("receive", "preliminary", "supplement_1_received"),
    ("receive", "supplement_4", "supplement_5_received"),
    ("upload", "doc_received", "preliminary"),
    ("upload", "supplement_5_received", "supplement_5"),
    # _received가 아닌 출발에서 upload 트리거 → None (no-op)
    ("upload", "preliminary", None),
    ("upload", "assigned", None),
    # receive 트리거가 _received 출발로 들어오면 매트릭스 외 → None
    ("receive", "doc_received", None),
])
def test_next_phase_for_matrix(trigger, from_phase, expected):
    assert next_phase_for(trigger, from_phase) == expected


def test_transition_phase_initial(db_session, make_building):
    b = make_building(mgmt_no="PT-INIT")
    b.current_phase = None
    db_session.commit()

    log = transition_phase(db_session, b, to_phase="assigned", trigger="initial")
    db_session.commit()

    assert b.current_phase == "assigned"
    assert log is not None
    assert log.from_phase is None and log.to_phase == "assigned"
    assert log.mgmt_no == "PT-INIT"
    assert log.trigger == "initial"


def test_transition_phase_no_op_when_same(db_session, make_building):
    b = make_building(mgmt_no="PT-NOOP")
    b.current_phase = "preliminary"
    db_session.commit()

    log = transition_phase(db_session, b, to_phase="preliminary", trigger="manual")
    db_session.commit()

    assert log is None
    assert (
        db_session.query(PhaseTransitionLog)
        .filter(PhaseTransitionLog.mgmt_no == "PT-NOOP")
        .count()
        == 0
    )


def test_transition_phase_rejects_off_matrix(db_session, make_building):
    b = make_building(mgmt_no="PT-BAD")
    b.current_phase = "preliminary"
    db_session.commit()

    # 임의 점프 (preliminary → supplement_3) — 매트릭스 외
    with pytest.raises(InvalidPhaseTransition):
        transition_phase(db_session, b, to_phase="supplement_3", trigger="manual")


# ===== 통합: distribution.receive =====

def test_distribution_receive_logs_transition(client, db_session, make_user, make_building):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    b = make_building(mgmt_no="PT-RC1")
    b.current_phase = "assigned"
    db_session.commit()

    res = client.post(
        "/api/distribution/receive", headers=headers,
        json={"mgmt_nos": ["PT-RC1"]},
    )
    assert res.status_code == 200, res.text
    db_session.expire_all()

    logs = (
        db_session.query(PhaseTransitionLog)
        .filter(PhaseTransitionLog.mgmt_no == "PT-RC1")
        .order_by(PhaseTransitionLog.created_at)
        .all()
    )
    # assigned → doc_received 1건
    assert len(logs) == 1
    assert logs[0].trigger == "receive"
    assert logs[0].from_phase == "assigned"
    assert logs[0].to_phase == "doc_received"


def test_distribution_receive_initial_then_receive_when_phase_missing(
    client, db_session, make_user, make_building
):
    """phase 없는 building에 도서접수 시 INITIAL → RECEIVE 두 단계 모두 기록."""
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    b = make_building(mgmt_no="PT-INIT-RC")
    b.current_phase = None
    db_session.commit()

    res = client.post(
        "/api/distribution/receive", headers=headers,
        json={"mgmt_nos": ["PT-INIT-RC"]},
    )
    assert res.status_code == 200, res.text
    db_session.expire_all()

    logs = (
        db_session.query(PhaseTransitionLog)
        .filter(PhaseTransitionLog.mgmt_no == "PT-INIT-RC")
        .order_by(PhaseTransitionLog.created_at)
        .all()
    )
    triggers = [l.trigger for l in logs]
    assert triggers == ["initial", "receive"]


# ===== 통합: PATCH /buildings — current_phase 필드는 무시 =====

def test_patch_building_rejects_current_phase(
    client, db_session, make_user, make_building
):
    """PATCH 본문에 current_phase 가 들어오면 명시적으로 422 거부 (조용한 무시 X)."""
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    b = make_building(mgmt_no="PT-PATCH")
    b.current_phase = "assigned"
    db_session.commit()

    res = client.patch(
        f"/api/buildings/{b.id}", headers=headers,
        json={"current_phase": "supplement_3", "building_name": "이름변경"},
    )
    assert res.status_code == 422

    # phase 와 이름 둘 다 변경되지 않아야 한다 (트랜잭션 안 일어남)
    db_session.refresh(b)
    assert b.current_phase == "assigned"


def test_patch_building_normal_fields_still_work(
    client, db_session, make_user, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    b = make_building(mgmt_no="PT-PATCH-OK")
    db_session.commit()

    res = client.patch(
        f"/api/buildings/{b.id}", headers=headers,
        json={"building_name": "이름변경"},
    )
    assert res.status_code == 200, res.text
    db_session.refresh(b)
    assert b.building_name == "이름변경"


# ===== 통합: POST /buildings/{id}/phase =====

def test_phase_change_endpoint_accepts_matrix(
    client, db_session, make_user, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    b = make_building(mgmt_no="PT-MAN-OK")
    b.current_phase = "doc_received"
    db_session.commit()

    res = client.post(
        f"/api/buildings/{b.id}/phase", headers=headers,
        json={"to_phase": "preliminary", "reason": "데이터 복구"},
    )
    assert res.status_code == 200, res.text
    db_session.refresh(b)
    assert b.current_phase == "preliminary"

    log = (
        db_session.query(PhaseTransitionLog)
        .filter(PhaseTransitionLog.mgmt_no == "PT-MAN-OK")
        .one()
    )
    assert log.trigger == "manual"
    assert log.reason == "데이터 복구"


def test_phase_change_endpoint_rejects_off_matrix(
    client, db_session, make_user, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    b = make_building(mgmt_no="PT-MAN-BAD")
    b.current_phase = "preliminary"
    db_session.commit()

    res = client.post(
        f"/api/buildings/{b.id}/phase", headers=headers,
        json={"to_phase": "supplement_4"},
    )
    assert res.status_code == 400


def test_phase_change_endpoint_requires_admin(client, make_user, make_building):
    _, headers = make_user(UserRole.SECRETARY)  # 간사는 PATCH는 가능하나 phase 변경은 admin
    b = make_building(mgmt_no="PT-MAN-PERM")
    res = client.post(
        f"/api/buildings/{b.id}/phase", headers=headers,
        json={"to_phase": "doc_received"},
    )
    assert res.status_code == 403


# ===== 통합: assignments.assign INITIAL =====

def test_assignments_assign_logs_initial(
    client, db_session, make_user, make_reviewer, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    _, reviewer, _ = make_reviewer()
    b = make_building(mgmt_no="PT-ASSIGN")
    b.current_phase = None
    db_session.commit()

    res = client.post(
        "/api/assignments/assign", headers=headers,
        json={"building_id": b.id, "reviewer_id": reviewer.id},
    )
    assert res.status_code == 200, res.text
    db_session.refresh(b)
    assert b.current_phase == "assigned"

    log = (
        db_session.query(PhaseTransitionLog)
        .filter(PhaseTransitionLog.mgmt_no == "PT-ASSIGN")
        .one()
    )
    assert log.trigger == "initial"
    assert log.from_phase is None
    assert log.to_phase == "assigned"
