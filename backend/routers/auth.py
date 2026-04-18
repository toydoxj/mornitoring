"""인증 라우터 (JWT + 카카오 OAuth2)"""

import logging
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
logger = logging.getLogger(__name__)


# --- Pydantic 스키마 ---

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool = False


class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    role: UserRole
    phone: str | None = None
    is_active: bool
    must_change_password: bool = False
    kakao_linked: bool = False

    model_config = {"from_attributes": True}

    @classmethod
    def from_user(cls, user: "User") -> "UserResponse":
        return cls(
            id=user.id,
            name=user.name,
            email=user.email,
            role=user.role,
            phone=user.phone,
            is_active=user.is_active,
            must_change_password=user.must_change_password,
            kakao_linked=bool(user.kakao_id),
        )


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


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
    return TokenResponse(
        access_token=access_token,
        must_change_password=user.must_change_password,
    )


@router.get("/kakao/login")
def kakao_login():
    """카카오 로그인 URL 반환"""
    from services.kakao import get_authorize_url
    return {"url": get_authorize_url()}


@router.get("/kakao/callback")
async def kakao_callback(
    code: str,
    state: str | None = None,
    db: Session = Depends(get_db),
):
    """카카오 인가 코드 → 토큰 교환 → 사용자 조회/생성 → JWT 발급"""
    from services.kakao import exchange_code, get_user_info, verify_oauth_state

    # CSRF 방어: state JWT 검증
    if not verify_oauth_state(state or ""):
        raise HTTPException(status_code=400, detail="유효하지 않은 로그인 요청입니다")

    # 카카오 토큰 교환
    try:
        kakao_tokens = await exchange_code(code)
    except Exception:
        logger.exception("카카오 토큰 교환 실패")
        raise HTTPException(status_code=400, detail="카카오 로그인 처리 중 오류가 발생했습니다")

    kakao_access = kakao_tokens.get("access_token")
    if not kakao_access:
        raise HTTPException(status_code=400, detail=f"카카오 액세스 토큰 없음: {kakao_tokens}")
    kakao_refresh = kakao_tokens.get("refresh_token", "")
    kakao_expires_in = kakao_tokens.get("expires_in", 21599)
    kakao_token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=kakao_expires_in)

    # 카카오 사용자 정보
    try:
        kakao_user = await get_user_info(kakao_access)
    except Exception:
        logger.exception("카카오 사용자 정보 조회 실패")
        raise HTTPException(status_code=400, detail="카카오 로그인 처리 중 오류가 발생했습니다")
    kakao_id = str(kakao_user["id"])
    # 닉네임: properties.nickname 또는 kakao_account.profile.nickname
    kakao_name = (
        kakao_user.get("properties", {}).get("nickname", "")
        or kakao_user.get("kakao_account", {}).get("profile", {}).get("nickname", "")
    )

    # DB에서 사용자 조회 (kakao_id 기준)
    user = db.query(User).filter(User.kakao_id == kakao_id).first()
    if user:
        user.kakao_access_token = kakao_access
        user.kakao_refresh_token = kakao_refresh
        user.kakao_token_expires_at = kakao_token_expires_at
        db.commit()
        db.refresh(user)
        access_token = create_access_token({"sub": str(user.id), "role": user.role.value})
        return TokenResponse(access_token=access_token, must_change_password=False)

    # 카카오 ID 매칭 실패 → 이메일+비번으로 /link-account 호출 필요
    # (이름 기반 자동 매칭은 동명이인 위험으로 제거)
    return {
        "access_token": "",
        "token_type": "bearer",
        "must_change_password": False,
        "need_link": True,
        "kakao_id": kakao_id,
        "kakao_name": kakao_name or "",
        "kakao_access_token": kakao_access,
        "kakao_refresh_token": kakao_refresh,
        "kakao_expires_in": kakao_expires_in,
    }


class LinkAccountRequest(BaseModel):
    email: str
    password: str
    kakao_id: str
    kakao_access_token: str
    kakao_refresh_token: str
    kakao_expires_in: int | None = None


@router.post("/link-account")
def link_account(body: LinkAccountRequest, db: Session = Depends(get_db)):
    """기존 계정에 카카오 연결"""
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not user.password_hash:
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다")

    user.kakao_id = body.kakao_id
    user.kakao_access_token = body.kakao_access_token
    user.kakao_refresh_token = body.kakao_refresh_token
    if body.kakao_expires_in:
        user.kakao_token_expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=body.kakao_expires_in
        )
    db.commit()
    db.refresh(user)

    access_token = create_access_token({"sub": str(user.id), "role": user.role.value})
    return TokenResponse(access_token=access_token, must_change_password=False)


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """현재 로그인 사용자 정보"""
    return current_user


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """비밀번호 변경"""
    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="현재 비밀번호가 올바르지 않습니다")

    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="새 비밀번호는 8자 이상이어야 합니다")

    current_user.password_hash = get_password_hash(body.new_password)
    current_user.must_change_password = False
    db.commit()
    return {"message": "비밀번호가 변경되었습니다"}
