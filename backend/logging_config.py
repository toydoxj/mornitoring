"""중앙 로깅 설정 + 이벤트 로깅 헬퍼.

Render 등 클라우드 로그 대시보드에서 grep하기 쉬운 평문 + key=value 형식.
운영 직전 최소 가시성 단계라 JSON 구조 로깅까지는 가지 않는다.
나중에 Sentry 도입 시 logger 핸들러에 추가하면 된다.
"""

import logging
from typing import Any

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 모든 도메인 이벤트는 이 이름의 로거로 출력 → Render 등에서 `app:` 필터로 추출
EVENT_LOGGER_NAME = "app"


def setup_logging(level: int = logging.INFO) -> None:
    """uvicorn 기본 로거 옆에 앱 로거를 세팅. 중복 호출 안전."""
    root = logging.getLogger()
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        logging.basicConfig(level=level, format=LOG_FORMAT, datefmt=DATE_FORMAT)
    else:
        root.setLevel(level)
    logging.getLogger(EVENT_LOGGER_NAME).setLevel(level)


def _format_value(v: Any) -> str:
    """공백/특수문자 포함 시 따옴표 감싸기. None은 '-'."""
    if v is None:
        return "-"
    s = str(v)
    if " " in s or "=" in s or '"' in s:
        s = s.replace('"', '\\"')
        return f'"{s}"'
    return s


def log_event(level: str, event: str, **fields: Any) -> None:
    """`event=<name> key=value ...` 형식으로 출력.

    level: "info" | "warning" | "error" | "debug"
    event: 식별자(snake_case) — auth_login_failed, kakao_callback_error 등
    fields: 부가 정보 — user_id, email, reason 등
    """
    pairs = " ".join(f"{k}={_format_value(v)}" for k, v in fields.items())
    msg = f"event={event}" + (f" {pairs}" if pairs else "")
    logger = logging.getLogger(EVENT_LOGGER_NAME)
    log_fn = getattr(logger, level.lower(), logger.info)
    log_fn(msg)
