"""카카오 친구 목록 조회 + 검토위원 매칭 라우터"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models.user import User, UserRole
from routers.auth import require_roles
from services.kakao import (
    REQUIRED_KAKAO_SCOPES,
    ensure_valid_token,
    extract_kakao_login_uuid,
    get_friends,
    get_kakao_identity_status,
    get_kakao_token_status,
    get_reauthorize_url,
    get_user_info,
    get_user_scopes,
)

router = APIRouter()


REQUIRED_SCOPES = list(REQUIRED_KAKAO_SCOPES)


class ScopeItem(BaseModel):
    id: str
    display_name: str | None = None
    type: str | None = None
    using: bool = False
    agreed: bool = False
    revocable: bool = False


class ScopeStatusResponse(BaseModel):
    kakao_linked: bool
    all_agreed: bool
    missing_scopes: list[str]
    scopes: list[ScopeItem]
    reauthorize_url: str | None = None


@router.get("/me/scopes", response_model=ScopeStatusResponse)
async def my_kakao_scopes(
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY, UserRole.SECRETARY)
    ),
):
    """현재 로그인 사용자의 카카오 동의 항목 상태 조회.

    - 필수 scope(profile_nickname, friends, talk_message) 중 미동의 항목 식별
    - 미동의 시 추가 동의받기 URL 제공
    """
    if not current_user.kakao_access_token:
        return ScopeStatusResponse(
            kakao_linked=False,
            all_agreed=False,
            missing_scopes=REQUIRED_SCOPES,
            scopes=[],
            reauthorize_url=None,
        )

    try:
        access_token = await ensure_valid_token(current_user, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        data = await get_user_scopes(access_token)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"동의 항목 조회 실패: {exc}")

    scopes_raw = data.get("scopes", []) or []
    scopes = [ScopeItem(**s) for s in scopes_raw]
    agreed_ids = {s.id for s in scopes if s.agreed}
    missing = [sid for sid in REQUIRED_SCOPES if sid not in agreed_ids]

    reauthorize_url: str | None = None
    if missing:
        reauthorize_url = get_reauthorize_url(missing)

    return ScopeStatusResponse(
        kakao_linked=True,
        all_agreed=len(missing) == 0,
        missing_scopes=missing,
        scopes=scopes,
        reauthorize_url=reauthorize_url,
    )


class FriendItem(BaseModel):
    uuid: str
    profile_nickname: str | None = None
    profile_thumbnail_image: str | None = None
    favorite: bool = False
    matched_user_id: int | None = None
    matched_user_name: str | None = None


class FriendsResponse(BaseModel):
    items: list[FriendItem]
    total: int


@router.get("/friends", response_model=FriendsResponse)
async def list_kakao_friends(
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """현재 로그인한 사용자의 카카오 친구 목록 조회.

    - 친구 목록 + 이미 매칭된 검토위원 정보를 함께 반환
    """
    try:
        access_token = await ensure_valid_token(current_user, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    friends = await get_friends(access_token)

    # 이미 매칭된 사용자(uuid → user) 인덱스
    uuids = [f.get("uuid") for f in friends if f.get("uuid")]
    matched_users: dict[str, User] = {}
    if uuids:
        users = db.query(User).filter(User.kakao_uuid.in_(uuids)).all()
        matched_users = {u.kakao_uuid: u for u in users if u.kakao_uuid}

    items: list[FriendItem] = []
    for f in friends:
        uuid = f.get("uuid")
        if not uuid:
            continue
        matched = matched_users.get(uuid)
        items.append(FriendItem(
            uuid=uuid,
            profile_nickname=f.get("profile_nickname"),
            profile_thumbnail_image=f.get("profile_thumbnail_image"),
            favorite=f.get("favorite", False),
            matched_user_id=matched.id if matched else None,
            matched_user_name=matched.name if matched else None,
        ))

    return FriendsResponse(items=items, total=len(items))


class MatchRequest(BaseModel):
    user_id: int
    kakao_uuid: str


@router.post("/match")
async def match_friend(
    body: MatchRequest,
    db: Session = Depends(get_db),
    _: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """검토위원(또는 임의 사용자)과 카카오 UUID 매칭"""
    user = db.query(User).filter(User.id == body.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")
    if user.kakao_login_uuid and user.kakao_login_uuid != body.kakao_uuid:
        raise HTTPException(
            status_code=409,
            detail="카카오 로그인 계정과 선택한 친구가 다릅니다",
        )

    # 동일 UUID가 다른 사용자에 이미 매칭되어 있다면 해제
    existing = (
        db.query(User)
        .filter(User.kakao_uuid == body.kakao_uuid, User.id != body.user_id)
        .first()
    )
    if existing:
        existing.kakao_uuid = None

    user.kakao_uuid = body.kakao_uuid
    db.commit()
    return {"message": "매칭되었습니다", "user_id": user.id, "kakao_uuid": body.kakao_uuid}


@router.delete("/match/{user_id}")
async def unmatch_friend(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """매칭 해제"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")
    user.kakao_uuid = None
    db.commit()
    return {"message": "매칭이 해제되었습니다"}


@router.delete("/oauth/{user_id}")
async def unlink_kakao_oauth(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """카카오 로그인 연동 해제.

    친구 매칭(kakao_uuid)은 별도 관리 항목이라 유지한다. 잘못 매칭된 경우
    `/match/{user_id}` 해제 버튼으로 함께 정리한다.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

    user.kakao_id = None
    user.kakao_login_uuid = None
    user.kakao_access_token = None
    user.kakao_refresh_token = None
    user.kakao_token_expires_at = None
    user.kakao_scopes_ok = None
    user.kakao_scopes_checked_at = None
    db.commit()
    return {"message": "카카오 로그인 연동이 해제되었습니다", "user_id": user.id}


class UserMatchStatus(BaseModel):
    user_id: int
    name: str
    email: str
    role: UserRole
    group_no: int | None = None
    kakao_oauth_linked: bool  # 본 서비스에 카카오 로그인 완료 (kakao_id 존재)
    kakao_linked: bool  # 내 친구 목록에서 매칭 완료 (kakao_uuid 존재) — 기존 필드 유지
    kakao_uuid: str | None = None
    kakao_login_uuid: str | None = None
    kakao_identity_status: str
    kakao_token_status: str | None = None
    kakao_token_expires_at: str | None = None
    kakao_scopes_status: str | None = None


class BulkTokenRefreshSummary(BaseModel):
    total: int
    refreshed: int
    skipped: int
    failed: int


class BulkTokenRefreshResult(BaseModel):
    user_id: int
    name: str
    status_before: str
    status_after: str
    kakao_token_expires_at: str | None = None
    refreshed: bool
    error: str | None = None


class BulkTokenRefreshResponse(BaseModel):
    summary: BulkTokenRefreshSummary
    results: list[BulkTokenRefreshResult]


class BulkLoginUuidSyncSummary(BaseModel):
    total: int
    synced: int
    matched: int
    mismatched: int
    failed: int


class BulkLoginUuidSyncResult(BaseModel):
    user_id: int
    name: str
    status_before: str
    status_after: str
    synced: bool
    error: str | None = None


class BulkLoginUuidSyncResponse(BaseModel):
    summary: BulkLoginUuidSyncSummary
    results: list[BulkLoginUuidSyncResult]


@router.get("/reviewers", response_model=list[UserMatchStatus])
async def list_users_match_status(
    db: Session = Depends(get_db),
    _: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY, UserRole.SECRETARY)
    ),
):
    """전체 활성 사용자의 카카오 매칭 상태 목록 (역할 무관)"""
    users = (
        db.query(User)
        .filter(User.is_active.is_(True))
        .order_by(User.role, User.name)
        .all()
    )
    def _scopes_status(u: User) -> str:
        if u.kakao_scopes_ok is True:
            return "ok"
        if u.kakao_scopes_ok is False:
            return "insufficient"
        return "unknown"

    items: list[UserMatchStatus] = []
    for u in users:
        kakao_token_status, kakao_token_expires_at = get_kakao_token_status(u)
        items.append(UserMatchStatus(
            user_id=u.id,
            name=u.name,
            email=u.email,
            role=u.role,
            group_no=u.group_no,
            kakao_oauth_linked=bool(u.kakao_id),
            kakao_linked=bool(u.kakao_uuid),
            kakao_uuid=u.kakao_uuid,
            kakao_login_uuid=u.kakao_login_uuid,
            kakao_identity_status=get_kakao_identity_status(u),
            kakao_token_status=kakao_token_status,
            kakao_token_expires_at=kakao_token_expires_at,
            kakao_scopes_status=_scopes_status(u),
        ))
    return items


def _token_refresh_error_message(exc: Exception) -> str:
    """외부 응답의 민감 정보를 줄이고 운영자가 볼 수 있는 오류만 정리한다."""
    response = getattr(exc, "response", None)
    if response is not None:
        status_code = getattr(response, "status_code", None)
        try:
            data = response.json()
        except Exception:
            data = {}
        message = (
            data.get("error_description")
            or data.get("error")
            or data.get("msg")
            or data.get("code")
            or str(exc)
        )
        return f"HTTP {status_code}: {message}"[:200]
    return (str(exc) or exc.__class__.__name__)[:200]


@router.post("/tokens/refresh", response_model=BulkTokenRefreshResponse)
async def refresh_kakao_tokens(
    db: Session = Depends(get_db),
    _: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """활성 사용자 중 갱신 필요한 카카오 access token을 일괄 갱신한다.

    사용자 목록 API는 외부 카카오 API를 호출하지 않고 상태만 표시한다.
    이 엔드포인트는 운영자가 명시적으로 요청한 경우에만 refresh token으로
    access token을 갱신해 카카오 토큰 발급 요청 수를 통제한다.
    """
    users = (
        db.query(User)
        .filter(User.is_active.is_(True), User.kakao_id.is_not(None))
        .order_by(User.role, User.name)
        .all()
    )

    results: list[BulkTokenRefreshResult] = []
    refreshed_count = 0
    skipped_count = 0
    failed_count = 0

    for user in users:
        before_status, before_expires_at = get_kakao_token_status(user)
        if before_status != "refresh_needed":
            skipped_count += 1
            results.append(BulkTokenRefreshResult(
                user_id=user.id,
                name=user.name,
                status_before=before_status,
                status_after=before_status,
                kakao_token_expires_at=before_expires_at,
                refreshed=False,
            ))
            continue

        try:
            await ensure_valid_token(user, db)
        except Exception as exc:
            db.rollback()
            failed_count += 1
            results.append(BulkTokenRefreshResult(
                user_id=user.id,
                name=user.name,
                status_before=before_status,
                status_after="invalid",
                kakao_token_expires_at=before_expires_at,
                refreshed=False,
                error=_token_refresh_error_message(exc),
            ))
            continue

        after_status, after_expires_at = get_kakao_token_status(user)
        refreshed = after_status == "valid"
        if refreshed:
            refreshed_count += 1
        else:
            failed_count += 1

        results.append(BulkTokenRefreshResult(
            user_id=user.id,
            name=user.name,
            status_before=before_status,
            status_after=after_status,
            kakao_token_expires_at=after_expires_at,
            refreshed=refreshed,
            error=None if refreshed else "갱신 후에도 토큰이 유효 상태가 아닙니다",
        ))

    return BulkTokenRefreshResponse(
        summary=BulkTokenRefreshSummary(
            total=len(users),
            refreshed=refreshed_count,
            skipped=skipped_count,
            failed=failed_count,
        ),
        results=results,
    )


@router.post("/login-uuids/sync", response_model=BulkLoginUuidSyncResponse)
async def sync_kakao_login_uuids(
    db: Session = Depends(get_db),
    _: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """저장된 카카오 토큰으로 로그인 uuid를 일괄 조회해 저장한다."""
    users = (
        db.query(User)
        .filter(User.is_active.is_(True), User.kakao_id.is_not(None))
        .order_by(User.role, User.name)
        .all()
    )

    results: list[BulkLoginUuidSyncResult] = []
    synced_count = 0
    matched_count = 0
    mismatched_count = 0
    failed_count = 0

    for user in users:
        before_status = get_kakao_identity_status(user)
        try:
            access_token = await ensure_valid_token(user, db)
            kakao_user = await get_user_info(access_token)
            kakao_id = str(kakao_user.get("id"))
            if kakao_id != user.kakao_id:
                raise ValueError("저장된 카카오 ID와 토큰 사용자가 다릅니다")
            login_uuid = extract_kakao_login_uuid(kakao_user)
            if not login_uuid:
                raise ValueError("카카오 사용자 정보에 for_partner.uuid가 없습니다")

            user.kakao_login_uuid = login_uuid
            db.commit()
            db.refresh(user)
        except Exception as exc:
            db.rollback()
            failed_count += 1
            results.append(BulkLoginUuidSyncResult(
                user_id=user.id,
                name=user.name,
                status_before=before_status,
                status_after=before_status,
                synced=False,
                error=_token_refresh_error_message(exc),
            ))
            continue

        synced_count += 1
        after_status = get_kakao_identity_status(user)
        if after_status == "matched":
            matched_count += 1
        elif after_status == "mismatch":
            mismatched_count += 1

        results.append(BulkLoginUuidSyncResult(
            user_id=user.id,
            name=user.name,
            status_before=before_status,
            status_after=after_status,
            synced=True,
        ))

    return BulkLoginUuidSyncResponse(
        summary=BulkLoginUuidSyncSummary(
            total=len(users),
            synced=synced_count,
            matched=matched_count,
            mismatched=mismatched_count,
            failed=failed_count,
        ),
        results=results,
    )


class UserScopeDiagnosis(BaseModel):
    user_id: int
    user_name: str
    kakao_id: str | None
    oauth_linked: bool
    token_expired: bool
    kakao_token_status: str
    kakao_token_expires_at: str | None = None
    token_error: str | None = None
    all_agreed: bool | None
    missing_scopes: list[str]
    scopes: list[ScopeItem]
    error: str | None = None


@router.get("/user/{user_id}/scopes", response_model=UserScopeDiagnosis)
async def diagnose_user_scopes(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """특정 사용자의 카카오 동의 항목 진단 (관리자 전용)

    - 해당 사용자가 카카오 로그인 완료했는지
    - 토큰이 유효한지
    - 필수 scope(friends, talk_message)에 동의했는지
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

    kakao_token_status, kakao_token_expires_at = get_kakao_token_status(user)
    result = UserScopeDiagnosis(
        user_id=user.id,
        user_name=user.name,
        kakao_id=user.kakao_id,
        oauth_linked=bool(user.kakao_id),
        token_expired=kakao_token_status in {
            "missing_token",
            "refresh_needed",
            "refresh_unavailable",
        },
        kakao_token_status=kakao_token_status,
        kakao_token_expires_at=kakao_token_expires_at,
        all_agreed=None,
        missing_scopes=[],
        scopes=[],
    )

    if not user.kakao_id:
        result.error = "본 서비스에 카카오 로그인을 완료하지 않았습니다"
        return result
    if not user.kakao_access_token:
        result.error = "카카오 토큰 정보가 없습니다"
        return result

    try:
        access_token = await ensure_valid_token(user, db)
    except ValueError as exc:
        kakao_token_status, kakao_token_expires_at = get_kakao_token_status(user)
        result.kakao_token_status = kakao_token_status
        result.kakao_token_expires_at = kakao_token_expires_at
        result.token_expired = True
        result.token_error = str(exc)
        result.error = f"토큰 유효하지 않음: {exc}"
        return result
    except Exception as exc:
        result.kakao_token_status = "invalid"
        result.token_expired = True
        result.token_error = str(exc)
        result.error = f"토큰 갱신 실패: {exc}"
        return result

    kakao_token_status, kakao_token_expires_at = get_kakao_token_status(user)
    result.kakao_token_status = kakao_token_status
    result.kakao_token_expires_at = kakao_token_expires_at
    result.token_expired = kakao_token_status != "valid"

    try:
        data = await get_user_scopes(access_token)
    except Exception as exc:
        result.error = f"동의 항목 조회 실패: {exc}"
        return result

    scopes_raw = data.get("scopes", []) or []
    result.scopes = [ScopeItem(**s) for s in scopes_raw]
    agreed_ids = {s.id for s in result.scopes if s.agreed}
    result.missing_scopes = [sid for sid in REQUIRED_SCOPES if sid not in agreed_ids]
    result.all_agreed = len(result.missing_scopes) == 0

    # 진단 결과를 user에 캐시 (목록에서 컬럼 표시용)
    from datetime import datetime, timezone
    user.kakao_scopes_ok = result.all_agreed
    user.kakao_scopes_checked_at = datetime.now(timezone.utc)
    db.commit()
    return result
