"""테스트 공용 fixture.

운영 PostgreSQL 대신 SQLite in-memory를 사용한다. 테스트마다 모든 테이블을
새로 만들고 격리된 세션을 제공한다. 카카오 같은 외부 호출을 하는 케이스는
이번 라운드 범위가 아니므로 mock fixture는 추가하지 않는다.
"""

import os

# config.Settings는 모듈 import 시점에 평가되므로 모든 import보다 먼저 환경변수 주입.
# 셸/CI에 이미 같은 키가 설정돼 있어도 테스트 환경을 강제하기 위해 명시 대입.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = "test_jwt_secret_key_with_minimum_32_chars"
os.environ["AWS_REGION"] = "ap-northeast-2"
os.environ["S3_BUCKET_NAME"] = "test-bucket"
os.environ["KAKAO_REDIRECT_URI"] = "http://localhost/callback"
os.environ["CORS_ORIGINS"] = '["http://localhost:3000"]'
os.environ["FRONTEND_BASE_URL"] = "http://localhost:3000"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# 환경변수 설정 후 import
import models  # noqa: F401  Base.metadata에 모든 모델 등록
from database import Base, get_db
from main import app
from models.building import Building
from models.reviewer import Reviewer
from models.user import User, UserRole
from routers.auth import create_access_token, get_password_hash


@pytest.fixture(scope="function")
def engine():
    """테스트 함수마다 새 SQLite in-memory 엔진."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture(scope="function")
def db_session(engine):
    """테스트 1회용 세션."""
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def client(engine, db_session):
    """`get_db` 의존성을 테스트 세션으로 override한 TestClient."""

    def _override_get_db():
        # FastAPI 핸들러는 자체 세션 lifecycle을 관리하므로 별도 세션을 만들어 yield.
        SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        s = SessionLocal()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _create_user(
    db,
    *,
    name: str,
    email: str,
    role: UserRole,
    password: str = "testpass1",
    must_change_password: bool = False,
    **extra,
) -> User:
    """User 생성 fixture. **extra로 kakao_uuid 등 추가 필드 직접 주입 가능."""
    user = User(
        name=name,
        email=email,
        role=role,
        password_hash=get_password_hash(password),
        must_change_password=must_change_password,
        is_active=True,
        **extra,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _auth_header(user: User) -> dict:
    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def make_user(db_session):
    """역할별 사용자 생성 fixture. 호출 시 (User, headers) 반환."""

    counter = {"i": 0}

    def _make(role: UserRole, **kwargs) -> tuple[User, dict]:
        counter["i"] += 1
        i = counter["i"]
        defaults = {
            "name": kwargs.pop("name", f"테스트{role.value}{i}"),
            "email": kwargs.pop("email", f"user{i}_{role.value}@example.com"),
            "role": role,
        }
        user = _create_user(db_session, **defaults, **kwargs)
        return user, _auth_header(user)

    return _make


@pytest.fixture
def make_reviewer(db_session):
    """REVIEWER 역할 User + 연결된 Reviewer row 생성. (User, Reviewer, headers) 반환."""

    counter = {"i": 0}

    def _make(group_no: str | None = None) -> tuple[User, Reviewer, dict]:
        counter["i"] += 1
        i = counter["i"]
        user = _create_user(
            db_session,
            name=f"검토위원{i}",
            email=f"reviewer{i}@example.com",
            role=UserRole.REVIEWER,
        )
        reviewer = Reviewer(user_id=user.id, group_no=group_no)
        db_session.add(reviewer)
        db_session.commit()
        db_session.refresh(reviewer)
        return user, reviewer, _auth_header(user)

    return _make


@pytest.fixture
def make_building(db_session):
    """건축물 생성. reviewer_id로 담당 위원 지정 가능."""

    counter = {"i": 0}

    def _make(*, reviewer_id: int | None = None, mgmt_no: str | None = None) -> Building:
        counter["i"] += 1
        i = counter["i"]
        b = Building(
            mgmt_no=mgmt_no or f"TEST-{i:04d}",
            reviewer_id=reviewer_id,
            building_name=f"테스트건물{i}",
        )
        db_session.add(b)
        db_session.commit()
        db_session.refresh(b)
        return b

    return _make
