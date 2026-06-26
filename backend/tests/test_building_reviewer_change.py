"""건축물 상세 화면의 검토자 변경 회귀 테스트."""

from models.building import Building
from models.user import UserRole


def test_reviewer_options_are_registered_active_reviewers_in_scope(
    client, db_session, make_user, make_reviewer
):
    secretary, headers = make_user(UserRole.SECRETARY)
    secretary.group_no = 1
    same_group_user, same_group_reviewer, _ = make_reviewer(group_no=1)
    other_group_user, other_group_reviewer, _ = make_reviewer(group_no=2)
    inactive_user, inactive_reviewer, _ = make_reviewer(group_no=1)
    inactive_user.is_active = False
    db_session.commit()

    res = client.get("/api/buildings/reviewer-options", headers=headers)

    assert res.status_code == 200
    reviewer_ids = {item["reviewer_id"] for item in res.json()}
    assert same_group_reviewer.id in reviewer_ids
    assert other_group_reviewer.id not in reviewer_ids
    assert inactive_reviewer.id not in reviewer_ids

    item = next(
        option for option in res.json()
        if option["reviewer_id"] == same_group_reviewer.id
    )
    assert item["user_id"] == same_group_user.id
    assert item["name"] == same_group_user.name
    assert item["group_no"] == 1
    assert other_group_user.name not in {option["name"] for option in res.json()}


def test_building_reviewer_change_updates_reviewer_and_assigned_name(
    client, db_session, make_user, make_reviewer, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    old_user, old_reviewer, _ = make_reviewer(group_no=1)
    new_user, new_reviewer, _ = make_reviewer(group_no=2)
    building = make_building(reviewer_id=old_reviewer.id, mgmt_no="REV-CHANGE-001")
    building.assigned_reviewer_name = old_user.name
    db_session.commit()

    res = client.patch(
        f"/api/buildings/{building.id}",
        json={"reviewer_id": new_reviewer.id},
        headers=headers,
    )

    assert res.status_code == 200
    data = res.json()
    assert data["reviewer_id"] == new_reviewer.id
    assert data["reviewer_name"] == new_user.name
    assert data["assigned_reviewer_name"] == new_user.name

    db_session.expire_all()
    saved = db_session.get(Building, building.id)
    assert saved is not None
    assert saved.reviewer_id == new_reviewer.id
    assert saved.assigned_reviewer_name == new_user.name


def test_group_secretary_cannot_assign_other_group_reviewer(
    client, db_session, make_user, make_reviewer, make_building
):
    secretary, headers = make_user(UserRole.SECRETARY)
    secretary.group_no = 1
    same_group_user, same_group_reviewer, _ = make_reviewer(group_no=1)
    _other_user, other_group_reviewer, _ = make_reviewer(group_no=2)
    building = make_building(
        reviewer_id=same_group_reviewer.id,
        mgmt_no="REV-CHANGE-SCOPE-001",
    )
    building.assigned_reviewer_name = same_group_user.name
    db_session.commit()

    res = client.patch(
        f"/api/buildings/{building.id}",
        json={"reviewer_id": other_group_reviewer.id},
        headers=headers,
    )

    assert res.status_code == 403
