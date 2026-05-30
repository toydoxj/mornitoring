"""프로그램 개선 요청 카카오 알림 회귀 테스트."""

from datetime import datetime, timedelta, timezone

from models.notification_log import NotificationLog
from models.user import UserRole
from routers import notifications


def test_program_improvement_sent_by_current_reviewer(
    client,
    db_session,
    make_reviewer,
    make_user,
    monkeypatch,
):
    requester, _, headers = make_reviewer()
    recipient, _ = make_user(
        UserRole.CHIEF_SECRETARY,
        name="정지훈",
        email="jihun@example.com",
        kakao_uuid="jihun-kakao-uuid",
    )

    async def fake_ensure_valid_token(user, db):
        assert user.id == requester.id
        return "requester-access-token"

    async def fake_send_message_to_friends(
        access_token: str,
        receiver_uuids: list[str],
        title: str,
        description: str,
        link_url: str = "",
    ):
        assert access_token == "requester-access-token"
        assert receiver_uuids == ["jihun-kakao-uuid"]
        assert title == "프로그램 개선 요청"
        assert "작성자:" in description
        assert "업로드 버튼 위치 개선" in description
        return {"successful_receiver_uuids": ["jihun-kakao-uuid"], "failure_info": []}

    monkeypatch.setattr(notifications, "ensure_valid_token", fake_ensure_valid_token)
    monkeypatch.setattr(
        notifications, "send_message_to_friends", fake_send_message_to_friends
    )

    res = client.post(
        "/api/notifications/program-improvement",
        headers=headers,
        json={"content": "업로드 버튼 위치 개선이 필요합니다."},
    )

    assert res.status_code == 200
    body = res.json()
    assert body["is_sent"] is True
    assert body["recipient_id"] == recipient.id
    assert body["recipient_name"] == "정지훈"

    logs = db_session.query(NotificationLog).all()
    assert len(logs) == 1
    assert logs[0].sender_id == requester.id
    assert logs[0].recipient_id == recipient.id
    assert logs[0].channel == "kakao"
    assert logs[0].template_type == "program_improvement"
    assert logs[0].is_sent is True


def test_program_improvement_records_failure_when_recipient_not_matched(
    client,
    db_session,
    make_reviewer,
    make_user,
    monkeypatch,
):
    requester, _, headers = make_reviewer()
    recipient, _ = make_user(
        UserRole.CHIEF_SECRETARY,
        name="정지훈",
        email="jihun-unmatched@example.com",
        kakao_uuid=None,
        kakao_access_token="recipient-access-token",
        kakao_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("수신자 매칭이 없으면 카카오 API를 호출하지 않아야 합니다")

    monkeypatch.setattr(notifications, "ensure_valid_token", fail_if_called)
    monkeypatch.setattr(notifications, "send_message_to_friends", fail_if_called)

    res = client.post(
        "/api/notifications/program-improvement",
        headers=headers,
        json={"content": "목록 필터를 추가해주세요."},
    )

    assert res.status_code == 200
    body = res.json()
    assert body["is_sent"] is False
    assert "수신자 카카오 친구 매칭" in body["error"]

    logs = db_session.query(NotificationLog).all()
    assert len(logs) == 1
    assert logs[0].sender_id == requester.id
    assert logs[0].recipient_id == recipient.id
    assert logs[0].channel == "kakao"
    assert logs[0].is_sent is False
    assert "수신자 카카오 친구 매칭" in (logs[0].error_message or "")
