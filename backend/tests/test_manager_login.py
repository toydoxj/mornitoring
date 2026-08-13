"""관리원 전용 이메일/비밀번호 로그인 회귀.

- 관리원만 통과, 다른 역할은 자격 증명이 맞아도 403
- 비활성 관리원 계정 거부
- 자격 증명 오류는 계정 존재 여부를 흘리지 않는 동일 401 문구
- 성공/실패 모두 감사 로그에 provider=password_manager 로 남는다
- 기존 /api/auth/login 동작은 그대로
"""

import pytest

from models.audit_log import AuditLog
from models.user import UserRole
from routers.auth import get_password_hash

LOGIN_URL = "/api/auth/manager/login"
PASSWORD = "testpass1"


def _form(email: str, password: str = PASSWORD) -> dict:
    return {"username": email, "password": password}


def _login_audits(db_session, action: str):
    return (
        db_session.query(AuditLog)
        .filter(AuditLog.action == action)
        .order_by(AuditLog.id)
        .all()
    )


def test_manager_logs_in(client, db_session, make_user):
    manager, _ = make_user(UserRole.MANAGER)

    res = client.post(LOGIN_URL, data=_form(manager.email))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["access_token"]
    assert body["must_change_password"] is False

    # 발급된 토큰으로 실제 조회가 되는지까지 확인
    me = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["role"] == "manager"

    audits = _login_audits(db_session, "login")
    assert audits[-1].user_id == manager.id
    assert audits[-1].after_data["provider"] == "password_manager"


def test_manager_login_returns_must_change_password(client, make_user):
    manager, _ = make_user(UserRole.MANAGER, must_change_password=True)

    res = client.post(LOGIN_URL, data=_form(manager.email))
    assert res.status_code == 200
    assert res.json()["must_change_password"] is True


@pytest.mark.parametrize("role", [
    UserRole.TEAM_LEADER,
    UserRole.CHIEF_SECRETARY,
    UserRole.SECRETARY,
    UserRole.REVIEWER,
])
def test_non_manager_rejected(client, db_session, make_user, role):
    """비밀번호가 맞아도 관리원이 아니면 403."""
    user, _ = make_user(role)

    res = client.post(LOGIN_URL, data=_form(user.email))
    assert res.status_code == 403
    assert "관리원 전용" in res.json()["detail"]

    failed = _login_audits(db_session, "login_failed")
    assert failed[-1].after_data["reason"] == "role_not_allowed"
    assert failed[-1].after_data["role"] == role.value
    assert failed[-1].after_data["provider"] == "password_manager"


def test_inactive_manager_rejected(client, db_session, make_user):
    manager, _ = make_user(UserRole.MANAGER)
    manager.is_active = False
    db_session.commit()

    res = client.post(LOGIN_URL, data=_form(manager.email))
    assert res.status_code == 403
    assert "비활성화" in res.json()["detail"]

    failed = _login_audits(db_session, "login_failed")
    assert failed[-1].after_data["reason"] == "inactive"


def test_wrong_password_rejected(client, db_session, make_user):
    manager, _ = make_user(UserRole.MANAGER)

    res = client.post(LOGIN_URL, data=_form(manager.email, "wrong-password"))
    assert res.status_code == 401
    assert res.json()["detail"] == "이메일 또는 비밀번호가 올바르지 않습니다"

    failed = _login_audits(db_session, "login_failed")
    assert failed[-1].after_data["reason"] == "bad_password"
    assert failed[-1].after_data["provider"] == "password_manager"


def test_unknown_email_gives_same_message(client, db_session, make_user):
    """없는 계정과 틀린 비밀번호의 응답이 구분되지 않아야 한다."""
    manager, _ = make_user(UserRole.MANAGER)

    unknown = client.post(LOGIN_URL, data=_form("nobody@example.com"))
    wrong = client.post(LOGIN_URL, data=_form(manager.email, "wrong-password"))

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]

    failed = _login_audits(db_session, "login_failed")
    assert failed[0].after_data["reason"] == "user_not_found"


def test_password_only_account_without_hash(client, db_session, make_user):
    """비밀번호가 없는 계정(카카오 전용)은 401."""
    manager, _ = make_user(UserRole.MANAGER)
    manager.password_hash = None
    db_session.commit()

    res = client.post(LOGIN_URL, data=_form(manager.email))
    assert res.status_code == 401


def test_default_login_still_allows_all_roles(client, db_session, make_user):
    """기존 로그인 엔드포인트는 역할 제한 없이 그대로 동작한다."""
    reviewer, _ = make_user(UserRole.REVIEWER)

    res = client.post("/api/auth/login", data=_form(reviewer.email))
    assert res.status_code == 200
    assert res.json()["access_token"]

    audits = _login_audits(db_session, "login")
    assert audits[-1].after_data["provider"] == "password"


def test_default_login_allows_inactive_user(client, db_session, make_user):
    """기존 엔드포인트의 활성 검사 동작은 바꾸지 않는다 (회귀 방지).

    비활성 계정은 로그인 자체는 통과하고 이후 /me 에서 걸러진다.
    """
    user, _ = make_user(UserRole.REVIEWER)
    user.is_active = False
    db_session.commit()

    res = client.post("/api/auth/login", data=_form(user.email))
    assert res.status_code == 200

    me = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {res.json()['access_token']}"},
    )
    assert me.status_code == 401


def test_password_hash_helper_matches_fixture():
    """fixture 가 쓰는 해시 방식과 로그인 검증이 맞물리는지 확인."""
    from routers.auth import verify_password

    assert verify_password(PASSWORD, get_password_hash(PASSWORD))
