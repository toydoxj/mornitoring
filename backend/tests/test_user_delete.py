"""사용자 삭제(비활성화) 회귀 테스트."""

from datetime import datetime, timedelta, timezone

from models.password_setup_token import (
    PasswordSetupToken,
    TokenDeliveryChannel,
    TokenPurpose,
)
from models.reviewer import Reviewer
from models.user import User, UserRole
from routers.auth import verify_password


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


def test_create_user_reactivates_soft_deleted_email(
    client, db_session, make_user
):
    """삭제된 사용자를 같은 이메일로 등록하면 기존 행을 재활성화한다."""
    _, admin_headers = make_user(UserRole.TEAM_LEADER)
    target, _ = make_user(
        UserRole.REVIEWER,
        name="이공우",
        email="egw-reactivate@example.com",
        kakao_id="old-kakao-id",
        kakao_uuid="old-kakao-uuid",
        kakao_access_token="old-access",
        kakao_refresh_token="old-refresh",
        kakao_scopes_ok=True,
    )
    reviewer = Reviewer(user_id=target.id, group_no=2)
    db_session.add(reviewer)
    token = PasswordSetupToken(
        token_hash="reactivate_user_token_hash",
        user_id=target.id,
        purpose=TokenPurpose.INITIAL_SETUP,
        delivery_channel=TokenDeliveryChannel.MANUAL,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db_session.add(token)
    db_session.commit()

    delete_res = client.delete(f"/api/users/{target.id}", headers=admin_headers)
    assert delete_res.status_code == 204

    res = client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "name": "이공우",
            "email": "EGW-Reactivate@example.com",
            "role": "reviewer",
            "phone": "010-2222-3333",
            "group_no": 6,
        },
    )

    assert res.status_code == 201
    body = res.json()
    assert body["id"] == target.id
    assert body["email"] == "egw-reactivate@example.com"
    assert body["initial_password"]

    db_session.expire_all()
    restored = db_session.query(User).filter(User.id == target.id).one()
    assert restored.is_active is True
    assert restored.phone == "010-2222-3333"
    assert restored.must_change_password is True
    assert verify_password(body["initial_password"], restored.password_hash)
    assert restored.kakao_id is None
    assert restored.kakao_uuid is None
    assert restored.kakao_access_token is None
    assert restored.kakao_refresh_token is None
    assert restored.kakao_scopes_ok is None

    restored_reviewer = (
        db_session.query(Reviewer).filter(Reviewer.user_id == target.id).one()
    )
    assert restored_reviewer.group_no == 6

    restored_token = (
        db_session.query(PasswordSetupToken)
        .filter(PasswordSetupToken.id == token.id)
        .one()
    )
    assert restored_token.consumed_at is not None
