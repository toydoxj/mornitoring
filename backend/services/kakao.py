"""카카오 API 서비스 (로그인 + 친구에게 보내기)"""

import json

import httpx

from config import settings

KAKAO_AUTH_URL = "https://kauth.kakao.com"
KAKAO_API_URL = "https://kapi.kakao.com"


def get_authorize_url() -> str:
    """카카오 로그인 인가 URL 생성"""
    return (
        f"{KAKAO_AUTH_URL}/oauth/authorize"
        f"?client_id={settings.kakao_rest_api_key}"
        f"&redirect_uri={settings.kakao_redirect_uri}"
        f"&response_type=code"
        f"&scope=friends,talk_message"
    )


async def exchange_code(code: str) -> dict:
    """인가 코드로 토큰 교환"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{KAKAO_AUTH_URL}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": settings.kakao_rest_api_key,
                "redirect_uri": settings.kakao_redirect_uri,
                "code": code,
            },
        )
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
