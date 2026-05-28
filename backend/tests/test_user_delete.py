"""사용자 삭제(비활성화) 회귀 테스트."""

from datetime import datetime, timedelta, timezone

from models.password_setup_token import (
    PasswordSetupToken,
    TokenDeliveryChannel,
    TokenPurpose,
)
from models.user import User, UserRole


def test_delete_user_soft_deactivates_and_hides_from_default_list(
    client, db_session, make_user
):
    _, admin_headers = make_user(UserRole.TEAM_LEADER)
    target, _ = make_user(UserRole.REVIEWER, name="이공우", email="egw@example.com")

    token = PasswordSetupToken(
        token_hash="delete_user_token_hash",
        user_id=target.id,
        purpose=TokenPurpose.INITIAL_SETUP,
        delivery_channel=TokenDeliveryChannel.MANUAL,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db_session.add(token)
    db_session.commit()

    res = client.delete(f"/api/users/{target.id}", headers=admin_headers)
    assert res.status_code == 204

    db_session.expire_all()
    refreshed = db_session.query(User).filter(User.id == target.id).first()
    assert refreshed is not None
    assert refreshed.is_active is False

    list_res = client.get("/api/users", headers=admin_headers, params={"size": 100})
    assert list_res.status_code == 200
    ids = [u["id"] for u in list_res.json()["items"]]
    assert target.id not in ids

    inactive_res = client.get(
        "/api/users",
        headers=admin_headers,
        params={"size": 100, "include_inactive": True},
    )
    assert inactive_res.status_code == 200
    inactive_items = {u["id"]: u for u in inactive_res.json()["items"]}
    assert inactive_items[target.id]["is_active"] is False


def test_delete_user_rejects_self_delete(client, make_user):
    user, headers = make_user(UserRole.TEAM_LEADER)

    res = client.delete(f"/api/users/{user.id}", headers=headers)

    assert res.status_code == 400
    assert res.json()["detail"] == "본인 계정은 삭제할 수 없습니다"
