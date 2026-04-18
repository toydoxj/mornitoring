"""N6 — 운영 가시성 로깅 회귀.

- log_event 출력 형식(`event=<name> key=value ...`) 검증
- 미들웨어가 X-Request-ID 헤더를 응답에 추가하는지
- 로그인 실패 시 `auth_login_failed` 이벤트가 warning 레벨로 기록되는지
"""

import logging

from logging_config import EVENT_LOGGER_NAME, log_event


def test_log_event_format(caplog):
    caplog.set_level(logging.INFO, logger=EVENT_LOGGER_NAME)
    log_event("info", "sample", user_id=42, reason="ok")
    msgs = [r.message for r in caplog.records if r.name == EVENT_LOGGER_NAME]
    assert any(m == "event=sample user_id=42 reason=ok" for m in msgs)


def test_log_event_quotes_value_with_space(caplog):
    caplog.set_level(logging.WARNING, logger=EVENT_LOGGER_NAME)
    log_event("warning", "sample", note="has space")
    msgs = [r.message for r in caplog.records if r.name == EVENT_LOGGER_NAME]
    assert any(m == 'event=sample note="has space"' for m in msgs)


def test_health_check_returns_request_id_header(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert "X-Request-ID" in res.headers
    assert len(res.headers["X-Request-ID"]) == 12


def test_login_failure_emits_warning_event(client, caplog):
    caplog.set_level(logging.WARNING, logger=EVENT_LOGGER_NAME)
    res = client.post(
        "/api/auth/login",
        data={"username": "nonexistent@example.com", "password": "wrongpw"},
    )
    assert res.status_code == 401
    msgs = [r.message for r in caplog.records if r.name == EVENT_LOGGER_NAME]
    assert any("event=auth_login_failed" in m and "reason=user_not_found" in m for m in msgs)


def test_request_middleware_logs_4xx_as_warning(client, caplog):
    caplog.set_level(logging.WARNING, logger=EVENT_LOGGER_NAME)
    # 인증 없이 보호 엔드포인트 호출 → 401
    res = client.get("/api/audit-logs")
    assert res.status_code == 401
    msgs = [r.message for r in caplog.records if r.name == EVENT_LOGGER_NAME]
    assert any("event=request" in m and "status=401" in m for m in msgs)
