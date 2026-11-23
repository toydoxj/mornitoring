"""배정 경로 3개의 감사 로그 (issues #5)."""
from openpyxl import Workbook

from models.audit_log import AuditLog
from models.user import UserRole


def _reviewer_logs(db_session, building_id):
    return (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "change_reviewer", AuditLog.target_id == building_id)
        .order_by(AuditLog.id)
        .all()
    )


def _assignment_xlsx(tmp_path, rows):
    wb = Workbook()
    ws = wb.active
    ws.append(["관리번호", "검토위원"])
    for row in rows:
        ws.append(list(row))
    path = tmp_path / "assign.xlsx"
    wb.save(path)
    return path


def test_assign_writes_change_reviewer_audit_with_before_after(
    client, db_session, make_user, make_reviewer, make_building
):
    actor, headers = make_user(UserRole.CHIEF_SECRETARY)
    old_user, old_reviewer, _ = make_reviewer()
    new_user, new_reviewer, _ = make_reviewer()
    b = make_building(mgmt_no="AUD-ASSIGN")
    b.reviewer_id = old_reviewer.id
    b.assigned_reviewer_name = old_user.name
    db_session.commit()

    res = client.post("/api/assignments/assign", headers=headers,
                      json={"building_id": b.id, "reviewer_id": new_reviewer.id})
    assert res.status_code == 200, res.text

    (log,) = _reviewer_logs(db_session, b.id)
    assert log.user_id == actor.id and log.target_type == "building"
    assert log.before_data == {"mgmt_no": "AUD-ASSIGN", "reviewer_id": old_reviewer.id,
                               "assigned_reviewer_name": old_user.name}
    assert log.after_data == {"mgmt_no": "AUD-ASSIGN", "reviewer_id": new_reviewer.id,
                              "assigned_reviewer_name": new_user.name, "source": "assign_api"}


def test_assign_same_reviewer_writes_no_audit(
    client, db_session, make_user, make_reviewer, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    user, reviewer, _ = make_reviewer()
    b = make_building(mgmt_no="AUD-SAME")
    b.reviewer_id = reviewer.id
    b.assigned_reviewer_name = user.name
    db_session.commit()

    res = client.post("/api/assignments/assign", headers=headers,
                      json={"building_id": b.id, "reviewer_id": reviewer.id})
    assert res.status_code == 200
    assert _reviewer_logs(db_session, b.id) == []


def test_unassign_writes_change_reviewer_audit(
    client, db_session, make_user, make_reviewer, make_building
):
    actor, headers = make_user(UserRole.TEAM_LEADER)
    user, reviewer, _ = make_reviewer()
    b = make_building(mgmt_no="AUD-UNASSIGN")
    b.reviewer_id = reviewer.id
    b.assigned_reviewer_name = user.name
    db_session.commit()

    res = client.delete(f"/api/assignments/assign/{b.id}", headers=headers)
    assert res.status_code == 200

    (log,) = _reviewer_logs(db_session, b.id)
    assert log.user_id == actor.id
    assert log.before_data["reviewer_id"] == reviewer.id
    assert log.after_data["reviewer_id"] is None
    assert log.after_data["source"] == "unassign_api"


def test_unassign_without_reviewer_writes_no_audit(client, db_session, make_user, make_building):
    _, headers = make_user(UserRole.TEAM_LEADER)
    b = make_building(mgmt_no="AUD-UNASSIGN-NONE")
    b.reviewer_id = None
    db_session.commit()
    assert client.delete(f"/api/assignments/assign/{b.id}", headers=headers).status_code == 200
    assert _reviewer_logs(db_session, b.id) == []


def test_assignment_excel_apply_writes_audit_only_for_changed_buildings(
    client, db_session, make_user, make_reviewer, make_building, tmp_path
):
    actor, headers = make_user(UserRole.CHIEF_SECRETARY)
    old_user, old_reviewer, _ = make_reviewer()
    new_user, new_reviewer, _ = make_reviewer()
    changed = make_building(mgmt_no="AUD-XL-1")
    same = make_building(mgmt_no="AUD-XL-2")
    for b in (changed, same):
        b.reviewer_id = old_reviewer.id
        b.assigned_reviewer_name = old_user.name
    db_session.commit()
    path = _assignment_xlsx(tmp_path, [("AUD-XL-1", new_user.name), ("AUD-XL-2", old_user.name)])

    with open(path, "rb") as fh:
        res = client.post("/api/assignments/upload/apply", headers=headers,
                          files={"file": ("assign.xlsx", fh)})
    assert res.status_code == 200, res.text

    (log,) = _reviewer_logs(db_session, changed.id)
    assert log.user_id == actor.id
    assert log.before_data["reviewer_id"] == old_reviewer.id
    assert log.after_data["reviewer_id"] == new_reviewer.id
    assert log.after_data["source"] == "assignment_excel"
    assert log.after_data["batch_id"] == res.json()["batch_id"]
    assert res.json()["audit_logged"] == 1
    assert _reviewer_logs(db_session, same.id) == []


def test_assignment_excel_unregistered_name_logs_name_change_with_same_reviewer_id(
    db_session, make_reviewer, make_building, tmp_path
):
    """Review Focus 1: 미등록 이름은 reviewer_id 를 그대로 두고 이름만 바꾼다."""
    from engines.reviewer_assign import apply_assignment

    old_user, old_reviewer, _ = make_reviewer()
    b = make_building(mgmt_no="AUD-XL-UNREG")
    b.reviewer_id = old_reviewer.id
    b.assigned_reviewer_name = old_user.name
    db_session.commit()

    apply_assignment(_assignment_xlsx(tmp_path, [("AUD-XL-UNREG", "미등록위원")]), db_session,
                     actor_user_id=None)

    (log,) = _reviewer_logs(db_session, b.id)
    assert log.before_data["reviewer_id"] == log.after_data["reviewer_id"] == old_reviewer.id
    assert log.before_data["assigned_reviewer_name"] == old_user.name
    assert log.after_data["assigned_reviewer_name"] == "미등록위원"


def test_assignment_excel_duplicate_mgmt_no_logs_once_with_final_value(
    db_session, make_reviewer, make_building, tmp_path
):
    """Review Focus 2: 같은 관리번호 2행 → 로그 1건, 업로드 전 값 → 최종 값."""
    from engines.reviewer_assign import apply_assignment

    u1, r1, _ = make_reviewer()
    u2, r2, _ = make_reviewer()
    b = make_building(mgmt_no="AUD-XL-DUP")
    b.reviewer_id = None
    b.assigned_reviewer_name = None
    db_session.commit()

    apply_assignment(_assignment_xlsx(tmp_path, [("AUD-XL-DUP", u1.name), ("AUD-XL-DUP", u2.name)]),
                     db_session, actor_user_id=None)

    (log,) = _reviewer_logs(db_session, b.id)
    assert (log.before_data["reviewer_id"], log.after_data["reviewer_id"]) == (None, r2.id)


def test_building_patch_reviewer_change_records_before_data(
    client, db_session, make_user, make_reviewer, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    old_user, old_reviewer, _ = make_reviewer()
    new_user, new_reviewer, _ = make_reviewer()
    b = make_building(mgmt_no="AUD-PATCH")
    b.reviewer_id = old_reviewer.id
    b.assigned_reviewer_name = old_user.name
    db_session.commit()

    res = client.patch(f"/api/buildings/{b.id}", headers=headers,
                       json={"reviewer_id": new_reviewer.id})
    assert res.status_code == 200, res.text

    (log,) = _reviewer_logs(db_session, b.id)
    assert log.before_data["reviewer_id"] == old_reviewer.id
    assert log.after_data["reviewer_id"] == new_reviewer.id
    assert log.after_data["source"] == "building_patch"
    assert log.after_data["reviewer_name"] == new_user.name   # 기존 키 유지
