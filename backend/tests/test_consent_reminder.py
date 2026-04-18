"""카카오 동의 재안내 발송 회귀."""

from datetime import datetime, timedelta, timezone

from models.user import UserRole


def test_reviewer_cannot_send_consent_reminder(client, make_reviewer, make_user):
    _, _, headers_r = make_reviewer()
    target, _ = make_user(UserRole.REVIEWER)
    res = client.post(f"/api/users/{target.id}/send-consent-reminder", headers=headers_r)
    assert res.status_code == 403


def test_send_consent_reminder_unmatched_user_returns_manual(
    client, make_user
):
    _, headers_admin = make_user(UserRole.TEAM_LEADER)
    target, _ = make_user(UserRole.REVIEWER, email="unmatched-consent@example.com")
    # kakao_uuid 없음

    res = client.post(f"/api/users/{target.id}/send-consent-reminder", headers=headers_admin)
    assert res.status_code == 200
    body = res.json()
    assert body["delivery"] == "manual"
    assert "/login" in body["login_url"]


def test_send_consent_reminder_kakao_success(
    client, kakao_mock, make_user
):
    sender, headers = make_user(
        UserRole.TEAM_LEADER,
        kakao_id="100",
        kakao_access_token="sender_acc",
        kakao_refresh_token="sender_ref",
        kakao_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
    )
    target, _ = make_user(
        UserRole.REVIEWER,
        email="consent-target@example.com",
        kakao_uuid="consent-uuid-001",
    )

    kakao_mock.friend_send_ok(success_uuids=["consent-uuid-001"])

    res = client.post(f"/api/users/{target.id}/send-consent-reminder", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["delivery"] == "kakao"
    assert body["error"] is None
    assert "/login" in body["login_url"]


def test_send_consent_reminder_kakao_failure_falls_back_to_manual(
    client, kakao_mock, make_user
):
    sender, headers = make_user(
        UserRole.TEAM_LEADER,
        kakao_id="101",
        kakao_access_token="sender_acc_2",
        kakao_refresh_token="sender_ref_2",
        kakao_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
    )
    target, _ = make_user(
        UserRole.REVIEWER,
        email="fail-consent@example.com",
        kakao_uuid="fail-consent-uuid",
    )

    kakao_mock.friend_send_fail(status_code=400, msg="not a friend")

    res = client.post(f"/api/users/{target.id}/send-consent-reminder", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["delivery"] == "manual"
    assert body["error"]
