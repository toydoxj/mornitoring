"""재제출 요청 회귀 테스트.

- RESUBMIT 트리거 매트릭스 (접수 상태 → 직전 단계만 허용)
- POST /api/resubmissions: 단계 되돌림 + 제출 예정일 삭제 + 로그 2종
- 접수 상태가 아니거나 담당이 아니면 거부, 중복 요청 거부
- 목록 가시성: 조 배정 간사는 자기 조만, 관리원은 전체 조회 가능 / 수정 불가
- PATCH: 처리완료 시 처리자·처리일시 기록
"""

from datetime import date

import pytest

from models.audit_log import AuditLog
from models.phase_transition_log import PhaseTransitionLog
from models.resubmission_request import ResubmissionRequest, ResubmissionStatus
from models.review_stage import PhaseType, ReviewStage
from models.user import UserRole
from services.phase_transition import InvalidPhaseTransition, next_phase_for, transition_phase


# ===== 매트릭스 단위 =====

@pytest.mark.parametrize("from_phase,expected", [
    ("doc_received", "assigned"),
    ("supplement_1_received", "preliminary"),
    ("supplement_5_received", "supplement_4"),
    # 제출 상태·배정완료에서는 재제출 요청 불가
    ("preliminary", None),
    ("assigned", None),
    ("supplement_2", None),
])
def test_resubmit_matrix(from_phase, expected):
    assert next_phase_for("resubmit", from_phase) == expected


def test_resubmit_transition_rejects_non_received(db_session, make_building):
    b = make_building(mgmt_no="RS-REJECT")
    b.current_phase = "preliminary"
    db_session.commit()

    with pytest.raises(InvalidPhaseTransition):
        transition_phase(db_session, b, to_phase="doc_received", trigger="resubmit")


def test_resubmit_transition_rejects_wrong_target(db_session, make_building):
    b = make_building(mgmt_no="RS-JUMP")
    b.current_phase = "supplement_2_received"
    db_session.commit()

    # 두 단계 이상 되돌리기 금지 (기대값은 supplement_1)
    with pytest.raises(InvalidPhaseTransition):
        transition_phase(db_session, b, to_phase="preliminary", trigger="resubmit")


# ===== 헬퍼 =====

def _setup_received_building(db_session, make_reviewer, make_building, *, group_no=None):
    """접수 상태 + 제출 예정일이 있는 건물 한 건을 만든다."""
    user, reviewer, headers = make_reviewer(group_no)
    building = make_building(reviewer_id=reviewer.id, mgmt_no="RS-0001")
    building.current_phase = "doc_received"
    building.assigned_reviewer_name = user.name
    stage = ReviewStage(
        building_id=building.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
        doc_received_at=date(2026, 8, 1),
        report_due_date=date(2026, 8, 15),
    )
    db_session.add(stage)
    db_session.commit()
    return user, reviewer, headers, building, stage


# ===== 등록 =====

def test_create_resubmission_rolls_back_phase_and_clears_due_date(
    client, db_session, make_reviewer, make_building
):
    user, reviewer, headers, building, stage = _setup_received_building(
        db_session, make_reviewer, make_building
    )

    res = client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "구조계산서 누락"},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["from_phase"] == "doc_received"
    assert body["to_phase"] == "assigned"

    db_session.expire_all()
    assert building.current_phase == "assigned"
    assert stage.report_due_date is None

    req = db_session.query(ResubmissionRequest).one()
    assert req.mgmt_no == building.mgmt_no
    assert req.phase == "preliminary"
    assert req.from_phase == "doc_received"
    assert req.to_phase == "assigned"
    assert req.cleared_due_date == "2026-08-15"
    assert req.requester_id == user.id
    assert req.status == ResubmissionStatus.PENDING


def test_create_resubmission_writes_logs(
    client, db_session, make_reviewer, make_building
):
    user, reviewer, headers, building, _ = _setup_received_building(
        db_session, make_reviewer, make_building
    )

    client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "도면 불일치"},
        headers=headers,
    )

    phase_log = (
        db_session.query(PhaseTransitionLog)
        .filter(PhaseTransitionLog.mgmt_no == building.mgmt_no)
        .one()
    )
    assert phase_log.trigger == "resubmit"
    assert phase_log.from_phase == "doc_received"
    assert phase_log.to_phase == "assigned"
    assert phase_log.actor_user_id == user.id
    assert "도면 불일치" in (phase_log.reason or "")

    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "resubmission_request")
        .one()
    )
    assert audit.user_id == user.id
    assert audit.target_type == "building"
    assert audit.target_id == building.id
    assert audit.before_data["report_due_date"] == "2026-08-15"
    assert audit.after_data["current_phase"] == "assigned"
    assert audit.after_data["reason"] == "도면 불일치"


def test_create_resubmission_requires_received_phase(
    client, db_session, make_reviewer, make_building
):
    _, _, headers, building, _ = _setup_received_building(
        db_session, make_reviewer, make_building
    )
    building.current_phase = "preliminary"
    db_session.commit()

    res = client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    )
    assert res.status_code == 400
    assert "접수 상태" in res.json()["detail"]

    db_session.expire_all()
    assert building.current_phase == "preliminary"


def test_create_resubmission_rejects_other_reviewer(
    client, db_session, make_reviewer, make_building
):
    _, _, _, building, _ = _setup_received_building(
        db_session, make_reviewer, make_building
    )
    _, _, other_headers = make_reviewer()

    res = client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=other_headers,
    )
    assert res.status_code == 403

    db_session.expire_all()
    assert building.current_phase == "doc_received"


def test_create_resubmission_rejects_duplicate_pending(
    client, db_session, make_reviewer, make_building
):
    _, _, headers, building, _ = _setup_received_building(
        db_session, make_reviewer, make_building
    )

    first = client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "1차 사유"},
        headers=headers,
    )
    assert first.status_code == 201

    # 접수 상태로 되돌려도 대기중 요청이 남아 있으면 중복 등록 금지
    db_session.expire_all()
    building.current_phase = "doc_received"
    db_session.commit()

    second = client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "2차 사유"},
        headers=headers,
    )
    assert second.status_code == 400
    assert "대기 중" in second.json()["detail"]


def test_create_resubmission_requires_reason(
    client, db_session, make_reviewer, make_building
):
    _, _, headers, building, _ = _setup_received_building(
        db_session, make_reviewer, make_building
    )

    res = client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "   "},
        headers=headers,
    )
    assert res.status_code == 400
    assert db_session.query(ResubmissionRequest).count() == 0


# ===== 조회 =====

def test_my_resubmissions_lists_own_requests(
    client, db_session, make_reviewer, make_building
):
    _, _, headers, building, _ = _setup_received_building(
        db_session, make_reviewer, make_building
    )
    client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    )

    res = client.get("/api/resubmissions/my", headers=headers)
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) == 1
    assert items[0]["building_id"] == building.id
    assert items[0]["status"] == "pending"


def test_reviewer_cannot_list_all_requests(
    client, db_session, make_reviewer, make_building
):
    _, _, headers, _, _ = _setup_received_building(
        db_session, make_reviewer, make_building
    )
    assert client.get("/api/resubmissions", headers=headers).status_code == 403


def test_manager_can_read_but_not_update(
    client, db_session, make_user, make_reviewer, make_building
):
    _, _, headers, building, _ = _setup_received_building(
        db_session, make_reviewer, make_building
    )
    client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    )
    _, manager_headers = make_user(UserRole.MANAGER)

    listed = client.get("/api/resubmissions", headers=manager_headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    req_id = listed.json()["items"][0]["id"]
    denied = client.patch(
        f"/api/resubmissions/{req_id}",
        json={"status": "completed"},
        headers=manager_headers,
    )
    assert denied.status_code == 403


def test_secretary_sees_only_own_group(
    client, db_session, make_user, make_reviewer, make_building
):
    _, _, headers, building, _ = _setup_received_building(
        db_session, make_reviewer, make_building, group_no=1
    )
    client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    )

    _, same_group_headers = make_user(UserRole.SECRETARY, group_no=1)
    _, other_group_headers = make_user(UserRole.SECRETARY, group_no=2)

    same = client.get("/api/resubmissions", headers=same_group_headers)
    assert same.status_code == 200 and same.json()["total"] == 1

    other = client.get("/api/resubmissions", headers=other_group_headers)
    assert other.status_code == 200 and other.json()["total"] == 0


def test_list_includes_building_context(
    client, db_session, make_user, make_reviewer, make_building
):
    _, _, headers, building, _ = _setup_received_building(
        db_session, make_reviewer, make_building, group_no=3
    )
    client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    )
    _, chief_headers = make_user(UserRole.CHIEF_SECRETARY)

    item = client.get("/api/resubmissions", headers=chief_headers).json()["items"][0]
    assert item["building_name"] == building.building_name
    assert item["current_phase"] == "assigned"
    assert item["reviewer_group_no"] == 3
    assert item["cleared_due_date"] == "2026-08-15"


# ===== 처리 =====

def test_patch_marks_completed_with_handler(
    client, db_session, make_user, make_reviewer, make_building
):
    _, _, headers, building, _ = _setup_received_building(
        db_session, make_reviewer, make_building
    )
    created = client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    )
    req_id = created.json()["id"]
    chief, chief_headers = make_user(UserRole.CHIEF_SECRETARY)

    res = client.patch(
        f"/api/resubmissions/{req_id}",
        json={"reply": "설계사에 재제출 요청함", "status": "completed"},
        headers=chief_headers,
    )
    assert res.status_code == 200

    db_session.expire_all()
    req = db_session.get(ResubmissionRequest, req_id)
    assert req.status == ResubmissionStatus.COMPLETED
    assert req.reply == "설계사에 재제출 요청함"
    assert req.handled_by == chief.id
    assert req.handled_at is not None

    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "resubmission_update")
        .one()
    )
    assert audit.user_id == chief.id
    assert audit.after_data["status"] == "completed"


def test_patch_back_to_pending_clears_handler(
    client, db_session, make_user, make_reviewer, make_building
):
    _, _, headers, building, _ = _setup_received_building(
        db_session, make_reviewer, make_building
    )
    req_id = client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    ).json()["id"]
    _, chief_headers = make_user(UserRole.CHIEF_SECRETARY)

    client.patch(
        f"/api/resubmissions/{req_id}",
        json={"status": "completed"},
        headers=chief_headers,
    )
    client.patch(
        f"/api/resubmissions/{req_id}",
        json={"status": "pending"},
        headers=chief_headers,
    )

    db_session.expire_all()
    req = db_session.get(ResubmissionRequest, req_id)
    assert req.status == ResubmissionStatus.PENDING
    assert req.handled_by is None
    assert req.handled_at is None


def test_patch_denies_other_group_secretary(
    client, db_session, make_user, make_reviewer, make_building
):
    _, _, headers, building, _ = _setup_received_building(
        db_session, make_reviewer, make_building, group_no=1
    )
    req_id = client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    ).json()["id"]
    _, other_group_headers = make_user(UserRole.SECRETARY, group_no=2)

    res = client.patch(
        f"/api/resubmissions/{req_id}",
        json={"status": "completed"},
        headers=other_group_headers,
    )
    assert res.status_code == 403


# ===== 후속 흐름 =====

def test_my_reviews_hides_due_date_after_resubmission(
    client, db_session, make_reviewer, make_building
):
    """재제출 요청 후 내 검토 대상의 제출 예정일이 사라져야 한다."""
    _, _, headers, building, _ = _setup_received_building(
        db_session, make_reviewer, make_building
    )

    before = client.get("/api/buildings/my-reviews", headers=headers).json()["items"][0]
    assert before["report_due_date"] == "2026-08-15"
    assert before["current_phase"] == "doc_received"

    client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    )

    after = client.get("/api/buildings/my-reviews", headers=headers).json()["items"][0]
    assert after["report_due_date"] is None
    assert after["current_phase"] == "assigned"


def test_due_date_assigned_on_re_receive(
    client, db_session, make_user, make_reviewer, make_building
):
    """재제출 요청분도 도서가 다시 접수되면 예정일이 새로 부여된다."""
    _, _, headers, building, stage = _setup_received_building(
        db_session, make_reviewer, make_building
    )
    client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    )
    db_session.expire_all()
    assert building.current_phase == "assigned"
    assert stage.report_due_date is None

    # 총괄간사가 재제출된 도서를 접수 (예정일 명시)
    _, chief_headers = make_user(UserRole.CHIEF_SECRETARY)
    res = client.post(
        "/api/distribution/receive",
        headers=chief_headers,
        json={
            "mgmt_nos": [building.mgmt_no],
            "received_date": "2026-09-01",
            "report_due_date": "2026-09-20",
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["updated"] == 1

    db_session.expire_all()
    assert building.current_phase == "doc_received"
    # 기존 stage 를 재사용하며 접수일·예정일이 갱신된다 (stage 중복 생성 없음)
    stages = db_session.query(ReviewStage).filter_by(building_id=building.id).all()
    assert len(stages) == 1
    assert stages[0].doc_received_at == date(2026, 9, 1)
    assert stages[0].report_due_date == date(2026, 9, 20)


def test_due_date_defaults_to_14_days_on_re_receive(
    client, db_session, make_user, make_reviewer, make_building
):
    """예정일을 지정하지 않고 재접수하면 접수일 + 14일로 자동 기록된다."""
    _, _, headers, building, _ = _setup_received_building(
        db_session, make_reviewer, make_building
    )
    client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    )
    _, chief_headers = make_user(UserRole.CHIEF_SECRETARY)

    client.post(
        "/api/distribution/receive",
        headers=chief_headers,
        json={"mgmt_nos": [building.mgmt_no], "received_date": "2026-09-01"},
    )

    db_session.expire_all()
    stage = db_session.query(ReviewStage).filter_by(building_id=building.id).one()
    assert stage.report_due_date == date(2026, 9, 15)


def test_my_reviews_shows_due_date_again_after_re_receive(
    client, db_session, make_user, make_reviewer, make_building
):
    """재접수 후 내 검토 대상에 제출 예정일이 다시 보인다."""
    _, _, headers, building, _ = _setup_received_building(
        db_session, make_reviewer, make_building
    )
    client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    )
    _, chief_headers = make_user(UserRole.CHIEF_SECRETARY)
    client.post(
        "/api/distribution/receive",
        headers=chief_headers,
        json={"mgmt_nos": [building.mgmt_no], "received_date": "2026-09-01"},
    )

    item = client.get("/api/buildings/my-reviews", headers=headers).json()["items"][0]
    assert item["current_phase"] == "doc_received"
    assert item["report_due_date"] == "2026-09-15"


def test_re_receive_marks_request_and_logs(
    client, db_session, make_user, make_reviewer, make_building
):
    """재접수 시각이 요청에 기록되고 감사 로그가 남는다. 상태는 대기 유지."""
    _, _, headers, building, _ = _setup_received_building(
        db_session, make_reviewer, make_building
    )
    client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    )
    chief, chief_headers = make_user(UserRole.CHIEF_SECRETARY)
    client.post(
        "/api/distribution/receive",
        headers=chief_headers,
        json={"mgmt_nos": [building.mgmt_no], "received_date": "2026-09-01"},
    )

    db_session.expire_all()
    req = db_session.query(ResubmissionRequest).one()
    assert req.re_received_at is not None
    # 상태 전환은 간사가 직접 한다
    assert req.status == ResubmissionStatus.PENDING

    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "resubmission_re_receive")
        .one()
    )
    assert audit.user_id == chief.id
    assert audit.after_data["report_due_date"] == "2026-09-15"
    assert audit.after_data["mgmt_nos"] == [building.mgmt_no]


def test_re_receive_notification_includes_due_date(
    client, db_session, make_user, make_reviewer, make_building
):
    """재제출 요청분 접수 알림에도 검토서 요청 예정일이 안내된다."""
    _, _, headers, building, _ = _setup_received_building(
        db_session, make_reviewer, make_building
    )
    client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    )
    _, chief_headers = make_user(UserRole.CHIEF_SECRETARY)

    res = client.post(
        "/api/distribution/receive",
        headers=chief_headers,
        json={"mgmt_nos": [building.mgmt_no], "received_date": "2026-09-01"},
    )
    notifications = res.json()["notifications"]
    assert len(notifications) == 1
    assert notifications[0]["report_due_date"] == "2026-09-15"
    assert "검토서 요청 예정일: 2026-09-15" in notifications[0]["message"]


def test_resubmit_and_normal_share_one_notification(
    client, db_session, make_user, make_reviewer, make_building
):
    """재제출 요청분과 일반 접수분은 예정일이 같으므로 한 알림으로 묶인다."""
    user, reviewer, headers, building, _ = _setup_received_building(
        db_session, make_reviewer, make_building
    )
    other = make_building(reviewer_id=reviewer.id, mgmt_no="RS-0002")
    other.current_phase = "assigned"
    other.assigned_reviewer_name = user.name
    db_session.commit()

    client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    )
    _, chief_headers = make_user(UserRole.CHIEF_SECRETARY)

    res = client.post(
        "/api/distribution/receive",
        headers=chief_headers,
        json={
            "mgmt_nos": [building.mgmt_no, other.mgmt_no],
            "received_date": "2026-09-01",
        },
    )
    notifications = res.json()["notifications"]
    assert len(notifications) == 1
    assert sorted(notifications[0]["mgmt_nos"]) == [building.mgmt_no, other.mgmt_no]
    assert notifications[0]["report_due_date"] == "2026-09-15"

    db_session.expire_all()
    stages = {
        s.building_id: s
        for s in db_session.query(ReviewStage).filter(
            ReviewStage.building_id.in_([building.id, other.id])
        )
    }
    assert stages[building.id].report_due_date == date(2026, 9, 15)
    assert stages[other.id].report_due_date == date(2026, 9, 15)
