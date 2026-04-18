"""auth /link-account 흐름 회귀 테스트.

- 만료/존재하지 않는 link_session_id → 401
- 정상 session + 잘못된 비밀번호 → 401 (토큰만 가져도 로그인 불가)
"""

from datetime import datetime, timedelta, timezone

from models.kakao_link_session import KakaoLinkSession
from models.user import UserRole


def _create_link_session(
    db,
    *,
    expired: bool = False,
    consumed: bool = False,
    kakao_id: str = "kakao-test-123",
) -> KakaoLinkSession:
    now = datetime.now(timezone.utc)
    session = KakaoLinkSession(
        kakao_id=kakao_id,
        kakao_access_token="kakao-access-token-stub",
        kakao_refresh_token="kakao-refresh-token-stub",
        kakao_expires_in=21599,
        expires_at=(now - timedelta(minutes=5)) if expired else (now + timedelta(minutes=10)),
        consumed_at=now if consumed else None,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def test_link_account_with_expired_session_returns_401(client, db_session):
    session = _create_link_session(db_session, expired=True)
    res = client.post(
        "/api/auth/link-account",
        json={
            "email": "anyuser@example.com",
            "password": "anypassword",
            "link_session_id": session.id,
        },
    )
    assert res.status_code == 401


def test_link_account_with_wrong_password_returns_401_and_does_not_consume(
    client, db_session, make_user
):
    user, _ = make_user(UserRole.REVIEWER, email="link-test@example.com", password="correct123")
    session = _create_link_session(db_session)

    res = client.post(
        "/api/auth/link-account",
        json={
            "email": user.email,
            "password": "wrongpassword",
            "link_session_id": session.id,
        },
    )
    assert res.status_code == 401

    # 잘못된 비번 시도가 세션을 소모하면 안 됨 (DoS 방어)
    db_session.expire_all()
    refreshed = (
        db_session.query(KakaoLinkSession).filter(KakaoLinkSession.id == session.id).first()
    )
    assert refreshed is not None
    assert refreshed.consumed_at is None


def test_link_account_success_consumes_session_and_links_kakao(
    client, db_session, make_user
):
    user, _ = make_user(UserRole.REVIEWER, email="link-ok@example.com", password="correct123")
    session = _create_link_session(db_session, kakao_id="kakao-success-456")

    res = client.post(
        "/api/auth/link-account",
        json={
            "email": user.email,
            "password": "correct123",
            "link_session_id": session.id,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body.get("access_token")

    db_session.expire_all()
    refreshed_session = (
        db_session.query(KakaoLinkSession).filter(KakaoLinkSession.id == session.id).first()
    )
    assert refreshed_session is not None
    assert refreshed_session.consumed_at is not None

    # 두 번째 호출은 이미 consumed라 401
    res2 = client.post(
        "/api/auth/link-account",
        json={
            "email": user.email,
            "password": "correct123",
            "link_session_id": session.id,
        },
    )
    assert res2.status_code == 401
