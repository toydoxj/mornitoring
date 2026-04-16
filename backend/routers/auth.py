"""인증 라우터 (JWT + 카카오 OAuth2)"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import bcrypt
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.user import User, UserRole

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# --- Pydantic 스키마 ---

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    role: UserRole
    phone: str | None = None
    is_active: bool

    model_config = {"from_attributes": True}


# --- 유틸 함수 ---

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_access_token_expire_minutes
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="인증 정보가 유효하지 않습니다",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        sub = payload.get("sub")
        if sub is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.id == int(sub)).first()
    if user is None or not user.is_active:
        raise credentials_exception
    return user


def require_roles(*roles: UserRole):
    """역할 기반 접근 제어 의존성"""
    async def role_checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="접근 권한이 없습니다",
            )
        return current_user
    return role_checker


# --- 엔드포인트 ---

@router.post("/login", response_model=TokenResponse)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """이메일/비밀번호 로그인"""
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not user.password_hash:
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다")
    if not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다")

    access_token = create_access_token({"sub": str(user.id), "role": user.role.value})
    return TokenResponse(access_token=access_token)


@router.get("/kakao/login")
def kakao_login():
    """카카오 로그인 URL 반환"""
    from services.kakao import get_authorize_url
    return {"url": get_authorize_url()}


@router.get("/kakao/callback")
async def kakao_callback(code: str, db: Session = Depends(get_db)):
    """카카오 인가 코드 → 토큰 교환 → 사용자 조회/생성 → JWT 발급"""
    from services.kakao import exchange_code, get_user_info

    # 카카오 토큰 교환
    kakao_tokens = await exchange_code(code)
    kakao_access = kakao_tokens["access_token"]
    kakao_refresh = kakao_tokens.get("refresh_token", "")

    # 카카오 사용자 정보
    kakao_user = await get_user_info(kakao_access)
    kakao_id = str(kakao_user["id"])
    kakao_name = kakao_user.get("properties", {}).get("nickname", "")

    # DB에서 사용자 조회 (kakao_id 기준)
    user = db.query(User).filter(User.kakao_id == kakao_id).first()
    if not user:
        # 이름으로 매칭 시도 (기존 사용자 연결)
        user = db.query(User).filter(User.name == kakao_name).first()
        if user:
            user.kakao_id = kakao_id
        else:
            # 신규 사용자 (기본 검토위원)
            user = User(
                name=kakao_name,
                email=f"kakao_{kakao_id}@kakao.com",
                role=UserRole.REVIEWER,
                kakao_id=kakao_id,
            )
            db.add(user)

    # 카카오 토큰 저장
    user.kakao_access_token = kakao_access
    user.kakao_refresh_token = kakao_refresh
    db.commit()
    db.refresh(user)

    # JWT 발급
    access_token = create_access_token({"sub": str(user.id), "role": user.role.value})
    return TokenResponse(access_token=access_token)


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """현재 로그인 사용자 정보"""
    return current_user
