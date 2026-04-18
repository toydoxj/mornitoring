"""D — 카카오 초대 링크 비번 셋업 회귀 테스트.

흐름: send-invite → validate → password-setup
검증:
- 발송: 카카오 매칭 사용자 vs 미매칭 사용자 분기, 토큰 hash 저장
- validate: 만료/소비 토큰 거부, 평문 토큰 hash 매칭
- setup: 1회성 소비, 비번 변경 + must_change_password=False
- 재발송 시 기존 토큰 무효화
"""

import hashlib
from datetime import datetime, timedelta, timezone

from models.password_setup_token import (
    PasswordSetupToken,
    TokenDeliveryChannel,
    TokenPurpose,
)
from models.user import UserRole
from routers.auth import verify_password


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ===== send-invite =====

def test_admin_sends_invite_to_kakao_unmatched_user_returns_manual(
    client, db_session, make_user
):
    """카카오 매칭 안 된 사용자: delivery=manual, setup_url 응답."""
    _, admin_headers = make_user(UserRole.TEAM_LEADER)
    target, _ = make_user(UserRole.REVIEWER)
    # target.kakao_uuid는 None

    res = client.post(
        f"/api/users/{target.id}/send-invite", headers=admin_headers
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["delivery"] == "manual"
    assert payload["purpose"] == "initial_setup"
    assert "setup_url" in payload and "token=" in payload["setup_url"]

    # DB에 token_hash 저장 (평문 아님)
    token_in_url = payload["setup_url"].split("token=")[1]
    rows = db_session.query(PasswordSetupToken).filter(
        PasswordSetupToken.user_id == target.id
    ).all()
    assert len(rows) == 1
    assert rows[0].token_hash == _hash(token_in_url)
    assert rows[0].consumed_at is None
    assert rows[0].delivery_channel == TokenDeliveryChannel.MANUAL


def test_reviewer_cannot_send_invite(client, make_reviewer, make_user):
    _, _, headers_r = make_reviewer()
    target, _ = make_user(UserRole.REVIEWER)
    res = client.post(f"/api/users/{target.id}/send-invite", headers=headers_r)
    assert res.status_code == 403


def test_send_invite_revokes_previous_token(client, db_session, make_user):
    """재발송 시 이전 미소비 토큰 모두 consumed_at 마킹 → 비활성화."""
    _, admin_headers = make_user(UserRole.TEAM_LEADER)
    target, _ = make_user(UserRole.REVIEWER)

    # 첫 발송
    res1 = client.post(f"/api/users/{target.id}/send-invite", headers=admin_headers)
    token1 = res1.json()["setup_url"].split("token=")[1]

    # 재발송
    res2 = client.post(f"/api/users/{target.id}/send-invite", headers=admin_headers)
    assert res2.status_code == 200
    token2 = res2.json()["setup_url"].split("token=")[1]
    assert token1 != token2

    # 이전 토큰은 소비 마킹됨
    db_session.expire_all()
    old = db_session.query(PasswordSetupToken).filter(
        PasswordSetupToken.token_hash == _hash(token1)
    ).first()
    assert old is not None and old.consumed_at is not None

    # 첫 토큰으로 validate → 401
    res_validate = client.get(f"/api/auth/password-setup/validate?token={token1}")
    assert res_validate.status_code == 401


# ===== validate =====

def test_validate_returns_masked_email(client, make_user):
    _, admin_headers = make_user(UserRole.TEAM_LEADER)
    target, _ = make_user(UserRole.REVIEWER, email="hongkildong@example.com")

    res = client.post(f"/api/users/{target.id}/send-invite", headers=admin_headers)
    token = res.json()["setup_url"].split("token=")[1]

    res_v = client.get(f"/api/auth/password-setup/validate?token={token}")
    assert res_v.status_code == 200
    body = res_v.json()
    assert body["valid"] is True
    assert body["purpose"] == "initial_setup"
    # ho***@example.com
    assert body["email_masked"].startswith("ho")
    assert body["email_masked"].endswith("@example.com")
    assert "*" in body["email_masked"]


def test_validate_rejects_unknown_token(client):
    res = client.get("/api/auth/password-setup/validate?token=fake_unknown_token")
    assert res.status_code == 401


def test_validate_rejects_expired_token(client, db_session, make_user):
    """expires_at 과거 토큰은 401."""
    target, _ = make_user(UserRole.REVIEWER)
    raw_token = "expiredtoken_for_test_xyz"
    row = PasswordSetupToken(
        token_hash=_hash(raw_token),
        user_id=target.id,
        purpose=TokenPurpose.INITIAL_SETUP,
        delivery_channel=TokenDeliveryChannel.MANUAL,
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db_session.add(row)
    db_session.commit()

    res = client.get(f"/api/auth/password-setup/validate?token={raw_token}")
    assert res.status_code == 401


# ===== password-setup =====

def test_password_setup_completes_and_consumes_token(
    client, db_session, make_user
):
    _, admin_headers = make_user(UserRole.TEAM_LEADER)
    target, _ = make_user(UserRole.REVIEWER, email="setup-test@example.com")

    res = client.post(f"/api/users/{target.id}/send-invite", headers=admin_headers)
    token = res.json()["setup_url"].split("token=")[1]

    res_setup = client.post(
        "/api/auth/password-setup",
        json={"token": token, "new_password": "NewSecurePass123"},
    )
    assert res_setup.status_code == 200

    # 토큰 소비됨
    db_session.expire_all()
    row = db_session.query(PasswordSetupToken).filter(
        PasswordSetupToken.token_hash == _hash(token)
    ).first()
    assert row.consumed_at is not None

    # User 비번 변경 + must_change_password=False
    from models.user import User as UserModel
    user_after = db_session.query(UserModel).filter(UserModel.id == target.id).first()
    assert verify_password("NewSecurePass123", user_after.password_hash)
    assert user_after.must_change_password is False

    # 같은 토큰 재사용 → 401
    res_again = client.post(
        "/api/auth/password-setup",
        json={"token": token, "new_password": "AnotherPass456"},
    )
    assert res_again.status_code == 401


def test_password_setup_rejects_short_password(
    client, make_user
):
    _, admin_headers = make_user(UserRole.TEAM_LEADER)
    target, _ = make_user(UserRole.REVIEWER)
    res = client.post(f"/api/users/{target.id}/send-invite", headers=admin_headers)
    token = res.json()["setup_url"].split("token=")[1]

    res_setup = client.post(
        "/api/auth/password-setup",
        json={"token": token, "new_password": "short"},  # 8자 미만
    )
    # Pydantic min_length=8 검증 → 422
    assert res_setup.status_code == 422


def test_password_setup_with_invalid_token_returns_401(client):
    res = client.post(
        "/api/auth/password-setup",
        json={"token": "totally_invalid_token_xyz", "new_password": "ValidPass123"},
    )
    assert res.status_code == 401
