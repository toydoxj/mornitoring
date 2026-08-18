"""재제출 요청 회귀 테스트.

- RESUBMIT 트리거 매트릭스 (접수 상태 → 직전 단계만 허용)
- POST /api/resubmissions: 단계 되돌림 + 제출 예정일 삭제 + 로그 2종
- 접수 상태가 아니거나 담당이 아니면 거부, 중복 요청 거부
- 목록 가시성: 조 배정 간사는 자기 조만, 관리원은 전체 조회·처리 가능
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

def test_create_resubmission_keeps_phase_and_due_date(
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
    assert body["phase"] == "preliminary"
    assert body["current_phase"] == "doc_received"

    db_session.expire_all()
    # 단계 되돌리기·예정일 삭제는 간사가 한다 — 요청만으로는 그대로여야 한다
    assert building.current_phase == "doc_received"
    assert stage.report_due_date == date(2026, 8, 15)

    req = db_session.query(ResubmissionRequest).one()
    assert req.mgmt_no == building.mgmt_no
    assert req.phase == "preliminary"
    assert req.from_phase == "doc_received"
    assert req.to_phase is None
    assert req.cleared_due_date is None
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

    # 등록만으로는 단계가 바뀌지 않으므로 전환 로그도 없다
    assert (
        db_session.query(PhaseTransitionLog)
        .filter(PhaseTransitionLog.mgmt_no == building.mgmt_no)
        .count()
        == 0
    )

    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "resubmission_request")
        .one()
    )
    assert audit.user_id == user.id
    assert audit.target_type == "building"
    assert audit.target_id == building.id
    assert audit.after_data["current_phase"] == "doc_received"
    assert audit.after_data["report_due_date"] == "2026-08-15"
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

    # 대기중 요청이 남아 있으면 중복 등록 금지
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


def test_manager_can_read_and_update(
    client, db_session, make_user, make_reviewer, make_building
):
    """관리원은 전체 조회 + 처리까지 가능하다."""
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
    updated = client.patch(
        f"/api/resubmissions/{req_id}",
        json={"status": "completed"},
        headers=manager_headers,
    )
    assert updated.status_code == 200

    db_session.expire_all()
    req = db_session.get(ResubmissionRequest, req_id)
    assert req.status == ResubmissionStatus.COMPLETED


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
    assert item["current_phase"] == "doc_received"
    assert item["reviewer_group_no"] == 3
    assert item["current_due_date"] == "2026-08-15"
    assert item["cleared_due_date"] is None


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

def test_my_reviews_reflects_secretary_actions(
    client, db_session, make_user, make_reviewer, make_building
):
    """간사가 처리하기 전까지는 내 검토 대상이 그대로고, 처리 후 반영된다."""
    _, _, headers, building, _ = _setup_received_building(
        db_session, make_reviewer, make_building
    )

    before = client.get("/api/buildings/my-reviews", headers=headers).json()["items"][0]
    assert before["report_due_date"] == "2026-08-15"
    assert before["current_phase"] == "doc_received"

    req_id = client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    ).json()["id"]

    # 요청만으로는 화면이 그대로
    mid = client.get("/api/buildings/my-reviews", headers=headers).json()["items"][0]
    assert mid["report_due_date"] == "2026-08-15"
    assert mid["current_phase"] == "doc_received"

    # 간사가 단계 되돌리기 + 예정일 삭제
    _, chief_headers = make_user(UserRole.CHIEF_SECRETARY)
    client.patch(
        f"/api/resubmissions/{req_id}",
        json={"action": "complete"},
        headers=chief_headers,
    )

    after = client.get("/api/buildings/my-reviews", headers=headers).json()["items"][0]
    assert after["report_due_date"] is None
    assert after["current_phase"] == "assigned"


def test_due_date_assigned_on_re_receive(
    client, db_session, make_user, make_reviewer, make_building
):
    """간사가 되돌린 뒤 도서가 다시 접수되면 예정일이 새로 부여된다."""
    _, _, headers, building, stage = _setup_received_building(
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
        json={"action": "complete"},
        headers=chief_headers,
    )
    db_session.expire_all()
    assert building.current_phase == "assigned"

    # 총괄간사가 재제출된 도서를 접수 (예정일 명시)
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


# ===== 간사 처리: 처리완료 =====

def test_complete_rolls_back_and_clears_due_date(
    client, db_session, make_user, make_reviewer, make_building
):
    """처리완료는 단계 되돌리기와 예정일 삭제를 함께 수행한다."""
    _, _, headers, building, stage = _setup_received_building(
        db_session, make_reviewer, make_building
    )
    req_id = client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    ).json()["id"]
    chief, chief_headers = make_user(UserRole.CHIEF_SECRETARY)

    res = client.patch(
        f"/api/resubmissions/{req_id}",
        json={"action": "complete"},
        headers=chief_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["rolled_back_to"] == "assigned"
    assert body["cleared_due_date"] == "2026-08-15"

    db_session.expire_all()
    assert building.current_phase == "assigned"
    assert stage.report_due_date is None

    req = db_session.get(ResubmissionRequest, req_id)
    assert req.status == ResubmissionStatus.COMPLETED
    assert req.from_phase == "doc_received"
    assert req.to_phase == "assigned"
    assert req.cleared_due_date == "2026-08-15"
    assert req.handled_by == chief.id
    assert req.handled_at is not None

    log = (
        db_session.query(PhaseTransitionLog)
        .filter(PhaseTransitionLog.mgmt_no == building.mgmt_no)
        .one()
    )
    assert log.trigger == "resubmit"
    assert log.from_phase == "doc_received"
    assert log.to_phase == "assigned"
    assert log.actor_user_id == chief.id

    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "resubmission_update")
        .one()
    )
    assert audit.after_data["action"] == "complete"
    assert audit.after_data["rolled_back_to"] == "assigned"
    assert audit.after_data["cleared_due_date"] == "2026-08-15"


def test_complete_from_supplement_round(
    client, db_session, make_user, make_reviewer, make_building
):
    """보완 차수에서도 바로 앞 제출 단계로 되돌아간다."""
    user, reviewer, headers = make_reviewer()
    building = make_building(reviewer_id=reviewer.id, mgmt_no="RS-SUP1")
    building.current_phase = "supplement_1_received"
    building.assigned_reviewer_name = user.name
    db_session.add(ReviewStage(
        building_id=building.id,
        phase=PhaseType.SUPPLEMENT_1,
        phase_order=1,
        doc_received_at=date(2026, 8, 1),
        report_due_date=date(2026, 8, 15),
    ))
    db_session.commit()

    req_id = client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    ).json()["id"]
    _, chief_headers = make_user(UserRole.CHIEF_SECRETARY)

    res = client.patch(
        f"/api/resubmissions/{req_id}",
        json={"action": "complete"},
        headers=chief_headers,
    )
    assert res.status_code == 200
    assert res.json()["rolled_back_to"] == "preliminary"

    db_session.expire_all()
    assert building.current_phase == "preliminary"


def test_complete_is_idempotent(
    client, db_session, make_user, make_reviewer, make_building
):
    """이미 처리된 항목은 건너뛰므로 두 번 눌러도 오류가 나지 않는다."""
    _, _, headers, building, stage = _setup_received_building(
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
        json={"action": "complete"},
        headers=chief_headers,
    )
    again = client.patch(
        f"/api/resubmissions/{req_id}",
        json={"action": "complete"},
        headers=chief_headers,
    )
    assert again.status_code == 200
    assert again.json()["rolled_back_to"] is None
    assert again.json()["cleared_due_date"] is None

    db_session.expire_all()
    # 단계가 두 번 되돌아가지 않아야 한다
    assert building.current_phase == "assigned"
    assert stage.report_due_date is None
    assert (
        db_session.query(PhaseTransitionLog)
        .filter(PhaseTransitionLog.mgmt_no == building.mgmt_no)
        .count()
        == 1
    )


def test_complete_rejected_when_not_received(
    client, db_session, make_user, make_reviewer, make_building
):
    """접수 상태가 아니면 처리완료가 400 (되돌릴 단계가 없음)."""
    _, _, headers, building, _ = _setup_received_building(
        db_session, make_reviewer, make_building
    )
    req_id = client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    ).json()["id"]

    building.current_phase = "preliminary"
    db_session.commit()
    _, chief_headers = make_user(UserRole.CHIEF_SECRETARY)

    res = client.patch(
        f"/api/resubmissions/{req_id}",
        json={"action": "complete"},
        headers=chief_headers,
    )
    assert res.status_code == 400
    assert "도서 접수 상태가 아니" in res.json()["detail"]

    db_session.expire_all()
    assert building.current_phase == "preliminary"


def test_complete_with_memo(
    client, db_session, make_user, make_reviewer, make_building
):
    """처리 메모를 함께 저장할 수 있다."""
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
        json={"action": "complete", "reply": "설계사에 재제출 요청함"},
        headers=chief_headers,
    )

    db_session.expire_all()
    req = db_session.get(ResubmissionRequest, req_id)
    assert req.reply == "설계사에 재제출 요청함"
    assert req.status == ResubmissionStatus.COMPLETED


# ===== 간사 처리: 반려 =====

def test_reject_keeps_phase_and_due_date(
    client, db_session, make_user, make_reviewer, make_building, monkeypatch
):
    """반려는 단계·예정일을 건드리지 않고 상태만 반려로 바꾼다."""
    from services import resubmission_notify

    sent = {}

    async def _fake_notify(db, sender, req):
        sent["mgmt_no"] = req.mgmt_no
        sent["sender_id"] = sender.id
        return True

    monkeypatch.setattr(
        "routers.resubmissions.notify_resubmission_rejected", _fake_notify
    )

    _, _, headers, building, stage = _setup_received_building(
        db_session, make_reviewer, make_building
    )
    req_id = client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    ).json()["id"]
    chief, chief_headers = make_user(UserRole.CHIEF_SECRETARY)

    res = client.patch(
        f"/api/resubmissions/{req_id}",
        json={"action": "reject"},
        headers=chief_headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["notified"] is True
    assert res.json()["rolled_back_to"] is None

    db_session.expire_all()
    # 단계·예정일 모두 그대로
    assert building.current_phase == "doc_received"
    assert stage.report_due_date == date(2026, 8, 15)
    assert (
        db_session.query(PhaseTransitionLog)
        .filter(PhaseTransitionLog.mgmt_no == building.mgmt_no)
        .count()
        == 0
    )

    req = db_session.get(ResubmissionRequest, req_id)
    assert req.status == ResubmissionStatus.REJECTED
    assert req.to_phase is None
    assert req.cleared_due_date is None
    assert req.handled_by == chief.id

    assert sent == {"mgmt_no": building.mgmt_no, "sender_id": chief.id}
    assert resubmission_notify.RESUBMISSION_REJECTED_TEMPLATE == "resubmission_rejected"


def test_reject_message_body(db_session, make_reviewer, make_building, client):
    """반려 알림 본문은 '현 도서로 검토 바랍니다' 문구를 담는다."""
    from services.resubmission_notify import compose_rejected_message

    _, _, headers, building, _ = _setup_received_building(
        db_session, make_reviewer, make_building
    )
    client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    )
    req = db_session.query(ResubmissionRequest).one()

    title, message = compose_rejected_message(req)
    assert building.mgmt_no in title
    assert f"관리번호 {building.mgmt_no}은 현 도서로 검토 바랍니다." in message

    req.reply = "도서 이상 없음"
    title, message = compose_rejected_message(req)
    assert "사유: 도서 이상 없음" in message


def test_reject_survives_notification_failure(
    client, db_session, make_user, make_reviewer, make_building, monkeypatch
):
    """카카오 발송이 실패해도 반려 처리 자체는 저장된다."""
    async def _fail_notify(db, sender, req):
        return False

    monkeypatch.setattr(
        "routers.resubmissions.notify_resubmission_rejected", _fail_notify
    )

    _, _, headers, building, _ = _setup_received_building(
        db_session, make_reviewer, make_building
    )
    req_id = client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    ).json()["id"]
    _, chief_headers = make_user(UserRole.CHIEF_SECRETARY)

    res = client.patch(
        f"/api/resubmissions/{req_id}",
        json={"action": "reject"},
        headers=chief_headers,
    )
    assert res.status_code == 200
    assert res.json()["notified"] is False

    db_session.expire_all()
    req = db_session.get(ResubmissionRequest, req_id)
    assert req.status == ResubmissionStatus.REJECTED


def test_rejected_appears_in_closed_list(
    client, db_session, make_user, make_reviewer, make_building, monkeypatch
):
    """반려 건은 처리 완료 목록(closed)에 함께 나온다."""
    async def _ok(db, sender, req):
        return True

    monkeypatch.setattr("routers.resubmissions.notify_resubmission_rejected", _ok)

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
        json={"action": "reject"},
        headers=chief_headers,
    )

    pending = client.get(
        "/api/resubmissions", params={"status_filter": "pending"}, headers=chief_headers
    ).json()
    assert pending["total"] == 0

    closed = client.get(
        "/api/resubmissions", params={"status_filter": "closed"}, headers=chief_headers
    ).json()
    assert closed["total"] == 1
    assert closed["items"][0]["status"] == "rejected"
    # 반려 건은 단계·예정일이 그대로 노출된다
    assert closed["items"][0]["current_phase"] == "doc_received"
    assert closed["items"][0]["current_due_date"] == "2026-08-15"


# ===== 처리 권한 =====

def test_manager_can_complete(
    client, db_session, make_user, make_reviewer, make_building
):
    """관리원도 처리완료 — 단계 되돌리기·예정일 삭제가 그대로 적용된다."""
    _, _, headers, building, stage = _setup_received_building(
        db_session, make_reviewer, make_building
    )
    req_id = client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    ).json()["id"]
    manager, manager_headers = make_user(UserRole.MANAGER)

    res = _complete(client, req_id, manager_headers)
    assert res.status_code == 200, res.text

    db_session.expire_all()
    assert building.current_phase == "assigned"
    assert stage.report_due_date is None
    req = db_session.get(ResubmissionRequest, req_id)
    assert req.status == ResubmissionStatus.COMPLETED
    assert req.handled_by == manager.id


def test_manager_can_reject(
    client, db_session, make_user, make_reviewer, make_building, monkeypatch
):
    """관리원도 반려 — 단계·예정일은 유지되고 요청자 알림만 나간다."""
    async def _ok(db, sender, req):
        return True

    monkeypatch.setattr("routers.resubmissions.notify_resubmission_rejected", _ok)

    _, _, headers, building, stage = _setup_received_building(
        db_session, make_reviewer, make_building
    )
    req_id = client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    ).json()["id"]
    _, manager_headers = make_user(UserRole.MANAGER)

    res = client.patch(
        f"/api/resubmissions/{req_id}",
        json={"action": "reject"},
        headers=manager_headers,
    )
    assert res.status_code == 200, res.text

    db_session.expire_all()
    assert building.current_phase == "doc_received"
    assert stage.report_due_date == date(2026, 8, 15)
    req = db_session.get(ResubmissionRequest, req_id)
    assert req.status == ResubmissionStatus.REJECTED


def test_reviewer_cannot_process(
    client, db_session, make_reviewer, make_building
):
    """검토위원 본인도 처리할 수 없다."""
    _, _, headers, building, _ = _setup_received_building(
        db_session, make_reviewer, make_building
    )
    req_id = client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    ).json()["id"]

    res = client.patch(
        f"/api/resubmissions/{req_id}",
        json={"action": "complete"},
        headers=headers,
    )
    assert res.status_code == 403

    db_session.expire_all()
    assert building.current_phase == "doc_received"


def test_other_group_secretary_cannot_process(
    client, db_session, make_user, make_reviewer, make_building
):
    """다른 조 간사는 처리할 수 없다."""
    _, _, headers, building, _ = _setup_received_building(
        db_session, make_reviewer, make_building, group_no=1
    )
    req_id = client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    ).json()["id"]
    _, other_headers = make_user(UserRole.SECRETARY, group_no=2)

    res = client.patch(
        f"/api/resubmissions/{req_id}",
        json={"action": "complete"},
        headers=other_headers,
    )
    assert res.status_code == 403

    db_session.expire_all()
    assert building.current_phase == "doc_received"


def test_back_to_pending_clears_handler(
    client, db_session, make_user, make_reviewer, make_building
):
    """처리된 건을 대기로 되돌리면 처리자 정보가 지워진다."""
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
        json={"action": "complete"},
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


def test_memo_only_keeps_status(
    client, db_session, make_user, make_reviewer, make_building
):
    """action 없이 메모만 저장하면 상태·단계가 그대로다."""
    _, _, headers, building, stage = _setup_received_building(
        db_session, make_reviewer, make_building
    )
    req_id = client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    ).json()["id"]
    _, chief_headers = make_user(UserRole.CHIEF_SECRETARY)

    res = client.patch(
        f"/api/resubmissions/{req_id}",
        json={"reply": "확인 중"},
        headers=chief_headers,
    )
    assert res.status_code == 200

    db_session.expire_all()
    req = db_session.get(ResubmissionRequest, req_id)
    assert req.reply == "확인 중"
    assert req.status == ResubmissionStatus.PENDING
    assert building.current_phase == "doc_received"
    assert stage.report_due_date == date(2026, 8, 15)


def test_list_shows_due_date_state(
    client, db_session, make_user, make_reviewer, make_building
):
    """목록은 처리 전 current_due_date, 처리 후 cleared_due_date 를 보여준다."""
    _, _, headers, building, _ = _setup_received_building(
        db_session, make_reviewer, make_building
    )
    req_id = client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    ).json()["id"]
    _, chief_headers = make_user(UserRole.CHIEF_SECRETARY)

    before = client.get("/api/resubmissions", headers=chief_headers).json()["items"][0]
    assert before["current_due_date"] == "2026-08-15"
    assert before["cleared_due_date"] is None

    client.patch(
        f"/api/resubmissions/{req_id}",
        json={"action": "complete"},
        headers=chief_headers,
    )

    after = client.get(
        "/api/resubmissions", params={"status_filter": "closed"}, headers=chief_headers
    ).json()["items"][0]
    assert after["current_due_date"] is None
    assert after["cleared_due_date"] == "2026-08-15"


# ===== 간사 처리: 대기로 되돌리기 (실수 복구) =====

def _complete(client, req_id, headers):
    return client.patch(
        f"/api/resubmissions/{req_id}",
        json={"action": "complete"},
        headers=headers,
    )


def test_revert_restores_phase_and_due_date(
    client, db_session, make_user, make_reviewer, make_building
):
    """대기로 되돌리면 처리완료로 바꾼 단계와 예정일이 원상복구된다."""
    _, _, headers, building, stage = _setup_received_building(
        db_session, make_reviewer, make_building
    )
    req_id = client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    ).json()["id"]
    _, chief_headers = make_user(UserRole.CHIEF_SECRETARY)
    _complete(client, req_id, chief_headers)

    db_session.expire_all()
    assert building.current_phase == "assigned"
    assert stage.report_due_date is None

    res = client.patch(
        f"/api/resubmissions/{req_id}",
        json={"action": "revert"},
        headers=chief_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["restored_phase"] == "doc_received"
    assert body["restored_due_date"] == "2026-08-15"

    db_session.expire_all()
    assert building.current_phase == "doc_received"
    assert stage.report_due_date == date(2026, 8, 15)

    req = db_session.get(ResubmissionRequest, req_id)
    assert req.status == ResubmissionStatus.PENDING
    assert req.to_phase is None
    assert req.cleared_due_date is None
    assert req.handled_by is None
    assert req.handled_at is None

    # 복구도 전환 로그로 남는다 (되돌림 1건 + 복구 1건)
    logs = (
        db_session.query(PhaseTransitionLog)
        .filter(PhaseTransitionLog.mgmt_no == building.mgmt_no)
        .order_by(PhaseTransitionLog.id)
        .all()
    )
    assert [(log.from_phase, log.to_phase, log.trigger) for log in logs] == [
        ("doc_received", "assigned", "resubmit"),
        ("assigned", "doc_received", "manual"),
    ]
    assert f"#{req_id}" in (logs[-1].reason or "")

    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "resubmission_update")
        .order_by(AuditLog.id)
        .all()[-1]
    )
    assert audit.after_data["action"] == "revert"
    assert audit.after_data["restored_phase"] == "doc_received"
    assert audit.after_data["restored_due_date"] == "2026-08-15"


def test_can_complete_again_after_revert(
    client, db_session, make_user, make_reviewer, make_building
):
    """복구 후 다시 처리완료를 누르면 정상 처리된다."""
    _, _, headers, building, stage = _setup_received_building(
        db_session, make_reviewer, make_building
    )
    req_id = client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    ).json()["id"]
    _, chief_headers = make_user(UserRole.CHIEF_SECRETARY)

    _complete(client, req_id, chief_headers)
    client.patch(
        f"/api/resubmissions/{req_id}",
        json={"action": "revert"},
        headers=chief_headers,
    )
    again = _complete(client, req_id, chief_headers)
    assert again.status_code == 200
    assert again.json()["rolled_back_to"] == "assigned"
    assert again.json()["cleared_due_date"] == "2026-08-15"

    db_session.expire_all()
    assert building.current_phase == "assigned"
    assert stage.report_due_date is None


def test_revert_blocked_when_phase_changed_after(
    client, db_session, make_user, make_reviewer, make_building
):
    """처리완료 이후 단계가 또 바뀌었으면 임의 복구를 막는다."""
    _, _, headers, building, _ = _setup_received_building(
        db_session, make_reviewer, make_building
    )
    req_id = client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    ).json()["id"]
    _, chief_headers = make_user(UserRole.CHIEF_SECRETARY)
    _complete(client, req_id, chief_headers)

    # 도서가 다시 접수돼 단계가 앞으로 갔다
    client.post(
        "/api/distribution/receive",
        headers=chief_headers,
        json={"mgmt_nos": [building.mgmt_no], "received_date": "2026-09-01"},
    )

    res = client.patch(
        f"/api/resubmissions/{req_id}",
        json={"action": "revert"},
        headers=chief_headers,
    )
    assert res.status_code == 400
    assert "단계가 변경되어" in res.json()["detail"]

    db_session.expire_all()
    assert building.current_phase == "doc_received"
    req = db_session.get(ResubmissionRequest, req_id)
    assert req.status == ResubmissionStatus.COMPLETED


def test_revert_keeps_newer_due_date(
    client, db_session, make_user, make_reviewer, make_building
):
    """복구 시점에 새 예정일이 잡혀 있으면 옛 날짜로 덮어쓰지 않는다."""
    _, _, headers, building, stage = _setup_received_building(
        db_session, make_reviewer, make_building
    )
    req_id = client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    ).json()["id"]
    _, chief_headers = make_user(UserRole.CHIEF_SECRETARY)
    _complete(client, req_id, chief_headers)

    # 단계는 그대로 두고 예정일만 새로 잡힌 상황을 만든다
    db_session.expire_all()
    stage.report_due_date = date(2026, 10, 1)
    db_session.commit()

    res = client.patch(
        f"/api/resubmissions/{req_id}",
        json={"action": "revert"},
        headers=chief_headers,
    )
    assert res.status_code == 200
    assert res.json()["restored_due_date"] is None

    db_session.expire_all()
    assert stage.report_due_date == date(2026, 10, 1)
    req = db_session.get(ResubmissionRequest, req_id)
    assert req.cleared_due_date is None


def test_revert_rejected_request_only_changes_status(
    client, db_session, make_user, make_reviewer, make_building, monkeypatch
):
    """반려 건은 되돌릴 단계·예정일이 없으므로 상태만 대기로 돌아간다."""
    async def _ok(db, sender, req):
        return True

    monkeypatch.setattr("routers.resubmissions.notify_resubmission_rejected", _ok)

    _, _, headers, building, stage = _setup_received_building(
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
        json={"action": "reject"},
        headers=chief_headers,
    )

    res = client.patch(
        f"/api/resubmissions/{req_id}",
        json={"action": "revert"},
        headers=chief_headers,
    )
    assert res.status_code == 200
    assert res.json()["restored_phase"] is None

    db_session.expire_all()
    assert building.current_phase == "doc_received"
    assert stage.report_due_date == date(2026, 8, 15)
    req = db_session.get(ResubmissionRequest, req_id)
    assert req.status == ResubmissionStatus.PENDING
    assert req.handled_by is None


def test_revert_requires_manage_permission(
    client, db_session, make_user, make_reviewer, make_building
):
    """검토위원·다른 조 간사는 복구할 수 없다 (관리원은 가능)."""
    _, _, reviewer_headers, building, stage = _setup_received_building(
        db_session, make_reviewer, make_building, group_no=1
    )
    req_id = client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=reviewer_headers,
    ).json()["id"]
    _, chief_headers = make_user(UserRole.CHIEF_SECRETARY)
    _complete(client, req_id, chief_headers)

    _, other_headers = make_user(UserRole.SECRETARY, group_no=2)

    for hdr in (reviewer_headers, other_headers):
        res = client.patch(
            f"/api/resubmissions/{req_id}",
            json={"action": "revert"},
            headers=hdr,
        )
        assert res.status_code == 403

    db_session.expire_all()
    assert building.current_phase == "assigned"
    assert stage.report_due_date is None

    # 관리원은 조 제한 없이 복구할 수 있다
    _, manager_headers = make_user(UserRole.MANAGER)
    res = client.patch(
        f"/api/resubmissions/{req_id}",
        json={"action": "revert"},
        headers=manager_headers,
    )
    assert res.status_code == 200, res.text

    db_session.expire_all()
    assert building.current_phase == "doc_received"
    assert stage.report_due_date == date(2026, 8, 15)


# ===== 건물별 이력 (건물 상세 화면의 반려 안내) =====

def test_building_history_shows_rejection_to_assigned_reviewer(
    client, db_session, make_user, make_reviewer, make_building, monkeypatch
):
    """담당 검토위원은 건물 상세에서 반려 결과와 회신을 볼 수 있다."""
    async def _ok(db, sender, req):
        return True

    monkeypatch.setattr("routers.resubmissions.notify_resubmission_rejected", _ok)

    _, _, headers, building, _ = _setup_received_building(
        db_session, make_reviewer, make_building
    )
    req_id = client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    ).json()["id"]
    chief, chief_headers = make_user(UserRole.CHIEF_SECRETARY)
    client.patch(
        f"/api/resubmissions/{req_id}",
        json={"action": "reject", "reply": "도서 이상 없음"},
        headers=chief_headers,
    )

    res = client.get(
        f"/api/resubmissions/building/{building.mgmt_no}", headers=headers
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["status"] == "rejected"
    assert item["reply"] == "도서 이상 없음"
    assert item["handled_by_name"] == chief.name
    assert item["handled_at"] is not None


def test_building_history_hidden_from_other_reviewer(
    client, db_session, make_reviewer, make_building
):
    """담당이 아닌 검토위원에게는 건물 존재 자체를 숨긴다 (404)."""
    _, _, headers, building, _ = _setup_received_building(
        db_session, make_reviewer, make_building
    )
    client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    )
    _, _, other_headers = make_reviewer()

    res = client.get(
        f"/api/resubmissions/building/{building.mgmt_no}", headers=other_headers
    )
    assert res.status_code == 404


def test_building_history_group_scope_for_secretary(
    client, db_session, make_user, make_reviewer, make_building
):
    """조 배정 간사는 자기 조 건물만, 관리원은 전체를 본다."""
    _, _, headers, building, _ = _setup_received_building(
        db_session, make_reviewer, make_building, group_no=1
    )
    client.post(
        "/api/resubmissions",
        json={"mgmt_no": building.mgmt_no, "reason": "사유"},
        headers=headers,
    )

    _, other_headers = make_user(UserRole.SECRETARY, group_no=2)
    assert client.get(
        f"/api/resubmissions/building/{building.mgmt_no}", headers=other_headers
    ).status_code == 404

    _, own_headers = make_user(UserRole.SECRETARY, group_no=1)
    assert client.get(
        f"/api/resubmissions/building/{building.mgmt_no}", headers=own_headers
    ).json()["total"] == 1

    _, manager_headers = make_user(UserRole.MANAGER)
    assert client.get(
        f"/api/resubmissions/building/{building.mgmt_no}", headers=manager_headers
    ).json()["total"] == 1
