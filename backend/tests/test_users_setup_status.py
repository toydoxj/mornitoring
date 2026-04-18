"""사용자 목록 응답의 비밀번호 셋업 상태 회귀.

상태 4가지:
- setup_completed: must_change_password=false (가장 우선)
- pending: 미소비 토큰이 있고 expires_at > now
- expired: 미소비인데 expires_at <= now
- not_invited: 토큰 발급 이력 없음 + must_change_password=true
"""

from datetime import datetime, timedelta, timezone

from models.password_setup_token import (
    PasswordSetupToken,
    TokenDeliveryChannel,
    TokenPurpose,
)
from models.user import UserRole


def _make_token(
    db, *, user_id, expires_in_minutes=60 * 72, consumed=False
):
    now = datetime.now(timezone.utc)
    token = PasswordSetupToken(
        token_hash=f"hash_{user_id}_{expires_in_minutes}_{consumed}",
        user_id=user_id,
        purpose=TokenPurpose.INITIAL_SETUP,
        delivery_channel=TokenDeliveryChannel.MANUAL,
        expires_at=now + timedelta(minutes=expires_in_minutes),
        consumed_at=now if consumed else None,
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return token


def _list_users(client, headers, status=None):
    url = "/api/users"
    if status:
        url += f"?setup_status={status}"
    res = client.get(url, headers=headers)
    assert res.status_code == 200
    return res.json()


def test_not_invited_status(client, db_session, make_user):
    _, admin_headers = make_user(UserRole.TEAM_LEADER)
    target, _ = make_user(
        UserRole.REVIEWER,
        email="not-invited@example.com",
        must_change_password=True,
    )

    body = _list_users(client, admin_headers)
    by_id = {u["id"]: u for u in body["items"]}
    assert by_id[target.id]["setup_status"] == "not_invited"
    assert by_id[target.id]["last_invite_sent_at"] is None


def test_pending_status(client, db_session, make_user):
    _, admin_headers = make_user(UserRole.TEAM_LEADER)
    target, _ = make_user(
        UserRole.REVIEWER,
        email="pending@example.com",
        must_change_password=True,
    )
    _make_token(db_session, user_id=target.id, expires_in_minutes=60)  # 1시간 유효

    body = _list_users(client, admin_headers)
    by_id = {u["id"]: u for u in body["items"]}
    assert by_id[target.id]["setup_status"] == "pending"
    assert by_id[target.id]["last_invite_sent_at"]  # 시각 채워짐


def test_expired_status(client, db_session, make_user):
    _, admin_headers = make_user(UserRole.TEAM_LEADER)
    target, _ = make_user(
        UserRole.REVIEWER,
        email="expired@example.com",
        must_change_password=True,
    )
    _make_token(db_session, user_id=target.id, expires_in_minutes=-60)  # 1시간 전 만료

    body = _list_users(client, admin_headers)
    by_id = {u["id"]: u for u in body["items"]}
    assert by_id[target.id]["setup_status"] == "expired"


def test_setup_completed_status(client, db_session, make_user):
    _, admin_headers = make_user(UserRole.TEAM_LEADER)
    target, _ = make_user(
        UserRole.REVIEWER,
        email="completed@example.com",
        must_change_password=False,
    )

    body = _list_users(client, admin_headers)
    by_id = {u["id"]: u for u in body["items"]}
    assert by_id[target.id]["setup_status"] == "setup_completed"


def test_setup_completed_takes_priority_over_expired_token(
    client, db_session, make_user
):
    """must_change_password=false면 만료 토큰이 있어도 setup_completed."""
    _, admin_headers = make_user(UserRole.TEAM_LEADER)
    target, _ = make_user(
        UserRole.REVIEWER,
        email="priority@example.com",
        must_change_password=False,
    )
    _make_token(db_session, user_id=target.id, expires_in_minutes=-100)

    body = _list_users(client, admin_headers)
    by_id = {u["id"]: u for u in body["items"]}
    assert by_id[target.id]["setup_status"] == "setup_completed"


def test_setup_status_filter(client, db_session, make_user):
    _, admin_headers = make_user(UserRole.TEAM_LEADER)
    not_invited, _ = make_user(UserRole.REVIEWER, email="ni@example.com", must_change_password=True)
    completed, _ = make_user(UserRole.REVIEWER, email="cm@example.com", must_change_password=False)

    body = _list_users(client, admin_headers, status="not_invited")
    ids = [u["id"] for u in body["items"]]
    assert not_invited.id in ids
    assert completed.id not in ids
