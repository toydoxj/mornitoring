"""FastAPI 메인 애플리케이션"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from database import SessionLocal
from routers import auth, users, buildings, ledger, assignments, reviews, audit, distribution, notifications, kakao, announcements, discussions

logger = logging.getLogger(__name__)

# 만료/소비된 카카오 연결 세션 청소 주기 (30분)
LINK_SESSION_PURGE_INTERVAL_SECONDS = 1800


async def _purge_expired_link_sessions_loop() -> None:
    from services.kakao import purge_expired_link_sessions

    while True:
        try:
            await asyncio.sleep(LINK_SESSION_PURGE_INTERVAL_SECONDS)
            db = SessionLocal()
            try:
                deleted = purge_expired_link_sessions(db)
                if deleted:
                    logger.info("kakao_link_sessions 정리: %d행 삭제", deleted)
            finally:
                db.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("kakao_link_sessions 정리 실패")


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
