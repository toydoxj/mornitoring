"""FastAPI 메인 애플리케이션"""

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from config import settings
from database import SessionLocal
from logging_config import log_event, setup_logging
from routers import auth, users, buildings, ledger, assignments, reviews, audit, distribution, notifications, kakao, announcements, discussions

setup_logging()
logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """요청 단위 요약 로깅 + X-Request-ID 부여.

    바디는 절대 남기지 않는다. 4xx는 warning, 5xx는 error로 자동 분류.
    Render 등 클라우드 로그에서 `event=request status=5` 같이 grep 가능.
    """

    async def dispatch(self, request: Request, call_next):
        request_id = uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = int((time.perf_counter() - start) * 1000)
            log_event(
                "error",
                "request_unhandled_exception",
                method=request.method,
                path=request.url.path,
                duration_ms=duration_ms,
                request_id=request_id,
            )
            raise
        duration_ms = int((time.perf_counter() - start) * 1000)
        status = response.status_code
        response.headers["X-Request-ID"] = request_id
        # health check 200은 노이즈라 로깅 생략 (헤더는 항상 부여)
        if request.url.path == "/api/health" and 200 <= status < 300:
            return response
        level = "error" if status >= 500 else ("warning" if status >= 400 else "info")
        log_event(
            level,
            "request",
            method=request.method,
            path=request.url.path,
            status=status,
            duration_ms=duration_ms,
            request_id=request_id,
        )
        return response

# 만료/소비된 카카오 연결 세션 청소 주기 (30분)
LINK_SESSION_PURGE_INTERVAL_SECONDS = 1800


async def _purge_expired_link_sessions_loop() -> None:
    from services.kakao import purge_expired_link_sessions
    from services.password_setup import purge_expired_setup_tokens

    while True:
        try:
            await asyncio.sleep(LINK_SESSION_PURGE_INTERVAL_SECONDS)
            db = SessionLocal()
            try:
                deleted = purge_expired_link_sessions(db)
                if deleted:
                    log_event("info", "kakao_link_session_purge", deleted=deleted)
                deleted_tokens = purge_expired_setup_tokens(db)
                if deleted_tokens:
                    log_event("info", "password_setup_token_purge", deleted=deleted_tokens)
            finally:
                db.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("주기 정리 작업 실패")
            log_event("error", "purge_loop_failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    purge_task = asyncio.create_task(_purge_expired_link_sessions_loop())
    try:
        yield
    finally:
        purge_task.cancel()
        try:
            await purge_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="건축구조안전 모니터링 시스템",
    description="통합관리대장 기반 모니터링 업무 자동화 API",
    version="0.1.0",
    lifespan=lifespan,
)

# 요청 로깅 (CORS보다 먼저 add → 실제 처리 시 가장 바깥에서 감쌈)
app.add_middleware(RequestLoggingMiddleware)

# CORS 설정 (프론트엔드 연동) — 허용 origin은 .env의 CORS_ORIGINS로 관리
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(auth.router, prefix="/api/auth", tags=["인증"])
app.include_router(users.router, prefix="/api/users", tags=["사용자"])
app.include_router(buildings.router, prefix="/api/buildings", tags=["건축물"])
app.include_router(ledger.router, prefix="/api/ledger", tags=["관리대장"])
app.include_router(assignments.router, prefix="/api/assignments", tags=["배정"])
app.include_router(reviews.router, prefix="/api/reviews", tags=["검토서"])
app.include_router(audit.router, prefix="/api/audit-logs", tags=["감사로그"])
app.include_router(distribution.router, prefix="/api/distribution", tags=["도서배포"])
app.include_router(notifications.router, prefix="/api/notifications", tags=["알림"])
app.include_router(kakao.router, prefix="/api/kakao", tags=["카카오"])
app.include_router(announcements.router, prefix="/api/announcements", tags=["공지사항"])
app.include_router(discussions.router, prefix="/api/discussions", tags=["토론방"])


@app.get("/api/health")
def health_check():
    return {"status": "ok"}
