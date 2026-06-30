"""N5 — respx로 카카오 외부 호출을 mock한 통합 테스트.

6개 시나리오:
1. OAuth 콜백 — 기존 사용자 로그인 성공
2. OAuth 콜백 — need_link (link_session_id 응답)
3. /link-account — link_session_id + 비번 → 카카오 토큰 user에 저장
4. send-invite — 카카오 발송 성공 → delivery=kakao
5. send-invite — 카카오 발송 실패 → manual fallback
6. ensure_valid_token — refresh 성공 → access_token 갱신
"""

import asyncio
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from models.kakao_link_session import KakaoLinkSession
from models.user import UserRole
from services.kakao import (
    decode_oauth_state,
    generate_oauth_state,
    generate_setup_context,
)


def test_kakao_login_consent_url_requests_additional_consent(client):
    """재동의 로그인 URL은 scope/state와 계정 선택 프롬프트를 포함한다."""
    res = client.get("/api/auth/kakao/login?consent=true")
    assert res.status_code == 200

    parsed = urlparse(res.json()["url"])
    params = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "kauth.kakao.com"
    assert params["redirect_uri"] == ["http://localhost/callback"]
    assert params["response_type"] == ["code"]
    assert params["scope"] == ["profile_nickname,friends,talk_message"]
    assert params["prompt"] == ["select_account"]
    assert params["state"][0]


def test_kakao_login_setup_context_binds_setup_user(client, make_user):
    """초대 직후 카카오 연동 URL은 state에 초대 대상 user_id를 담는다."""
    target, _ = make_user(UserRole.REVIEWER)
    setup_context = generate_setup_context(target.id)

    res = client.get(f"/api/auth/kakao/login?setup_context={setup_context}")
    assert res.status_code == 200

    parsed = urlparse(res.json()["url"])
    params = parse_qs(parsed.query)
    state_payload = decode_oauth_state(params["state"][0])
    assert state_payload is not None
    assert state_payload["setup_user_id"] == target.id
    assert params["prompt"] == ["select_account"]


# ===== 1. OAuth 콜백 — 기존 사용자 로그인 =====

def test_kakao_callback_existing_user_logs_in(client, db_session, kakao_mock, make_user):
    """kakao_id가 이미 매칭된 사용자가 카카오 OAuth로 다시 로그인."""
    user, _ = make_user(
        UserRole.REVIEWER,
        email="kakao-existing@example.com",
        kakao_id="98765",
    )

    kakao_mock.token_ok(access_token="new_access", refresh_token="new_refresh")
    kakao_mock.user_info_ok(kakao_id="98765", nickname="홍길동", uuid="login-uuid-98765")

    state = generate_oauth_state()
    res = client.get(f"/api/auth/kakao/callback?code=auth_code_x&state={state}")

    assert res.status_code == 200
    body = res.json()
    assert body["access_token"]
    assert body.get("need_link") is None or body.get("need_link") is False
    # user의 kakao_access_token 갱신됐는지 (httpx 별도 세션이라 직접 조회로 검증)
    db_session.expire_all()
    from models.user import User as UserModel
    refreshed = db_session.query(UserModel).filter(UserModel.id == user.id).first()
    assert refreshed.kakao_access_token == "new_access"
    assert refreshed.kakao_login_uuid == "login-uuid-98765"
    assert refreshed.kakao_uuid is None


def test_kakao_callback_setup_context_rejects_other_linked_user(
    client, kakao_mock, make_user
):
    """다른 사람 초대 링크에서 내 카카오 계정 로그인이 완료되면 안 된다."""
    target, _ = make_user(
        UserRole.REVIEWER,
        email="invite-owner@example.com",
        kakao_uuid="owner-uuid",
    )
    other, _ = make_user(
        UserRole.REVIEWER,
        email="already-linked@example.com",
        kakao_id="22222",
        kakao_uuid="other-uuid",
    )

    kakao_mock.token_ok(access_token="other_access", refresh_token="other_refresh")
    kakao_mock.user_info_ok(kakao_id="22222", uuid="other-uuid")

    state = generate_oauth_state(setup_user_id=target.id)
    res = client.get(f"/api/auth/kakao/callback?code=auth_code_x&state={state}")

    assert res.status_code == 409
    assert "다른 사용자" in res.json()["detail"]
    assert other.id != target.id


def test_kakao_callback_setup_context_rejects_uuid_mismatch(
    client, kakao_mock, make_user
):
    """초대 대상자의 카카오 uuid와 로그인한 카카오 uuid가 다르면 연결 세션도 만들지 않는다."""
    target, _ = make_user(
        UserRole.REVIEWER,
        email="uuid-owner@example.com",
        kakao_uuid="owner-uuid",
    )

    kakao_mock.token_ok(access_token="new_access", refresh_token="new_refresh")
    kakao_mock.user_info_ok(kakao_id="33333", uuid="wrong-uuid")

    state = generate_oauth_state(setup_user_id=target.id)
    res = client.get(f"/api/auth/kakao/callback?code=auth_code_x&state={state}")

    assert res.status_code == 409
    assert "카카오 계정이 다릅니다" in res.json()["detail"]


def test_kakao_callback_setup_context_auto_links_matching_uuid(
    client, db_session, kakao_mock, make_user
):
    """초대 대상 uuid와 로그인 uuid가 일치하면 이메일/비밀번호 연결 화면 없이 연결한다."""
    target, _ = make_user(
        UserRole.REVIEWER,
        email="setup-auto-link@example.com",
        kakao_uuid="target-uuid",
    )

    kakao_mock.token_ok(access_token="auto_access", refresh_token="auto_refresh")
    kakao_mock.user_info_ok(kakao_id="44444", uuid="target-uuid")

    state = generate_oauth_state(setup_user_id=target.id)
    res = client.get(f"/api/auth/kakao/callback?code=auth_code_x&state={state}")

    assert res.status_code == 200
    body = res.json()
    assert body["access_token"]
    assert body.get("need_link") is None or body.get("need_link") is False

    db_session.expire_all()
    from models.user import User as UserModel
    refreshed = db_session.query(UserModel).filter(UserModel.id == target.id).first()
    assert refreshed.kakao_id == "44444"
    assert refreshed.kakao_login_uuid == "target-uuid"
    assert refreshed.kakao_access_token == "auto_access"


# ===== 2. OAuth 콜백 — need_link =====

def test_kakao_callback_unknown_kakao_id_returns_link_session(
    client, db_session, kakao_mock
):
    """매칭된 사용자 없는 kakao_id → need_link + link_session_id 응답."""
    kakao_mock.token_ok()
    kakao_mock.user_info_ok(kakao_id="99999", nickname="신규유저", uuid="login-uuid-99999")

    state = generate_oauth_state()
    res = client.get(f"/api/auth/kakao/callback?code=any_code&state={state}")

    assert res.status_code == 200
    body = res.json()
    assert body["need_link"] is True
    assert body["link_session_id"]
    assert "kakao_access_token" not in body  # 토큰 노출 X
    assert "kakao_refresh_token" not in body

    # DB에 link_session 행 생성 확인
    rows = db_session.query(KakaoLinkSession).filter(
        KakaoLinkSession.id == body["link_session_id"]
    ).all()
    assert len(rows) == 1
    assert rows[0].kakao_id == "99999"
    assert rows[0].kakao_login_uuid == "login-uuid-99999"


def test_kakao_callback_logged_in_unlinked_user_links_directly(
    client, db_session, kakao_mock, make_user
):
    """이메일 로그인 상태의 미연동 사용자는 콜백에서 현재 계정에 바로 연결된다."""
    user, headers = make_user(
        UserRole.REVIEWER,
        email="logged-in-link@example.com",
    )

    kakao_mock.token_ok(access_token="direct_access", refresh_token="direct_refresh")
    kakao_mock.user_info_ok(kakao_id="777777", uuid="direct-login-uuid")

    state = generate_oauth_state()
    res = client.get(
        f"/api/auth/kakao/callback?code=direct_code&state={state}",
        headers=headers,
    )

    assert res.status_code == 200
    body = res.json()
    assert body["access_token"]
    assert body.get("need_link") is None or body.get("need_link") is False

    db_session.expire_all()
    from models.user import User as UserModel
    refreshed = db_session.query(UserModel).filter(UserModel.id == user.id).first()
    assert refreshed.kakao_id == "777777"
    assert refreshed.kakao_login_uuid == "direct-login-uuid"
    assert refreshed.kakao_access_token == "direct_access"


def test_kakao_callback_logged_in_user_rejects_other_users_kakao(
    client, kakao_mock, make_user
):
    """로그인 중인 사용자에게 다른 사용자 카카오 계정을 연결하지 않는다."""
    _, headers = make_user(
        UserRole.REVIEWER,
        email="current-user@example.com",
    )
    make_user(
        UserRole.REVIEWER,
        email="already-linked-owner@example.com",
        kakao_id="888888",
    )

    kakao_mock.token_ok(access_token="conflict_access", refresh_token="conflict_refresh")
    kakao_mock.user_info_ok(kakao_id="888888", uuid="owner-uuid")

    state = generate_oauth_state()
    res = client.get(
        f"/api/auth/kakao/callback?code=conflict_code&state={state}",
        headers=headers,
    )

    assert res.status_code == 409
    assert "이미 다른 사용자" in res.json()["detail"]


# ===== 3. /link-account 성공 =====

def test_link_account_success_saves_kakao_id(
    client, db_session, kakao_mock, make_user
):
    """need_link → /link-account → user.kakao_id 저장 + 로그인 응답."""
    user, _ = make_user(
        UserRole.REVIEWER,
        email="link-target@example.com",
        password="rightpw1",
    )

    # 먼저 OAuth 콜백으로 link_session 생성
    kakao_mock.token_ok(access_token="kakao_acc_z", refresh_token="kakao_ref_z")
    kakao_mock.user_info_ok(kakao_id="55555", uuid="login-uuid-55555")
    state = generate_oauth_state()
    callback_res = client.get(f"/api/auth/kakao/callback?code=any&state={state}")
    session_id = callback_res.json()["link_session_id"]

    # link-account 호출
    res = client.post(
        "/api/auth/link-account",
        json={
            "email": user.email,
            "password": "rightpw1",
            "link_session_id": session_id,
        },
    )
    assert res.status_code == 200
    assert res.json()["access_token"]

    db_session.expire_all()
    from models.user import User as UserModel
    refreshed = db_session.query(UserModel).filter(UserModel.id == user.id).first()
    assert refreshed.kakao_id == "55555"
    assert refreshed.kakao_login_uuid == "login-uuid-55555"
    assert refreshed.kakao_access_token == "kakao_acc_z"


# ===== 4. send-invite 카카오 발송 성공 =====

def test_send_invite_kakao_delivery_success(
    client, kakao_mock, make_user
):
    """관리자가 카카오 토큰 + 매칭된 사용자 → 카카오 발송 성공."""
    sender, headers = make_user(
        UserRole.TEAM_LEADER,
        kakao_id="11",
        kakao_access_token="sender_access",
        kakao_refresh_token="sender_refresh",
        kakao_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
    )
    target, _ = make_user(
        UserRole.REVIEWER,
        email="kakao-target@example.com",
        kakao_uuid="target-uuid-001",
    )

    kakao_mock.friend_send_ok(
        success_uuids=["target-uuid-001"],
        assert_text_contains=[
            "건축구조안전 모니터링 초대",
            "비밀번호를 설정한 뒤 로그인해주세요",
            "/setup-password?token=",
        ],
        assert_link_url_contains="/setup-password?token=",
    )

    res = client.post(f"/api/users/{target.id}/send-invite", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["delivery"] == "kakao"
    assert body["error"] is None
    # 카카오 성공 시 setup_url은 응답에 포함되지 않음 (보안)
    assert body["setup_url"] is None


# ===== 5. send-invite 카카오 발송 실패 → manual fallback =====

def test_send_invite_kakao_delivery_failure_falls_back_to_manual(
    client, kakao_mock, make_user
):
    sender, headers = make_user(
        UserRole.TEAM_LEADER,
        kakao_id="22",
        kakao_access_token="sender_access_2",
        kakao_refresh_token="sender_refresh_2",
        kakao_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
    )
    target, _ = make_user(
        UserRole.REVIEWER,
        email="fail-target@example.com",
        kakao_uuid="target-uuid-fail",
    )

    kakao_mock.friend_send_fail(status_code=400, msg="not a friend")

    res = client.post(f"/api/users/{target.id}/send-invite", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["delivery"] == "manual"
    assert body["setup_url"] and "token=" in body["setup_url"]
    assert body["error"]  # fallback 사유 채워짐


# ===== 7. send-invite — sender 토큰 임박 → 자동 refresh 후 발송 성공 (end-to-end) =====

def test_send_invite_refreshes_sender_token_then_sends(
    client, db_session, kakao_mock, make_user
):
    """sender 토큰이 만료 임박이면 ensure_valid_token이 자동 refresh + friend message 발송."""
    sender, headers = make_user(
        UserRole.TEAM_LEADER,
        kakao_id="33",
        kakao_access_token="old_sender_access",
        kakao_refresh_token="old_sender_refresh",
        kakao_token_expires_at=datetime.now(timezone.utc) + timedelta(minutes=2),  # 임박
    )
    target, _ = make_user(
        UserRole.REVIEWER,
        email="refresh-target@example.com",
        kakao_uuid="refresh-uuid-001",
    )

    kakao_mock.token_ok(access_token="refreshed_sender_access", refresh_token="refreshed_sender_refresh")
    kakao_mock.friend_send_ok(
        success_uuids=["refresh-uuid-001"],
        assert_text_contains=[
            "비밀번호를 설정한 뒤 로그인해주세요",
            "/setup-password?token=",
        ],
        assert_link_url_contains="/setup-password?token=",
    )

    res = client.post(f"/api/users/{target.id}/send-invite", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["delivery"] == "kakao"
    assert body["error"] is None

    # sender의 토큰이 갱신됐는지 확인
    db_session.expire_all()
    from models.user import User as UserModel
    refreshed_sender = db_session.query(UserModel).filter(UserModel.id == sender.id).first()
    assert refreshed_sender.kakao_access_token == "refreshed_sender_access"


# ===== 6. ensure_valid_token refresh 성공 =====

def test_ensure_valid_token_auto_refresh(db_session, kakao_mock, make_user, monkeypatch):
    """expires_at이 5분 이내면 자동 refresh → user 토큰 갱신."""
    from config import settings
    from services.kakao import ensure_valid_token

    monkeypatch.setattr(settings, "kakao_rest_api_key", "test_rest_key")
    monkeypatch.setattr(settings, "kakao_client_secret", "test_client_secret")

    user, _ = make_user(
        UserRole.SECRETARY,
        kakao_access_token="old_access",
        kakao_refresh_token="old_refresh",
        kakao_token_expires_at=datetime.now(timezone.utc) + timedelta(minutes=2),  # 임박
    )

    kakao_mock.token_ok(
        access_token="refreshed_access",
        refresh_token="refreshed_refresh",
        assert_form={
            "grant_type": "refresh_token",
            "client_id": "test_rest_key",
            "client_secret": "test_client_secret",
            "refresh_token": "old_refresh",
        },
    )

    new_access = asyncio.run(ensure_valid_token(user, db_session))
    assert new_access == "refreshed_access"

    db_session.expire_all()
    from models.user import User as UserModel
    refreshed = db_session.query(UserModel).filter(UserModel.id == user.id).first()
    assert refreshed.kakao_access_token == "refreshed_access"
    assert refreshed.kakao_refresh_token == "refreshed_refresh"


def test_bulk_refresh_kakao_tokens_refreshes_needed_only(
    client, db_session, kakao_mock, make_user
):
    """일괄 갱신은 refresh_needed 대상만 갱신하고 나머지는 건너뛴다."""
    _, headers = make_user(UserRole.TEAM_LEADER)
    target, _ = make_user(
        UserRole.SECRETARY,
        email="bulk-refresh-needed@example.com",
        kakao_id="bulk-refresh-needed",
        kakao_access_token="old_bulk_access",
        kakao_refresh_token="old_bulk_refresh",
        kakao_token_expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    valid, _ = make_user(
        UserRole.SECRETARY,
        email="bulk-refresh-valid@example.com",
        kakao_id="bulk-refresh-valid",
        kakao_access_token="valid_bulk_access",
        kakao_refresh_token="valid_bulk_refresh",
        kakao_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    unavailable, _ = make_user(
        UserRole.REVIEWER,
        email="bulk-refresh-unavailable@example.com",
        kakao_id="bulk-refresh-unavailable",
        kakao_access_token="expired_no_refresh_access",
        kakao_refresh_token=None,
        kakao_token_expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )

    kakao_mock.token_ok(
        access_token="bulk_refreshed_access",
        refresh_token="bulk_refreshed_refresh",
    )

    res = client.post("/api/kakao/tokens/refresh", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["summary"] == {
        "total": 3,
        "refreshed": 1,
        "skipped": 2,
        "failed": 0,
    }
    results = {item["user_id"]: item for item in body["results"]}
    assert results[target.id]["refreshed"] is True
    assert results[valid.id]["status_before"] == "valid"
    assert results[unavailable.id]["status_before"] == "refresh_unavailable"

    db_session.expire_all()
    from models.user import User as UserModel
    refreshed = db_session.query(UserModel).filter(UserModel.id == target.id).first()
    unchanged = db_session.query(UserModel).filter(UserModel.id == valid.id).first()
    assert refreshed.kakao_access_token == "bulk_refreshed_access"
    assert refreshed.kakao_refresh_token == "bulk_refreshed_refresh"
    assert unchanged.kakao_access_token == "valid_bulk_access"


def test_bulk_refresh_kakao_tokens_reports_failure(
    client, kakao_mock, make_user
):
    """일괄 갱신 실패는 전체 요청을 깨지 않고 사용자별 실패로 반환한다."""
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    target, _ = make_user(
        UserRole.SECRETARY,
        email="bulk-refresh-fail@example.com",
        kakao_id="bulk-refresh-fail",
        kakao_access_token="expired_access",
        kakao_refresh_token="invalid_refresh",
        kakao_token_expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )

    kakao_mock.token_fail(status_code=401, msg="invalid refresh token")

    res = client.post("/api/kakao/tokens/refresh", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["summary"] == {
        "total": 1,
        "refreshed": 0,
        "skipped": 0,
        "failed": 1,
    }
    assert body["results"][0]["user_id"] == target.id
    assert body["results"][0]["status_after"] == "invalid"
    assert "HTTP 401" in body["results"][0]["error"]


def test_bulk_sync_kakao_login_uuid_updates_identity_status(
    client, db_session, kakao_mock, make_user
):
    """기존 OAuth 사용자의 로그인 uuid를 다시 조회해 일치 확인 상태를 채운다."""
    _, headers = make_user(UserRole.TEAM_LEADER)
    target, _ = make_user(
        UserRole.REVIEWER,
        email="sync-login-uuid@example.com",
        kakao_id="77777",
        kakao_uuid="sync-uuid-77777",
        kakao_access_token="valid_access_for_user_info",
        kakao_refresh_token="valid_refresh_for_user_info",
        kakao_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
    )

    kakao_mock.user_info_ok(kakao_id="77777", uuid="sync-uuid-77777")

    res = client.post("/api/kakao/login-uuids/sync", headers=headers)

    assert res.status_code == 200
    body = res.json()
    assert body["summary"]["synced"] == 1
    assert body["summary"]["matched"] == 1

    db_session.expire_all()
    from models.user import User as UserModel

    refreshed = db_session.query(UserModel).filter(UserModel.id == target.id).first()
    assert refreshed.kakao_login_uuid == "sync-uuid-77777"


def test_send_message_to_self_requires_result_code_zero(kakao_mock):
    """나에게 보내기 HTTP 200이어도 result_code가 0이 아니면 실패로 취급한다."""
    from services.kakao import send_message_to_self

    kakao_mock.memo_send_ok(result_code=-1)

    result = asyncio.run(send_message_to_self(
        access_token="access",
        title="테스트",
        description="본문",
        link_url="http://localhost:3000/inquiries",
    ))

    assert result["error"] == "unexpected_result"
    assert result["detail"]["result_code"] == -1


def test_diagnose_user_scopes_reports_invalid_refresh_token(
    client, kakao_mock, make_user
):
    """사용자 진단에서 refresh token 401을 500이 아닌 갱신 실패 상태로 노출한다."""
    _, headers = make_user(UserRole.TEAM_LEADER)
    target, _ = make_user(
        UserRole.SECRETARY,
        email="token-invalid@example.com",
        kakao_id="token-invalid",
        kakao_access_token="expired_access",
        kakao_refresh_token="invalid_refresh",
        kakao_token_expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )

    kakao_mock.token_fail(status_code=401, msg="invalid refresh token")

    res = client.get(f"/api/kakao/user/{target.id}/scopes", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["kakao_token_status"] == "invalid"
    assert body["token_expired"] is True
    assert "토큰 갱신 실패" in body["error"]
