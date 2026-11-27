"""카카오 서버 연결 실패(ConnectTimeout·ConnectError) 대응 테스트.

운영 장애(2026-11-27): Render 에서 kauth.kakao.com 으로 연결이 5초 안에 맺어지지 않아
카카오 로그인이 실패했다. 연결 단계의 실패는 요청이 카카오에 도달하기 전이므로
인가 코드가 소모되지 않는다. 그래서 다시 시도해도 안전하다.
"""

import httpx
import pytest
import respx

from config import settings
from models.user import UserRole
from services.kakao import _kakao_client, generate_oauth_state

TOKEN_URL = "https://kauth.kakao.com/oauth/token"
USER_URL = "https://kapi.kakao.com/v2/user/me"
CONNECT_MESSAGE = "카카오 서버 연결이 지연되고 있습니다. 로그인 화면에서 다시 시도해 주세요"

TOKEN_OK = httpx.Response(
    200,
    json={
        "access_token": "kakao_access_x",
        "refresh_token": "kakao_refresh_x",
        "expires_in": 21599,
        "token_type": "bearer",
    },
)


@pytest.fixture(autouse=True)
def _fixed_kakao_settings(monkeypatch):
    """실행 환경의 환경변수와 무관하게 설정값을 고정한다."""
    monkeypatch.setattr(settings, "kakao_connect_timeout_seconds", 10.0)
    monkeypatch.setattr(settings, "kakao_http_timeout_seconds", 10.0)
    monkeypatch.setattr(settings, "kakao_connect_retries", 1)


def _user_ok(kakao_id: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": int(kakao_id),
            "properties": {"nickname": "홍길동"},
            "kakao_account": {"profile": {"nickname": "홍길동"}},
        },
    )


def test_kakao_client_uses_configured_timeouts():
    """카카오 호출 클라이언트는 설정한 제한 시간을 쓴다(httpx 기본 5초가 아니다)."""
    client = _kakao_client()
    assert client.timeout.connect == 10.0
    assert client.timeout.read == 10.0


def test_callback_retries_token_exchange_after_connect_timeout(client, make_user):
    """토큰 교환이 연결 단계에서 한 번 실패해도 다시 시도해 로그인한다."""
    make_user(UserRole.REVIEWER, email="retry-ok@example.com", kakao_id="555001")

    with respx.mock(assert_all_called=False) as mock:
        token_route = mock.post(TOKEN_URL).mock(
            side_effect=[httpx.ConnectTimeout("connect timeout"), TOKEN_OK]
        )
        mock.get(USER_URL).mock(return_value=_user_ok("555001"))

        res = client.get(
            f"/api/auth/kakao/callback?code=code_x&state={generate_oauth_state()}"
        )

    assert res.status_code == 200
    assert res.json()["access_token"]
    assert token_route.call_count == 2


def test_callback_returns_503_when_connect_keeps_failing(client, make_user):
    """다시 시도해도 연결하지 못하면 503 과 연결 지연 문구를 준다."""
    make_user(UserRole.REVIEWER, email="retry-fail@example.com", kakao_id="555002")

    with respx.mock(assert_all_called=False) as mock:
        token_route = mock.post(TOKEN_URL).mock(
            side_effect=httpx.ConnectTimeout("connect timeout")
        )

        res = client.get(
            f"/api/auth/kakao/callback?code=code_x&state={generate_oauth_state()}"
        )

    assert res.status_code == 503
    assert res.json()["detail"] == CONNECT_MESSAGE
    assert token_route.call_count == 2


def test_callback_does_not_retry_when_kakao_rejects(client):
    """카카오가 응답으로 거절한 경우는 다시 시도하지 않는다(인가 코드는 한 번만 쓴다)."""
    with respx.mock(assert_all_called=False) as mock:
        token_route = mock.post(TOKEN_URL).mock(
            return_value=httpx.Response(
                400, json={"error": "invalid_grant", "error_code": "KOE320"}
            )
        )

        res = client.get(
            f"/api/auth/kakao/callback?code=code_x&state={generate_oauth_state()}"
        )

    assert res.status_code == 400
    assert res.json()["detail"] == "카카오 로그인 처리 중 오류가 발생했습니다"
    assert token_route.call_count == 1


def test_callback_does_not_retry_on_read_timeout(client):
    """응답을 기다리다 끊긴 경우는 요청이 도달했을 수 있어 다시 시도하지 않는다."""
    with respx.mock(assert_all_called=False) as mock:
        token_route = mock.post(TOKEN_URL).mock(
            side_effect=httpx.ReadTimeout("read timeout")
        )

        res = client.get(
            f"/api/auth/kakao/callback?code=code_x&state={generate_oauth_state()}"
        )

    assert res.status_code == 400
    assert token_route.call_count == 1


def test_callback_retries_user_info_after_connect_error(client, make_user):
    """사용자 정보 조회도 연결 단계 실패는 다시 시도한다."""
    make_user(UserRole.REVIEWER, email="retry-user@example.com", kakao_id="555003")

    with respx.mock(assert_all_called=False) as mock:
        mock.post(TOKEN_URL).mock(return_value=TOKEN_OK)
        user_route = mock.get(USER_URL).mock(
            side_effect=[httpx.ConnectError("connect failed"), _user_ok("555003")]
        )

        res = client.get(
            f"/api/auth/kakao/callback?code=code_x&state={generate_oauth_state()}"
        )

    assert res.status_code == 200
    assert user_route.call_count == 2


def test_callback_does_not_retry_when_retries_is_zero(client, monkeypatch):
    """재시도 0회 설정이면 첫 연결 실패에서 바로 503 을 준다."""
    monkeypatch.setattr(settings, "kakao_connect_retries", 0)

    with respx.mock(assert_all_called=False) as mock:
        token_route = mock.post(TOKEN_URL).mock(
            side_effect=httpx.ConnectTimeout("connect timeout")
        )

        res = client.get(
            f"/api/auth/kakao/callback?code=code_x&state={generate_oauth_state()}"
        )

    assert res.status_code == 503
    assert token_route.call_count == 1


def test_callback_user_info_connect_failure_uses_code_only_once(client, make_user):
    """사용자 정보 조회가 끝내 연결하지 못해도 토큰 교환은 한 번만 한다."""
    make_user(UserRole.REVIEWER, email="retry-user-fail@example.com", kakao_id="555004")

    with respx.mock(assert_all_called=False) as mock:
        token_route = mock.post(TOKEN_URL).mock(return_value=TOKEN_OK)
        user_route = mock.get(USER_URL).mock(
            side_effect=httpx.ConnectTimeout("connect timeout")
        )

        res = client.get(
            f"/api/auth/kakao/callback?code=code_x&state={generate_oauth_state()}"
        )

    assert res.status_code == 503
    assert res.json()["detail"] == CONNECT_MESSAGE
    assert token_route.call_count == 1
    assert user_route.call_count == 2


def test_get_user_info_does_not_retry_by_default():
    """여러 사용자를 차례로 조회하는 호출자는 기본값(재시도 없음)을 쓴다."""
    import asyncio

    from services.kakao import KakaoConnectError, get_user_info

    with respx.mock(assert_all_called=False) as mock:
        user_route = mock.get(USER_URL).mock(
            side_effect=httpx.ConnectTimeout("connect timeout")
        )
        with pytest.raises(KakaoConnectError):
            asyncio.run(get_user_info("token_x"))

    assert user_route.call_count == 1


@pytest.mark.parametrize(
    "field, value",
    [
        ("kakao_connect_retries", -1),
        ("kakao_connect_timeout_seconds", 0),
        ("kakao_http_timeout_seconds", -5),
    ],
)
def test_settings_reject_invalid_kakao_values(field, value):
    """잘못된 환경변수는 기동 시점에 거부한다."""
    from pydantic import ValidationError

    from config import Settings

    with pytest.raises(ValidationError):
        Settings(**{field: value})
