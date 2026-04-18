"""인증 라우터 (JWT + 카카오 OAuth2)"""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import bcrypt
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from logging_config import log_event
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
    # 카카오 동의 캐시 (로그인 시 자동 진단 결과)
    kakao_scopes_ok: bool | None = None
    # 동의 부족 시 본인이 클릭하여 추가 동의받을 카카오 OAuth URL
    kakao_reauthorize_url: str | None = None

    model_config = {"from_attributes": True}

    @classmethod
    def from_user(cls, user: "User") -> "UserResponse":
        from config import settings as _settings
        reauthorize_url: str | None = None
        if user.kakao_id and user.kakao_scopes_ok is False:
            scope_param = "profile_nickname,friends,talk_message"
            reauthorize_url = (
                f"https://kauth.kakao.com/oauth/authorize"
                f"?client_id={_settings.kakao_rest_api_key}"
                f"&redirect_uri={_settings.kakao_redirect_uri}"
                f"&response_type=code"
                f"&scope={scope_param}"
            )
        return cls(
            id=user.id,
            name=user.name,
            email=user.email,
            role=user.role,
            phone=user.phone,
            is_active=user.is_active,
            must_change_password=user.must_change_password,
            kakao_linked=bool(user.kakao_id),
            kakao_scopes_ok=user.kakao_scopes_ok,
            kakao_reauthorize_url=reauthorize_url,
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
        log_event("warning", "auth_login_failed", email=form_data.username, reason="user_not_found")
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다")
    if not verify_password(form_data.password, user.password_hash):
        log_event("warning", "auth_login_failed", email=form_data.username, reason="bad_password")
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
    from services.kakao import (
        create_link_session,
        exchange_code,
        get_user_info,
        verify_oauth_state,
    )

    # CSRF 방어: state JWT 검증
    if not verify_oauth_state(state or ""):
        log_event("warning", "kakao_callback_invalid_state")
        raise HTTPException(status_code=400, detail="유효하지 않은 로그인 요청입니다")

    # 카카오 토큰 교환
    try:
        kakao_tokens = await exchange_code(code)
    except Exception:
        logger.exception("카카오 토큰 교환 실패")
        log_event("error", "kakao_token_exchange_failed")
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
        log_event("error", "kakao_user_info_failed")
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
        # 자동 동의 진단 + 캐시 갱신 (실패해도 로그인 흐름 영향 없음)
        from services.kakao import diagnose_and_cache_scopes
        await diagnose_and_cache_scopes(user, kakao_access, db)
        db.refresh(user)
        access_token = create_access_token({"sub": str(user.id), "role": user.role.value})
        return TokenResponse(access_token=access_token, must_change_password=False)

    # 카카오 ID 매칭 실패 → 이메일+비번으로 /link-account 호출 필요
    # (이름 기반 자동 매칭은 동명이인 위험으로 제거)
    # 카카오 토큰은 프론트(URL/JSON/스토리지)에 노출하지 않고 서버에 1회성 세션으로 보관.
    session_id = create_link_session(
        db,
        kakao_id=kakao_id,
        kakao_access_token=kakao_access,
        kakao_refresh_token=kakao_refresh,
        kakao_expires_in=kakao_expires_in,
    )
    return {
        "access_token": "",
        "token_type": "bearer",
        "must_change_password": False,
        "need_link": True,
        "kakao_name": kakao_name or "",
        "link_session_id": session_id,
    }


class LinkAccountRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)
    link_session_id: str = Field(min_length=1, max_length=64)


@router.post("/link-account")
async def link_account(body: LinkAccountRequest, db: Session = Depends(get_db)):
    """기존 계정에 카카오 연결 (1회성 세션 + 중복 연결 방지)

    세션 소모(consumed_at 마킹)는 모든 검증(인증·충돌)을 통과한 뒤에만
    수행한다. 잘못된 비밀번호 시도가 세션을 소모시키는 DoS를 방지하기 위해
    `lock_link_session`이 행 락만 잡고 마킹은 미루는 패턴.
    """
    from services.kakao import lock_link_session

    invalid_session = HTTPException(
        status_code=401,
        detail="연결 요청이 유효하지 않거나 만료되었습니다. 처음부터 다시 시도해주세요",
    )
    invalid_credentials = HTTPException(
        status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다"
    )

    session = lock_link_session(db, body.link_session_id)
    if session is None:
        log_event("warning", "link_account_invalid_session")
        raise invalid_session

    user = db.query(User).filter(User.email == body.email).first()
    if not user or not user.password_hash:
        log_event("warning", "link_account_bad_credentials", email=body.email, reason="user_not_found")
        raise invalid_credentials
    if not verify_password(body.password, user.password_hash):
        log_event("warning", "link_account_bad_credentials", email=body.email, reason="bad_password")
        raise invalid_credentials

    # 이미 다른 카카오 계정이 연결된 사용자
    if user.kakao_id and user.kakao_id != session.kakao_id:
        raise HTTPException(
            status_code=409,
            detail="이미 다른 카카오 계정이 연결되어 있습니다. 관리자에게 문의해주세요",
        )

    # 이 카카오 계정이 이미 다른 사용자에게 연결되어 있음
    # (DB unique 제약으로도 막히지만 사용자 친화적 메시지를 위해 사전 체크)
    other = (
        db.query(User)
        .filter(User.kakao_id == session.kakao_id, User.id != user.id)
        .first()
    )
    if other is not None:
        raise HTTPException(
            status_code=409,
            detail="이미 다른 사용자에게 연결된 카카오 계정입니다",
        )

    # 모든 검증 통과 — 사용자 업데이트 + 세션 소모를 한 트랜잭션에서 commit
    user.kakao_id = session.kakao_id
    user.kakao_access_token = session.kakao_access_token
    user.kakao_refresh_token = session.kakao_refresh_token or ""
    if session.kakao_expires_in:
        user.kakao_token_expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=int(session.kakao_expires_in)
        )
    session.consumed_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except IntegrityError:
        # 동시 요청에서 unique 제약(uq_users_kakao_id_not_null) 위반 시 친화적 메시지
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="이미 다른 사용자에게 연결된 카카오 계정입니다",
        )
    db.refresh(user)

    # 자동 동의 진단 + 캐시 갱신 (실패해도 link 흐름 영향 없음)
    from services.kakao import diagnose_and_cache_scopes
    await diagnose_and_cache_scopes(user, user.kakao_access_token, db)

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


# --- 비밀번호 셋업 (초대 링크 토큰 기반, 인증 불필요) ---

class PasswordSetupValidateResponse(BaseModel):
    valid: bool
    purpose: str
    email_masked: str  # "ho***@example.com" 형태로 일부만 노출


class PasswordSetupRequest(BaseModel):
    token: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=200)


def _mask_email(email: str) -> str:
    if "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        return f"{local[0]}*@{domain}"
    return f"{local[:2]}{'*' * (len(local) - 2)}@{domain}"


@router.get("/password-setup/validate", response_model=PasswordSetupValidateResponse)
def validate_password_setup(token: str, db: Session = Depends(get_db)):
    """초대 링크 토큰 사전 검증 (페이지 진입 시 호출).

    유효 시 200 + 마스킹된 이메일 반환, 실패 시 401.
    행 락은 잡지 않고 read-only 검증.
    """
    from services.password_setup import _hash_token
    from models.password_setup_token import PasswordSetupToken

    invalid = HTTPException(status_code=401, detail="유효하지 않거나 만료된 링크입니다")
    if not token:
        raise invalid

    row = (
        db.query(PasswordSetupToken)
        .filter(PasswordSetupToken.token_hash == _hash_token(token))
        .first()
    )
    if row is None or row.consumed_at is not None:
        log_event("warning", "password_setup_validate_failed", reason="invalid")
        raise invalid

    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        log_event("warning", "password_setup_validate_failed", reason="expired")
        raise invalid

    user = db.query(User).filter(User.id == row.user_id).first()
    if user is None or not user.is_active:
        raise invalid

    return PasswordSetupValidateResponse(
        valid=True,
        purpose=row.purpose.value,
        email_masked=_mask_email(user.email),
    )


@router.post("/password-setup")
def setup_password(body: PasswordSetupRequest, db: Session = Depends(get_db)):
    """초대 링크 토큰 + 새 비밀번호 → 비밀번호 셋업 + 토큰 1회 소비.

    토큰 락 -> 비번 검증 -> User 업데이트 + consumed_at 마킹을 한 트랜잭션에서 처리.
    """
    from services.password_setup import lookup_setup_token

    invalid = HTTPException(status_code=401, detail="유효하지 않거나 만료된 링크입니다")

    token = lookup_setup_token(db, body.token)
    if token is None:
        log_event("warning", "password_setup_invalid_token")
        raise invalid

    user = db.query(User).filter(User.id == token.user_id).first()
    if user is None or not user.is_active:
        raise invalid

    user.password_hash = get_password_hash(body.new_password)
    user.must_change_password = False
    token.consumed_at = datetime.now(timezone.utc)
    db.commit()

    log_event(
        "info", "password_setup_completed",
        user_id=user.id, purpose=token.purpose.value,
    )
    return {
        "message": "비밀번호가 설정되었습니다",
        "email": user.email,
        "kakao_linked": bool(user.kakao_id),
    }
