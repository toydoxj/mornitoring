"""FastAPI 메인 애플리케이션"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import auth, users, buildings, ledger, assignments, reviews, audit

app = FastAPI(
    title="건축구조안전 모니터링 시스템",
    description="통합관리대장 기반 모니터링 업무 자동화 API",
    version="0.1.0",
)

# CORS 설정 (프론트엔드 연동)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://ksea-m.vercel.app",
        "https://frontend-fsjh35-8127s-projects.vercel.app",
    ],
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


@app.get("/api/health")
def health_check():
    return {"status": "ok"}
