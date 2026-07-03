"""카카오 로그인 재연결 링크 회귀 테스트."""

from urllib.parse import parse_qs, urlparse

from models.user import UserRole
from services.kakao import decode_oauth_state


def test_reviewer_cannot_issue_kakao_reconnect_link(client, make_reviewer, make_user):
    """검토위원은 다른 사용자의 재연결 링크를 발급할 수 없다."""
    _, _, headers = make_reviewer()
    target, _ = make_user(UserRole.REVIEWER)

    res = client.post(
        f"/api/kakao/users/{target.id}/reconnect-link",
        headers=headers,
    )

    assert res.status_code == 403


def test_admin_issues_hidden_kakao_reconnect_link_and_binds_target(
    client,
    make_user,
):
    """관리자 발급 링크는 숨김 페이지 URL이며 OAuth state에 대상 user_id를 고정한다."""
    _, headers = make_user(UserRole.TEAM_LEADER)
    target, _ = make_user(
        UserRole.REVIEWER,
        name="재연결대상",
        email="kakao-reconnect-target@example.com",
    )

    issue_res = client.post(
        f"/api/kakao/users/{target.id}/reconnect-link",
        headers=headers,
    )

    assert issue_res.status_code == 200
    issued = issue_res.json()
    assert issued["user_id"] == target.id
    assert issued["name"] == "재연결대상"
    assert "/kakao-reconnect?token=" in issued["reconnect_url"]
    assert issued["expires_at"]

    reconnect_page = urlparse(issued["reconnect_url"])
    reconnect_params = parse_qs(reconnect_page.query)
    raw_token = reconnect_params["token"][0]

    login_res = client.get(
        "/api/auth/kakao/reconnect-login",
        params={"token": raw_token},
    )

    assert login_res.status_code == 200
    body = login_res.json()
    assert body["user_name"] == "재연결대상"

    kakao_url = urlparse(body["url"])
    kakao_params = parse_qs(kakao_url.query)
    state_payload = decode_oauth_state(kakao_params["state"][0])
    assert state_payload is not None
    assert state_payload["setup_user_id"] == target.id
    assert kakao_params["prompt"] == ["select_account"]


def test_hidden_kakao_reconnect_login_rejects_invalid_token(client):
    """서명되지 않은 임의 토큰은 OAuth URL을 발급하지 않는다."""
    res = client.get(
        "/api/auth/kakao/reconnect-login",
        params={"token": "not-a-valid-token"},
    )

    assert res.status_code == 401
