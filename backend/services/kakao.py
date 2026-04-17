"""카카오 API 서비스 (로그인 + 친구에게 보내기)"""

import json
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from config import settings
from models.user import User

KAKAO_AUTH_URL = "https://kauth.kakao.com"
KAKAO_API_URL = "https://kapi.kakao.com"


def get_authorize_url() -> str:
    """카카오 로그인 인가 URL 생성"""
    return (
        f"{KAKAO_AUTH_URL}/oauth/authorize"
        f"?client_id={settings.kakao_rest_api_key}"
        f"&redirect_uri={settings.kakao_redirect_uri}"
        f"&response_type=code"
        f"&scope=profile_nickname,friends,talk_message"
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
    expires_at = user.kakao_token_expires_at

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
