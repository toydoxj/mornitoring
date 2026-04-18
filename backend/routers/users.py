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
from models.password_setup_token import TokenPurpose
from models.reviewer import Reviewer
from models.user import User, UserRole
from routers.auth import get_current_user, get_password_hash, require_roles
from services.invite import InviteResult, send_invites

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
    # 비밀번호 셋업 상태 (목록 조회 시에만 채워짐)
    # setup_completed | pending | expired | not_invited
    setup_status: str | None = None
    last_invite_sent_at: str | None = None  # 마지막 토큰 발급 시각 (재발송 판단용)

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
    # auto_send_invite=True로 호출된 경우만 채워짐
    invite_summary: "BulkInviteSummary | None" = None
    invite_results: list["BulkInviteResultItem"] = []


class ResetPasswordResponse(BaseModel):
    message: str
    initial_password: str


class SendInviteResponse(BaseModel):
    """단건 초대 발송 결과."""
    delivery: str  # "kakao" | "manual"
    setup_url: str | None  # manual/error에만 노출 (kakao 성공 시 None)
    expires_at: str
    purpose: str
    error: str | None = None


class BulkSendInviteRequest(BaseModel):
    user_ids: list[int]
    purpose: TokenPurpose = TokenPurpose.INITIAL_SETUP


class BulkInviteResultItem(BaseModel):
    user_id: int
    name: str
    delivery: str  # "kakao" | "manual"
    expires_at: str
    setup_url: str | None  # manual/error에만
    error: str | None


class BulkInviteSummary(BaseModel):
    total: int
    kakao_sent: int
    manual: int
    failed: int
    sender_error: str | None  # 카카오 발신자 토큰 미준비 등 공통 사유


class BulkSendInviteResponse(BaseModel):
    summary: BulkInviteSummary
    results: list[BulkInviteResultItem]


class UserListResponse(BaseModel):
    items: list[UserResponse]
    total: int


# --- 엔드포인트 ---

@router.get("", response_model=UserListResponse)
def list_users(
    role: UserRole | None = None,
    setup_status: str | None = Query(
        None, description="필터: setup_completed/pending/expired/not_invited"
    ),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """사용자 목록 조회 (팀장/총괄간사만). 비밀번호 셋업 상태 포함."""
    from datetime import datetime, timezone
    from models.password_setup_token import PasswordSetupToken
    from services.password_setup import _ensure_aware_utc

    query = db.query(User)
    if role:
        query = query.filter(User.role == role)

    # 페이지네이션 전에 setup_status 필터를 적용하려면 모든 사용자에 대해
    # 상태를 계산해야 한다(60명 규모라 부담 없음). 필터 미지정 시는 페이지만 잘라낸다.
    if setup_status:
        candidates = query.all()
    else:
        total_pre = query.count()
        candidates = query.offset((page - 1) * size).limit(size).all()

    user_ids = [u.id for u in candidates]
    latest_tokens: dict[int, PasswordSetupToken] = {}
    if user_ids:
        token_rows = (
            db.query(PasswordSetupToken)
            .filter(PasswordSetupToken.user_id.in_(user_ids))
            .order_by(
                PasswordSetupToken.user_id,
                PasswordSetupToken.created_at.desc(),
            )
            .all()
        )
        for t in token_rows:
            if t.user_id not in latest_tokens:
                latest_tokens[t.user_id] = t

    now = datetime.now(timezone.utc)

    def _compute_status(user: User) -> tuple[str, str | None]:
        """(setup_status, last_invite_sent_at_iso). 우선순위: 완료 > 토큰 상태."""
        if not user.must_change_password:
            tok = latest_tokens.get(user.id)
            return "setup_completed", tok.created_at.isoformat() if tok else None
        tok = latest_tokens.get(user.id)
        if tok is None:
            return "not_invited", None
        if tok.consumed_at is not None:
            # 토큰 소비됐는데 must_change_password=true인 비정상 상태.
            # 완료로 가리지 말고 재발송 필요로 표시한다 (운영자 액션 트리거).
            return "not_invited", tok.created_at.isoformat()
        if _ensure_aware_utc(tok.expires_at) <= now:
            return "expired", tok.created_at.isoformat()
        return "pending", tok.created_at.isoformat()

    items_all = [
        (u, *_compute_status(u))
        for u in candidates
    ]

    if setup_status:
        items_all = [t for t in items_all if t[1] == setup_status]
        total = len(items_all)
        items_all = items_all[(page - 1) * size : (page - 1) * size + size]
    else:
        total = total_pre

    items = [
        UserResponse(
            id=u.id, name=u.name, email=u.email, role=u.role,
            phone=u.phone, is_active=u.is_active,
            kakao_linked=bool(u.kakao_id),
            kakao_matched=bool(u.kakao_uuid),
            kakao_uuid=u.kakao_uuid,
            setup_status=status,
            last_invite_sent_at=last_sent,
        )
        for (u, status, last_sent) in items_all
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
    auto_send_invite: bool = Query(False, description="등록 후 카카오/수동 초대 자동 발송"),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """사용자 일괄 등록 (엑셀). 각 신규 계정의 일회용 초기 비밀번호를 응답에 포함.

    엑셀 형식: A열=이름, B열=이메일, C열=역할(팀장/총괄간사/간사/검토위원), D열=전화번호(선택)
    auto_send_invite=true인 경우 신규 계정에 한해 send_invites를 호출하고
    invite_summary/invite_results를 응답에 포함한다.
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
        created_users: list[User] = []

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
            created_users.append(user)

        db.commit()
        # commit 후 user.id 확보
        for u in created_users:
            db.refresh(u)
        wb.close()

        invite_summary = None
        invite_results: list[BulkInviteResultItem] = []
        if auto_send_invite and created_users:
            summary, results = await send_invites(
                db,
                sender=current_user,
                targets=created_users,
                purpose=TokenPurpose.INITIAL_SETUP,
            )
            invite_summary = BulkInviteSummary(
                total=summary.total,
                kakao_sent=summary.kakao_sent,
                manual=summary.manual,
                failed=summary.failed,
                sender_error=summary.sender_error,
            )
            invite_results = [
                BulkInviteResultItem(
                    user_id=r.user_id,
                    name=r.name,
                    delivery=r.delivery,
                    expires_at=r.expires_at,
                    setup_url=r.setup_url,
                    error=r.error,
                )
                for r in results
            ]

        return BulkImportResponse(
            created=created,
            skipped=skipped,
            errors=errors,
            accounts=accounts,
            invite_summary=invite_summary,
            invite_results=invite_results,
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
    """단건 초대 발송. 내부적으로 bulk 흐름과 같은 services/invite.send_invites 호출."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="비활성 사용자입니다")

    _, results = await send_invites(
        db, sender=current_user, targets=[user], purpose=purpose
    )
    r = results[0]
    return SendInviteResponse(
        delivery=r.delivery,
        setup_url=r.setup_url,
        expires_at=r.expires_at,
        purpose=purpose.value,
        error=r.error,
    )


@router.post("/bulk-send-invite", response_model=BulkSendInviteResponse)
async def bulk_send_invite(
    body: BulkSendInviteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """다중 사용자 일괄 초대 발송.

    - 비활성/존재하지 않는 사용자 ID는 결과에서 제외 (에러 카운트로 들어감)
    - 카카오 매칭자는 카카오 메시지 발송, 미매칭은 manual setup_url 반환
    - 카카오 발신자 토큰 미준비 시 모두 manual fallback
    - best-effort: 일부 실패가 전체 롤백을 일으키지 않음
    """
    if not body.user_ids:
        raise HTTPException(status_code=400, detail="user_ids가 비어 있습니다")
    if len(body.user_ids) > 200:
        raise HTTPException(status_code=400, detail="한 번에 최대 200명까지 발송 가능합니다")

    users = (
        db.query(User)
        .filter(User.id.in_(body.user_ids), User.is_active.is_(True))
        .all()
    )
    user_by_id = {u.id: u for u in users}
    targets = [user_by_id[uid] for uid in body.user_ids if uid in user_by_id]
    skipped = [uid for uid in body.user_ids if uid not in user_by_id]

    summary, results = await send_invites(
        db, sender=current_user, targets=targets, purpose=body.purpose
    )

    # 누락된 user_id는 실패 결과로 추가
    items = [
        BulkInviteResultItem(
            user_id=r.user_id,
            name=r.name,
            delivery=r.delivery,
            expires_at=r.expires_at,
            setup_url=r.setup_url,
            error=r.error,
        )
        for r in results
    ]
    for uid in skipped:
        items.append(
            BulkInviteResultItem(
                user_id=uid,
                name=f"#{uid}",
                delivery="manual",
                expires_at="",
                setup_url=None,
                error="사용자를 찾을 수 없거나 비활성 상태입니다",
            )
        )

    return BulkSendInviteResponse(
        summary=BulkInviteSummary(
            total=summary.total + len(skipped),
            kakao_sent=summary.kakao_sent,
            manual=summary.manual,
            failed=summary.failed + len(skipped),
            sender_error=summary.sender_error,
        ),
        results=items,
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
