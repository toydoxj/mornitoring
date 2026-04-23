"""사용자 조 편성(group_no) 기능 회귀.

- PATCH /api/users/{id} 의 group_no 가 역할별로 적절한 곳(Reviewer vs User)에 저장되는지
- 1~7 범위 외 값은 422
- 검토위원에 group_no 설정 시 Reviewer 행이 없어도 자동 생성
- 응답에 통합 group_no 노출
- 알 수 없는 필드(extra)는 422
"""

from models.reviewer import Reviewer
from models.user import UserRole


def test_patch_user_group_no_for_secretary_writes_user_column(
    client, db_session, make_user
):
    _, admin_h = make_user(UserRole.CHIEF_SECRETARY)
    target, _ = make_user(UserRole.SECRETARY)

    res = client.patch(f"/api/users/{target.id}", headers=admin_h, json={"group_no": 3})
    assert res.status_code == 200, res.text
    assert res.json()["group_no"] == 3

    db_session.refresh(target)
    assert target.group_no == 3
    # 간사는 Reviewer 행을 생성하지 않는다.
    assert (
        db_session.query(Reviewer).filter(Reviewer.user_id == target.id).count() == 0
    )


def test_patch_user_group_no_for_reviewer_writes_reviewer_row(
    client, db_session, make_user, make_reviewer
):
    _, admin_h = make_user(UserRole.CHIEF_SECRETARY)
    user, reviewer, _ = make_reviewer()

    res = client.patch(f"/api/users/{user.id}", headers=admin_h, json={"group_no": 5})
    assert res.status_code == 200, res.text
    assert res.json()["group_no"] == 5

    db_session.refresh(reviewer)
    assert reviewer.group_no == 5
    # User.group_no 는 검토위원의 SoT 가 아니므로 건드리지 않는다.
    db_session.refresh(user)
    assert user.group_no is None


def test_patch_user_group_no_creates_reviewer_row_if_missing(
    client, db_session, make_user
):
    """검토위원 역할인데 Reviewer 행이 아직 없는 경우 group_no 설정 시 자동 생성."""
    _, admin_h = make_user(UserRole.CHIEF_SECRETARY)
    # 검토위원 직접 생성 (Reviewer 행 없는 상태)
    target, _ = make_user(UserRole.REVIEWER)

    res = client.patch(f"/api/users/{target.id}", headers=admin_h, json={"group_no": 2})
    assert res.status_code == 200, res.text
    assert res.json()["group_no"] == 2

    reviewer = (
        db_session.query(Reviewer).filter(Reviewer.user_id == target.id).one()
    )
    assert reviewer.group_no == 2


def test_patch_user_group_no_clear_to_null(client, db_session, make_user, make_reviewer):
    _, admin_h = make_user(UserRole.CHIEF_SECRETARY)
    user, reviewer, _ = make_reviewer()
    reviewer.group_no = 4
    db_session.commit()

    res = client.patch(f"/api/users/{user.id}", headers=admin_h, json={"group_no": None})
    assert res.status_code == 200, res.text
    assert res.json()["group_no"] is None
    db_session.refresh(reviewer)
    assert reviewer.group_no is None


def test_patch_user_group_no_out_of_range_rejected(client, make_user):
    _, admin_h = make_user(UserRole.CHIEF_SECRETARY)
    target, _ = make_user(UserRole.SECRETARY)

    for bad in (0, 8, -1, 99):
        res = client.patch(
            f"/api/users/{target.id}", headers=admin_h, json={"group_no": bad},
        )
        assert res.status_code == 422, f"bad={bad} should be 422"


def test_patch_user_unknown_field_rejected(client, make_user):
    _, admin_h = make_user(UserRole.CHIEF_SECRETARY)
    target, _ = make_user(UserRole.SECRETARY)

    res = client.patch(
        f"/api/users/{target.id}", headers=admin_h,
        json={"group_no": 1, "unknown_field": "x"},
    )
    assert res.status_code == 422


def test_list_users_returns_resolved_group_no(
    client, db_session, make_user, make_reviewer
):
    _, admin_h = make_user(UserRole.CHIEF_SECRETARY)
    secretary, _ = make_user(UserRole.SECRETARY)
    secretary.group_no = 2
    user_rev, reviewer, _ = make_reviewer()
    reviewer.group_no = 6
    db_session.commit()

    res = client.get("/api/users", headers=admin_h)
    assert res.status_code == 200
    items = {item["id"]: item for item in res.json()["items"]}

    assert items[secretary.id]["group_no"] == 2
    assert items[user_rev.id]["group_no"] == 6
