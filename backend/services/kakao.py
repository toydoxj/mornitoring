"""카카오 API 서비스 (로그인 + 친구에게 보내기)"""

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


async def refresh_token(refresh_token: str) -> dict:
    """토큰 갱신"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{KAKAO_AUTH_URL}/oauth/token",
            data={
                "grant_type": "refresh_token",
                "client_id": settings.kakao_rest_api_key,
                "refresh_token": refresh_token,
            },
        )
        response.raise_for_status()
        return response.json()


async def send_message_to_friend(
    sender_access_token: str,
    receiver_uuid: str,
    title: str,
    description: str,
) -> bool:
    """친구에게 메시지 보내기

    sender_access_token: 발신자(시스템 운영 계정)의 카카오 access token
    receiver_uuid: 수신자의 카카오 친구 UUID
    """
    template_object = {
        "object_type": "text",
        "text": f"[{title}]\n{description}",
        "link": {
            "web_url": "http://localhost:3000",
            "mobile_web_url": "http://localhost:3000",
        },
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{KAKAO_API_URL}/v1/api/talk/friends/message/default/send",
                headers={"Authorization": f"Bearer {sender_access_token}"},
                data={
                    "receiver_uuids": f'["{receiver_uuid}"]',
                    "template_object": str(template_object).replace("'", '"'),
                },
            )
            return response.status_code == 200
        except Exception:
            return False
