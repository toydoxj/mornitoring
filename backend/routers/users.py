"""사용자 관리 라우터"""

import secrets
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from openpyxl import load_workbook
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from logging_config import log_event
from models.building import Building
from models.password_setup_token import TokenDeliveryChannel, TokenPurpose
from models.reviewer import Reviewer
from models.user import User, UserRole
from routers.auth import get_current_user, get_password_hash, require_roles
from services.password_setup import issue_setup_token

router = APIRouter()


# 혼동 문자(l/i, 0/o, 1) 제외한 알파벳·숫자
_PW_LETTERS = "abcdefghjkmnpqrstuvwxyz"  # 23자 (i, l 제외)
_PW_DIGITS = "23456789"                   # 8자 (0, 1 제외)


def _generate_initial_password() -> str:
    """일회용 초기 비밀번호 (영문 소문자 4 + 숫자 4 = 8자).

    전달·입력 편의 위해 혼동 문자(i/l, 0/o, 1) 제외.
    엔트로피 약 2^30으로 must_change_password=True 전제 하에 충분.
    """
    letters = "".join(secrets.choice(_PW_LETTERS) for _ in range(4))
    digits = "".join(secrets.choice(_PW_DIGITS) for _ in range(4))
    return letters + digits


ROLE_MAP = {
    "팀장": UserRole.TEAM_LEADER,
    "총괄간사": UserRole.CHIEF_SECRETARY,
    "간사": UserRole.SECRETARY,
    "검토위원": UserRole.REVIEWER,
    "team_leader": UserRole.TEAM_LEADER,
    "chief_secretary": UserRole.CHIEF_SECRETARY,
    "secretary": UserRole.SECRETARY,
    "reviewer": UserRole.REVIEWER,
}


# --- Pydantic 스키마 ---

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    role: UserRole
    phone: str | None = None


class UserUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None


class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    role: UserRole
    phone: str | None = None
    is_active: bool
    # 카카오 상태
    kakao_linked: bool = False        # 카카오 로그인 완료(kakao_id 존재)
    kakao_matched: bool = False       # 친구 매칭 완료(kakao_uuid 존재)
    kakao_uuid: str | None = None

    model_config = {"from_attributes": True}


class UserCreateResponse(UserResponse):
    """사용자 신규 생성 응답 — 일회용 초기 비밀번호 포함."""
    initial_password: str


class BulkImportAccount(BaseModel):
    email: str
    name: str
    initial_password: str


class BulkImportResponse(BaseModel):
    created: int
    skipped: int
    errors: list[str] = []
    accounts: list[BulkImportAccount] = []


class ResetPasswordResponse(BaseModel):
    message: str
    initial_password: str


class SendInviteResponse(BaseModel):
    """초대 발송 결과.

    delivery=kakao: 카카오 메시지 발송 성공. setup_url은 디버그/관리자 확인용으로 함께 반환.
    delivery=manual: 카카오 매칭 안 됨 또는 발송 실패. 관리자가 setup_url을 다른 채널로 전달.
    """
    delivery: str  # "kakao" | "manual"
    setup_url: str
    expires_at: str
    purpose: str
    error: str | None = None  # 카카오 발송 실패 시 사유


class UserListResponse(BaseModel):
    items: list[UserResponse]
    total: int


# --- 엔드포인트 ---

@router.get("", response_model=UserListResponse)
def list_users(
    role: UserRole | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """사용자 목록 조회 (팀장/총괄간사만)"""
    query = db.query(User)
    if role:
        query = query.filter(User.role == role)

    total = query.count()
    users = query.offset((page - 1) * size).limit(size).all()
    items = [
        UserResponse(
            id=u.id, name=u.name, email=u.email, role=u.role,
            phone=u.phone, is_active=u.is_active,
            kakao_linked=bool(u.kakao_id),
            kakao_matched=bool(u.kakao_uuid),
            kakao_uuid=u.kakao_uuid,
        )
        for u in users
    ]
    return UserListResponse(items=items, total=total)


@router.post("", response_model=UserCreateResponse, status_code=201)
def create_user(
    body: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """사용자 등록 (팀장/총괄간사). 일회용 초기 비밀번호를 응답으로 반환."""
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=409, detail="이미 등록된 이메일입니다")

    initial_password = _generate_initial_password()
    user = User(
        name=body.name,
        email=body.email,
        role=body.role,
        phone=body.phone,
        password_hash=get_password_hash(initial_password),
        must_change_password=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserCreateResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.role,
        phone=user.phone,
        is_active=user.is_active,
        kakao_linked=bool(user.kakao_id),
        kakao_matched=bool(user.kakao_uuid),
        kakao_uuid=user.kakao_uuid,
        initial_password=initial_password,
    )


@router.post("/import-excel", response_model=BulkImportResponse)
async def import_users_excel(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """사용자 일괄 등록 (엑셀). 각 신규 계정의 일회용 초기 비밀번호를 응답에 포함.

    엑셀 형식: A열=이름, B열=이메일, C열=역할(팀장/총괄간사/간사/검토위원), D열=전화번호(선택)
    """
    if not file.filename or not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="엑셀 파일(.xlsx)만 업로드 가능합니다")

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        wb = load_workbook(str(tmp_path), data_only=True, read_only=True)
        ws = wb.active

        created = 0
        skipped = 0
        errors: list[str] = []
        accounts: list[BulkImportAccount] = []

        for row_idx, row in enumerate(ws.iter_rows(min_row=2), start=2):
            name = str(row[0].value).strip() if row[0].value else None
            email = str(row[1].value).strip() if len(row) > 1 and row[1].value else None
            role_str = str(row[2].value).strip() if len(row) > 2 and row[2].value else None
            phone = str(row[3].value).strip() if len(row) > 3 and row[3].value else None

            if not name or not email:
                continue

            # 역할 매핑
            role = ROLE_MAP.get(role_str, UserRole.REVIEWER) if role_str else UserRole.REVIEWER

            # 중복 체크
            if db.query(User).filter(User.email == email).first():
                skipped += 1
                continue

            initial_password = _generate_initial_password()
            user = User(
                name=name,
                email=email,
                role=role,
                phone=phone,
                password_hash=get_password_hash(initial_password),
                must_change_password=True,
            )
            db.add(user)
            accounts.append(BulkImportAccount(
                email=email, name=name, initial_password=initial_password,
            ))
            created += 1

        db.commit()
        wb.close()
        return BulkImportResponse(
            created=created, skipped=skipped, errors=errors, accounts=accounts,
        )

    finally:
        tmp_path.unlink(missing_ok=True)


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """사용자 상세 조회 — 본인 또는 관리자(팀장/총괄간사)만.

    REVIEWER/SECRETARY가 임의의 user_id로 다른 사용자 정보(이메일/전화번호 등)를
    조회하지 못하도록 방어. 존재 자체를 노출하지 않기 위해 권한 미달 시 404.
    """
    is_admin = current_user.role in (UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    is_self = current_user.id == user_id
    if not (is_admin or is_self):
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")
    return user


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    body: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """사용자 정보 수정 (팀장/총괄간사만)"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(user, key, value)

    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """사용자 삭제 (팀장/총괄간사)"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

    # reviewer 연결 해제
    reviewer = db.query(Reviewer).filter(Reviewer.user_id == user.id).first()
    if reviewer:
        db.query(Building).filter(Building.reviewer_id == reviewer.id).update(
            {"reviewer_id": None}
        )
        db.delete(reviewer)

    db.delete(user)
    db.commit()


@router.post("/{user_id}/send-invite", response_model=SendInviteResponse)
async def send_invite(
    user_id: int,
    purpose: TokenPurpose = TokenPurpose.INITIAL_SETUP,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """비밀번호 셋업 초대 발송 (팀장/총괄간사).

    - 카카오 매칭(`kakao_uuid`)된 사용자에게는 발신 관리자의 카카오 토큰으로 초대 메시지 발송
    - 미매칭 사용자에게는 setup_url만 응답 → 관리자가 별도 채널로 전달
    - 기존 미소비 토큰은 자동 무효화 (재발송 시 이전 링크 비활성)
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="비활성 사용자입니다")

    # 카카오 매칭 여부에 따라 channel 결정 (먼저 정해 토큰에 기록)
    will_send_kakao = bool(user.kakao_uuid) and bool(current_user.kakao_uuid is not None or current_user.kakao_access_token)
    channel = TokenDeliveryChannel.KAKAO if will_send_kakao else TokenDeliveryChannel.MANUAL

    raw_token, token = issue_setup_token(
        db,
        user_id=user.id,
        purpose=purpose,
        delivery_channel=channel,
        created_by=current_user.id,
    )
    setup_url = f"{settings.frontend_base_url.rstrip('/')}/setup-password?token={raw_token}"

    delivery = "manual"
    error: str | None = None

    if user.kakao_uuid:
        # 발송 시도 — 실패 시 manual로 fallback
        try:
            from services.kakao import ensure_valid_token, send_message_to_friends

            access_token = await ensure_valid_token(current_user, db)
            title = "건축구조안전 모니터링 — 비밀번호 설정"
            description = (
                f"{user.name}님, 시스템 접속을 위해 비밀번호를 설정해주세요.\n"
                f"링크는 72시간 후 만료됩니다."
            )
            result = await send_message_to_friends(
                access_token=access_token,
                receiver_uuids=[user.kakao_uuid],
                title=title,
                description=description,
                link_url=setup_url,
            )
            if "error" in result:
                error = str(result.get("detail", "발송 실패"))
                log_event(
                    "error", "send_invite_kakao_failed",
                    user_id=user.id, reason=error,
                )
            else:
                delivery = "kakao"
                log_event(
                    "info", "send_invite_kakao_sent",
                    user_id=user.id, purpose=purpose.value,
                )
        except Exception as exc:
            error = f"카카오 발송 오류: {exc}"
            log_event(
                "error", "send_invite_kakao_exception",
                user_id=user.id, reason=str(exc),
            )

    if delivery != "kakao":
        # 토큰의 실제 delivery_channel 반영 (manual로 변경)
        token.delivery_channel = TokenDeliveryChannel.MANUAL
        db.commit()

    return SendInviteResponse(
        delivery=delivery,
        setup_url=setup_url,
        expires_at=token.expires_at.isoformat(),
        purpose=purpose.value,
        error=error,
    )


@router.post("/{user_id}/reset-password", response_model=ResetPasswordResponse)
def reset_password(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """비밀번호 초기화 (팀장/총괄간사). 일회용 초기 비밀번호를 응답으로 반환."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

    initial_password = _generate_initial_password()
    user.password_hash = get_password_hash(initial_password)
    user.must_change_password = True
    db.commit()
    return ResetPasswordResponse(
        message=f"{user.name}의 비밀번호가 초기화되었습니다",
        initial_password=initial_password,
    )
