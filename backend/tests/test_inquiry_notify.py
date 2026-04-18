"""services.inquiry_notify.notify_inquiry_reply 회귀 테스트.

카카오 외부 호출은 monkeypatch로 차단하고, 수신자/발신자 조건 분기와
NotificationLog 기록이 의도대로 동작하는지 검증한다.
"""

import pytest

from models.inquiry import Inquiry, InquiryStatus
from models.notification_log import NotificationLog
from models.user import UserRole
from services import inquiry_notify


def _make_inquiry(db_session, submitter_id, building_id=None):
    inquiry = Inquiry(
        building_id=building_id or 1,
        mgmt_no="INQ-001",
        phase="preliminary",
        submitter_id=submitter_id,
        submitter_name="검토위원A",
        content="문의 내용",
        reply="답변 내용",
        status=InquiryStatus.COMPLETED,
    )
    db_session.add(inquiry)
    db_session.commit()
    db_session.refresh(inquiry)
    return inquiry


@pytest.mark.asyncio
async def test_skips_when_recipient_has_no_kakao_uuid(db_session, make_user):
    sender, _ = make_user(UserRole.CHIEF_SECRETARY, name="발신자")
    recipient, _ = make_user(UserRole.REVIEWER, name="수신자")  # kakao_uuid 없음
    inquiry = _make_inquiry(db_session, submitter_id=recipient.id)

    result = await inquiry_notify.notify_inquiry_reply(
        db_session, sender, inquiry, phase_changed=False
    )
    db_session.commit()

    assert result is False
    logs = db_session.query(NotificationLog).all()
    assert len(logs) == 1
    assert logs[0].is_sent is False
    assert logs[0].recipient_id == recipient.id
    assert logs[0].template_type == "inquiry_reply"
    assert "매칭" in (logs[0].error_message or "")


@pytest.mark.asyncio
async def test_message_includes_sender_name_as_manager(db_session, make_user):
    """메시지 본문 첫 줄에 '담당간사 : {발신자 이름}'이 기입된다."""
    sender, _ = make_user(UserRole.CHIEF_SECRETARY, name="김총괄")
    recipient, _ = make_user(UserRole.REVIEWER, name="이공우")
    inquiry = _make_inquiry(db_session, submitter_id=recipient.id)

    # kakao_uuid가 없어도 메시지 구성은 수행되고 NotificationLog에 message 가 기록됨
    await inquiry_notify.notify_inquiry_reply(
        db_session, sender, inquiry, phase_changed=True
    )
    db_session.commit()

    log = db_session.query(NotificationLog).first()
    assert log is not None
    assert log.message is not None
    assert "담당간사 : 김총괄" in log.message
    assert "답변:" in log.message
    assert "검토 단계가 변경" in log.message


@pytest.mark.asyncio
async def test_no_log_when_submitter_id_missing(db_session, make_user):
    sender, _ = make_user(UserRole.CHIEF_SECRETARY, name="발신자")
    # historical 데이터: submitter_id가 NULL인 문의
    inquiry = _make_inquiry(db_session, submitter_id=None)

    result = await inquiry_notify.notify_inquiry_reply(
        db_session, sender, inquiry, phase_changed=False
    )
    db_session.commit()

    assert result is False
    # 작성자 식별 불가 시에는 로그도 남기지 않는다
    assert db_session.query(NotificationLog).count() == 0
