"""카카오 API 서비스 (로그인 + 친구에게 보내기)"""

import json
import secrets
from datetime import datetime, timedelta, timezone

import httpx
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from config import settings
from models.kakao_link_session import KakaoLinkSession
from models.user import User

KAKAO_AUTH_URL = "https://kauth.kakao.com"
KAKAO_API_URL = "https://kapi.kakao.com"


def generate_oauth_state() -> str:
    """CSRF 방어용 state JWT 생성 (10분 유효)."""
    exp = datetime.now(timezone.utc) + timedelta(minutes=10)
    return jwt.encode(
        {"nonce": secrets.token_urlsafe(16), "exp": int(exp.timestamp())},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def verify_oauth_state(state: str) -> bool:
    """state JWT 검증 — 서명·만료 확인."""
    if not state:
        return False
    try:
        jwt.decode(state, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        return True
    except JWTError:
        return False


LINK_SESSION_TTL_SECONDS = 600  # 10분


def create_link_session(
    db: Session,
    *,
    kakao_id: str,
    kakao_access_token: str,
    kakao_refresh_token: str,
    kakao_expires_in: int | None,
) -> str:
    """카카오 계정 연결용 1회성 세션 생성. 추측 불가한 session_id 반환.

    카카오 토큰을 프론트(URL/JSON/스토리지)에 노출하지 않고 서버에 보관한다.
    클라이언트는 session_id만 들고 `/link-account`로 돌아오며, 서버는
    `consume_link_session`으로 1회 검증 후 즉시 소모(consumed_at) 처리한다.
    """
    session = KakaoLinkSession(
        kakao_id=kakao_id,
        kakao_access_token=kakao_access_token,
        kakao_refresh_token=kakao_refresh_token or None,
        kakao_expires_in=kakao_expires_in,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=LINK_SESSION_TTL_SECONDS),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session.id


def _ensure_aware_utc(dt: datetime | None) -> datetime | None:
    """timezone-naive datetime은 UTC로 보정. SQLite 등 tz 미지원 백엔드 호환."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def lock_link_session(db: Session, session_id: str) -> KakaoLinkSession | None:
    """1회성 세션 행 락 + 만료/소비 검증. 통과 시 행 락된 세션 반환.

    소모(`consumed_at` 마킹)와 commit은 호출자가 모든 비즈니스 검증
    (사용자 인증·충돌 체크 등)을 통과한 뒤 같은 트랜잭션에서 처리한다.
    이 패턴으로 잘못된 비밀번호 시도가 세션을 소모해버리는 DoS를 방지한다.
    """
    if not session_id:
        return None
    session = (
        db.query(KakaoLinkSession)
        .filter(KakaoLinkSession.id == session_id)
        .with_for_update()
        .first()
    )
    if session is None:
        return None
    if session.consumed_at is not None:
        return None
    if _ensure_aware_utc(session.expires_at) <= datetime.now(timezone.utc):
        return None
    return session


def purge_expired_link_sessions(db: Session) -> int:
    """만료/소비된 세션 정리. 호출 시점에 즉시 삭제. 청소 cron이나 필요 시 호출."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    deleted = (
        db.query(KakaoLinkSession)
        .filter(
            (KakaoLinkSession.expires_at <= datetime.now(timezone.utc))
            | (KakaoLinkSession.consumed_at <= cutoff)
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted


def get_authorize_url() -> str:
    """카카오 로그인 인가 URL 생성 (CSRF state 포함)."""
    state = generate_oauth_state()
    return (
        f"{KAKAO_AUTH_URL}/oauth/authorize"
        f"?client_id={settings.kakao_rest_api_key}"
        f"&redirect_uri={settings.kakao_redirect_uri}"
        f"&response_type=code"
        f"&scope=profile_nickname,friends,talk_message"
        f"&state={state}"
    )


async def exchange_code(code: str) -> dict:
    """인가 코드로 토큰 교환"""
    data = {
        "grant_type": "authorization_code",
        "client_id": settings.kakao_rest_api_key,
        "redirect_uri": settings.kakao_redirect_uri,
        "code": code,
    }
    if settings.kakao_client_secret:
        data["client_secret"] = settings.kakao_client_secret

    async with httpx.AsyncClient() as client:
        response = await client.post(f"{KAKAO_AUTH_URL}/oauth/token", data=data)
        response.raise_for_status()
        return response.json()


async def get_user_info(access_token: str) -> dict:
    """카카오 사용자 정보 조회"""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{KAKAO_API_URL}/v2/user/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        return response.json()


async def get_user_scopes(access_token: str) -> dict:
    """현재 토큰에 동의된 scope 목록 조회

    Returns:
        {"id": 1234, "scopes": [{"id": "friends", "display_name": "...", "agreed": true, ...}, ...]}
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{KAKAO_API_URL}/v2/user/scopes",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        return response.json()


async def refresh_token(refresh_token_str: str) -> dict:
    """토큰 갱신"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{KAKAO_AUTH_URL}/oauth/token",
            data={
                "grant_type": "refresh_token",
                "client_id": settings.kakao_rest_api_key,
                "refresh_token": refresh_token_str,
            },
        )
        response.raise_for_status()
        return response.json()


async def ensure_valid_token(user: User, db: Session) -> str:
    """카카오 토큰 유효성 보장. 만료 임박/만료 시 자동 갱신.

    Returns:
        유효한 access_token 문자열

    Raises:
        ValueError: refresh_token이 없거나 갱신 실패 시
    """
    if not user.kakao_access_token:
        raise ValueError("카카오 연동이 되어 있지 않습니다")

    now = datetime.now(timezone.utc)
    expires_at = _ensure_aware_utc(user.kakao_token_expires_at)

    # 만료 5분 전부터 갱신 대상
    needs_refresh = expires_at is None or (expires_at - now) < timedelta(minutes=5)

    if not needs_refresh:
        return user.kakao_access_token

    if not user.kakao_refresh_token:
        raise ValueError("refresh_token이 없어 토큰을 갱신할 수 없습니다")

    refreshed = await refresh_token(user.kakao_refresh_token)
    new_access = refreshed.get("access_token")
    if not new_access:
        raise ValueError(f"토큰 갱신 실패: {refreshed}")

    user.kakao_access_token = new_access
    if refreshed.get("refresh_token"):
        user.kakao_refresh_token = refreshed["refresh_token"]
    expires_in = refreshed.get("expires_in", 21599)
    user.kakao_token_expires_at = now + timedelta(seconds=expires_in)
    db.commit()
    db.refresh(user)
    return new_access


async def get_friends(access_token: str) -> list[dict]:
    """카카오 친구 목록 조회

    Returns:
        [{"id": uuid, "profile_nickname": "홍길동", ...}, ...]
    """
    friends = []
    offset = 0
    limit = 100

    async with httpx.AsyncClient() as client:
        while True:
            response = await client.get(
                f"{KAKAO_API_URL}/v1/api/talk/friends",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"offset": offset, "limit": limit, "order": "asc"},
            )
            if response.status_code != 200:
                break

            data = response.json()
            elements = data.get("elements", [])
            friends.extend(elements)

            if len(elements) < limit:
                break
            offset += limit

    return friends


async def send_message_to_self(
    access_token: str,
    title: str,
    description: str,
    link_url: str = "",
) -> dict:
    """나에게 메시지 보내기 (UUID 불필요, 친구 관계 불필요)

    Returns:
        성공 시 {"result_code": 0}, 실패 시 {"error": code, "detail": ...}
    """
    template_object = {
        "object_type": "text",
        "text": f"[{title}]\n{description}",
        "link": {
            "web_url": link_url or "https://ksea-m.vercel.app",
            "mobile_web_url": link_url or "https://ksea-m.vercel.app",
        },
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{KAKAO_API_URL}/v2/api/talk/memo/default/send",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "template_object": json.dumps(template_object),
            },
        )

        if response.status_code == 200:
            return response.json()
        else:
            return {"error": response.status_code, "detail": response.text}


async def send_message_to_friends(
    access_token: str,
    receiver_uuids: list[str],
    title: str,
    description: str,
    link_url: str = "",
) -> dict:
    """친구에게 텍스트 메시지 보내기

    Args:
        access_token: 발신자의 카카오 access token
        receiver_uuids: 수신자 UUID 목록 (최대 5명)
        title: 메시지 제목
        description: 메시지 본문

    Returns:
        {"successful_receiver_uuids": [...], "failure_info": [...]}
    """
    template_object = {
        "object_type": "text",
        "text": f"[{title}]\n{description}",
        "link": {
            "web_url": link_url or "https://ksea-m.vercel.app",
            "mobile_web_url": link_url or "https://ksea-m.vercel.app",
        },
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{KAKAO_API_URL}/v1/api/talk/friends/message/default/send",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "receiver_uuids": json.dumps(receiver_uuids),
                "template_object": json.dumps(template_object),
            },
        )

        if response.status_code == 200:
            return response.json()
        else:
            return {"error": response.status_code, "detail": response.text}
