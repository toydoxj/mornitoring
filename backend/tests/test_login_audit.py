"""로그인 감사 로그 + 로그인 이력 조회 API 회귀 테스트.

- POST /api/auth/login 성공/실패가 audit_logs에 기록되는지
- GET /api/audit-logs/logins 권한/필터/검색이 정상 동작하는지
- IP 추출 헬퍼가 trusted_proxy_hops 설정에 따라 안전하게 동작하는지
"""

import pytest

from config import settings
from models.audit_log import AuditLog
from models.user import UserRole


def _login(client, email: str, password: str, *, headers: dict | None = None):
    return client.post(
        "/api/auth/login",
        data={"username": email, "password": password},
        headers={**(headers or {}), "content-type": "application/x-www-form-urlencoded"},
    )


@pytest.fixture
def trust_one_proxy(monkeypatch):
    """프록시 1단(LB)을 신뢰하는 운영 모드를 시뮬레이션."""
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    yield


def test_login_success_creates_audit_log_trusts_xff_when_configured(
    client, db_session, make_user, trust_one_proxy
):
    user, _ = make_user(UserRole.SECRETARY, password="testpass1")

    res = _login(
        client, user.email, "testpass1",
        headers={"x-forwarded-for": "203.0.113.7, 10.0.0.1"},
    )
    assert res.status_code == 200, res.text

    logs = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "login")
        .all()
    )
    assert len(logs) == 1
    log = logs[0]
    assert log.user_id == user.id
    assert log.target_type == "user"
    assert (log.after_data or {}).get("provider") == "password"
    # hops=1이면 우측 1개(10.0.0.1)는 LB로 보고 그 안쪽 마지막 값이 원 클라이언트
    assert log.ip_address == "203.0.113.7"


def test_login_ignores_xff_when_no_trusted_proxy(
    client, db_session, make_user
):
    """기본(hops=0)에서는 외부 주입 X-Forwarded-For를 무시하고 client.host를 쓴다."""
    user, _ = make_user(UserRole.SECRETARY, password="testpass1")

    res = _login(
        client, user.email, "testpass1",
        headers={"x-forwarded-for": "1.2.3.4"},
    )
    assert res.status_code == 200, res.text

    log = db_session.query(AuditLog).filter(AuditLog.action == "login").one()
    assert log.ip_address != "1.2.3.4"


def test_login_failed_user_not_found(client, db_session):
    res = _login(client, "missing@example.com", "whatever")
    assert res.status_code == 401

    logs = db_session.query(AuditLog).filter(AuditLog.action == "login_failed").all()
    assert len(logs) == 1
    after = logs[0].after_data or {}
    assert logs[0].user_id is None
    assert after.get("reason") == "user_not_found"
    assert after.get("email") == "missing@example.com"


def test_login_failed_bad_password(client, db_session, make_user):
    user, _ = make_user(UserRole.SECRETARY, password="testpass1")

    res = _login(client, user.email, "WRONG-PASSWORD")
    assert res.status_code == 401

    logs = db_session.query(AuditLog).filter(AuditLog.action == "login_failed").all()
    assert len(logs) == 1
    log = logs[0]
    # 실패 로그는 user_id를 None으로 두지만 target_id는 추적용으로 채운다.
    assert log.user_id is None
    assert log.target_id == user.id
    assert (log.after_data or {}).get("reason") == "bad_password"


def test_login_logs_api_requires_admin(client, make_reviewer):
    _, _, headers = make_reviewer()
    res = client.get("/api/audit-logs/logins", headers=headers)
    assert res.status_code == 403


def test_login_logs_api_returns_join_and_filters(client, db_session, make_user):
    admin, admin_headers = make_user(UserRole.CHIEF_SECRETARY, password="testpass1", name="총괄")
    target, _ = make_user(UserRole.SECRETARY, password="testpass1", name="홍길동", email="hong@example.com")

    # 홍길동 1회 성공
    assert _login(client, target.email, "testpass1").status_code == 200
    # 홍길동 1회 실패
    assert _login(client, target.email, "WRONG").status_code == 401
    # 존재하지 않는 계정 1회 실패
    assert _login(client, "nope@example.com", "whatever").status_code == 401

    # 전체
    res = client.get("/api/audit-logs/logins", headers=admin_headers, params={"status": "all"})
    assert res.status_code == 200
    body = res.json()
    actions = {item["action"] for item in body["items"]}
    assert {"login", "login_failed"} <= actions

    # 성공만
    res = client.get("/api/audit-logs/logins", headers=admin_headers, params={"status": "success"})
    assert res.status_code == 200
    body = res.json()
    assert all(item["action"] == "login" for item in body["items"])
    # join으로 사용자 이름이 채워져야 한다.
    success_for_target = [i for i in body["items"] if i["user_id"] == target.id]
    assert success_for_target and success_for_target[0]["user_name"] == "홍길동"

    # 이름 검색
    res = client.get("/api/audit-logs/logins", headers=admin_headers, params={"q": "홍길동"})
    assert res.status_code == 200
    body = res.json()
    assert body["total"] >= 1
    assert all((i["user_name"] == "홍길동") for i in body["items"])

    # 조회 자체가 read_login_logs 감사로그로 남는지 확인 (위 3회 GET 호출)
    read_logs = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "read_login_logs")
        .all()
    )
    assert len(read_logs) == 3
