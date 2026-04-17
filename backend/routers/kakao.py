"""카카오 친구 목록 조회 + 검토위원 매칭 라우터"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models.user import User, UserRole
from routers.auth import require_roles
from services.kakao import ensure_valid_token, get_friends, get_user_scopes

router = APIRouter()


REQUIRED_SCOPES = ["profile_nickname", "friends", "talk_message"]


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
    from config import settings

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
        scope_param = ",".join(missing)
        reauthorize_url = (
            f"https://kauth.kakao.com/oauth/authorize"
            f"?client_id={settings.kakao_rest_api_key}"
            f"&redirect_uri={settings.kakao_redirect_uri}"
            f"&response_type=code"
            f"&scope={scope_param}"
        )

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


class UserMatchStatus(BaseModel):
    user_id: int
    name: str
    email: str
    role: UserRole
    kakao_oauth_linked: bool  # 본 서비스에 카카오 로그인 완료 (kakao_id 존재)
    kakao_linked: bool  # 내 친구 목록에서 매칭 완료 (kakao_uuid 존재) — 기존 필드 유지
    kakao_uuid: str | None = None


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
    return [
        UserMatchStatus(
            user_id=u.id,
            name=u.name,
            email=u.email,
            role=u.role,
            kakao_oauth_linked=bool(u.kakao_id),
            kakao_linked=bool(u.kakao_uuid),
            kakao_uuid=u.kakao_uuid,
        )
        for u in users
    ]


class UserScopeDiagnosis(BaseModel):
    user_id: int
    user_name: str
    kakao_id: str | None
    oauth_linked: bool
    token_expired: bool
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

    result = UserScopeDiagnosis(
        user_id=user.id,
        user_name=user.name,
        kakao_id=user.kakao_id,
        oauth_linked=bool(user.kakao_id),
        token_expired=False,
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
        result.token_expired = True
        result.error = f"토큰 유효하지 않음: {exc}"
        return result

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
    return result
