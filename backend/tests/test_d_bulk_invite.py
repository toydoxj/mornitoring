"""D-Bulk — 일괄 send-invite 회귀.

- bulk 엔드포인트 권한 (REVIEWER 차단)
- 카카오 미매칭 사용자만 → 모두 manual + setup_url 포함
- 카카오 매칭자 + 미매칭자 혼합 → 매칭자는 카카오 시도(테스트 환경에선 발신자 토큰 없어 manual fallback) + 미매칭은 manual
- 비활성/존재하지 않는 user_id → failed에 포함
- 빈 user_ids → 400
"""

from models.password_setup_token import PasswordSetupToken
from models.user import UserRole


def test_bulk_send_invite_requires_admin(client, make_reviewer):
    _, _, headers = make_reviewer()
    res = client.post(
        "/api/users/bulk-send-invite",
        headers=headers,
        json={"user_ids": [1]},
    )
    assert res.status_code == 403


def test_bulk_send_invite_empty_returns_400(client, make_user):
    _, headers = make_user(UserRole.TEAM_LEADER)
    res = client.post(
        "/api/users/bulk-send-invite", headers=headers, json={"user_ids": []}
    )
    assert res.status_code == 400


def test_bulk_send_invite_unmatched_users_all_manual(
    client, db_session, make_user
):
    _, headers = make_user(UserRole.TEAM_LEADER)
    a, _ = make_user(UserRole.REVIEWER, email="a@example.com")
    b, _ = make_user(UserRole.REVIEWER, email="b@example.com")
    c, _ = make_user(UserRole.REVIEWER, email="c@example.com")

    res = client.post(
        "/api/users/bulk-send-invite",
        headers=headers,
        json={"user_ids": [a.id, b.id, c.id]},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["summary"]["total"] == 3
    assert body["summary"]["kakao_sent"] == 0
    assert body["summary"]["manual"] == 3
    assert body["summary"]["failed"] == 0
    # 모두 manual이고 setup_url 포함
    for r in body["results"]:
        assert r["delivery"] == "manual"
        assert r["setup_url"] and "token=" in r["setup_url"]
        assert r["error"] is None

    # DB에 토큰 3건 발급 확인
    rows = db_session.query(PasswordSetupToken).all()
    assert len(rows) == 3


def test_bulk_send_invite_with_kakao_matched_falls_back_to_manual_when_sender_no_token(
    client, make_user
):
    """관리자가 카카오 토큰 미보유면 매칭 사용자도 manual fallback (sender_error 채워짐)."""
    sender, headers = make_user(UserRole.TEAM_LEADER)
    # sender의 kakao_access_token은 None
    matched_user, _ = make_user(
        UserRole.REVIEWER,
        email="matched@example.com",
        kakao_uuid="test-kakao-uuid-001",
    )

    res = client.post(
        "/api/users/bulk-send-invite",
        headers=headers,
        json={"user_ids": [matched_user.id]},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["summary"]["kakao_sent"] == 0
    assert body["summary"]["manual"] == 1
    assert body["summary"]["sender_error"]  # 사유 채워짐
    r = body["results"][0]
    assert r["delivery"] == "manual"
    assert r["setup_url"] and "token=" in r["setup_url"]


def test_bulk_send_invite_skips_unknown_or_inactive_users(
    client, db_session, make_user
):
    _, headers = make_user(UserRole.TEAM_LEADER)
    active, _ = make_user(UserRole.REVIEWER, email="active@example.com")
    inactive, _ = make_user(UserRole.REVIEWER, email="inactive@example.com")
    inactive.is_active = False
    db_session.commit()

    res = client.post(
        "/api/users/bulk-send-invite",
        headers=headers,
        json={"user_ids": [active.id, inactive.id, 999999]},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["summary"]["total"] == 3
    assert body["summary"]["manual"] == 1  # active만
    assert body["summary"]["failed"] == 2  # inactive + unknown

    # 결과에서 active는 setup_url 있고, 나머지는 error
    by_uid = {r["user_id"]: r for r in body["results"]}
    assert by_uid[active.id]["delivery"] == "manual"
    assert by_uid[active.id]["setup_url"]
    assert by_uid[inactive.id]["error"]
    assert by_uid[999999]["error"]
