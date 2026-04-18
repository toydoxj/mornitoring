"""데이터베이스 연결 설정"""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import settings

engine = create_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,      # 유휴 끊긴 커넥션 자동 감지·교체 (Supabase pooler 대응)
    pool_recycle=300,        # 5분마다 커넥션 순환
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI 의존성 주입용 DB 세션 생성기"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
