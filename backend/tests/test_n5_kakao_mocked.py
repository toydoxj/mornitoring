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

import pytest

from models.kakao_link_session import KakaoLinkSession
from models.user import UserRole
from services.kakao import generate_oauth_state


# ===== 1. OAuth 콜백 — 기존 사용자 로그인 =====

def test_kakao_callback_existing_user_logs_in(client, db_session, kakao_mock, make_user):
    """kakao_id가 이미 매칭된 사용자가 카카오 OAuth로 다시 로그인."""
    user, _ = make_user(
        UserRole.REVIEWER,
        email="kakao-existing@example.com",
        kakao_id="98765",
    )

    kakao_mock.token_ok(access_token="new_access", refresh_token="new_refresh")
    kakao_mock.user_info_ok(kakao_id="98765", nickname="홍길동")

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


# ===== 2. OAuth 콜백 — need_link =====

def test_kakao_callback_unknown_kakao_id_returns_link_session(
    client, db_session, kakao_mock
):
    """매칭된 사용자 없는 kakao_id → need_link + link_session_id 응답."""
    kakao_mock.token_ok()
    kakao_mock.user_info_ok(kakao_id="99999", nickname="신규유저")

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
    kakao_mock.user_info_ok(kakao_id="55555")
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

    kakao_mock.friend_send_ok(success_uuids=["target-uuid-001"])

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
    kakao_mock.friend_send_ok(success_uuids=["refresh-uuid-001"])

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
