"""문의사항 관련 카카오톡 알림을 전송한다.

알림 실패는 inquiry 본체 저장과 독립적이어야 하므로 예외를 삼키고 결과만 반환한다.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from config import settings
from logging_config import log_event
from models.inquiry import Inquiry
from models.notification_log import NotificationLog
from models.reviewer import Reviewer
from models.user import User, UserRole
from services.kakao import ensure_valid_token, send_message_to_friends


INQUIRY_REPLY_TEMPLATE = "inquiry_reply"
INQUIRY_CREATED_TEMPLATE = "inquiry_created"


def _compose_message(inquiry: Inquiry, phase_changed: bool) -> tuple[str, str]:
    """문의 답변 알림 제목/본문 구성.

    `send_message_to_friends`가 제목을 `[{title}]` 로 한 번 감싸 출력하므로
    본 함수는 대괄호 없는 담백한 제목만 반환해 이중 감쌈을 피한다.
    """
    title = f"문의 답변 - {inquiry.mgmt_no}"
    reply = (inquiry.reply or "").strip() or "(답변 내용이 등록되었습니다)"
    if len(reply) > 140:
        reply = reply[:137] + "..."
    lines = [f"답변: {reply}"]
    if phase_changed:
        lines.append("※ 건물의 검토 단계가 변경되었습니다.")
    return title, "\n".join(lines)


def _compose_new_inquiry_message(inquiry: Inquiry) -> tuple[str, str]:
    """새 문의 접수 알림 제목/본문 구성."""
    title = f"새 문의 - {inquiry.mgmt_no}"
    content = (inquiry.content or "").strip() or "(문의 내용 없음)"
    if len(content) > 140:
        content = content[:137] + "..."
    return title, f"관리번호: {inquiry.mgmt_no}\n검토위원: {inquiry.submitter_name}\n문의: {content}"


async def notify_inquiry_reply(
    db: Session,
    sender: User,
    inquiry: Inquiry,
    *,
    phase_changed: bool = False,
) -> bool:
    """작성자에게 카카오톡 답변 완료 알림을 보낸다. 성공 여부 반환.

    실패/스킵 시에도 NotificationLog를 남겨 운영에서 추적 가능하다.
    """
    if not inquiry.submitter_id:
        # historical 데이터 등 작성자 식별 불가: 기록 없이 무시
        return False

    recipient = db.query(User).filter(User.id == inquiry.submitter_id).first()
    if recipient is None:
        return False

    title, message = _compose_message(inquiry, phase_changed)
    link_url = f"{settings.frontend_base_url}/my-inquiries"

    def _write_log(*, is_sent: bool, channel: str, error: str | None) -> None:
        db.add(NotificationLog(
            sender_id=sender.id,
            recipient_id=recipient.id,
            channel=channel,
            template_type=INQUIRY_REPLY_TEMPLATE,
            title=title,
            message=message,
            related_building_id=inquiry.building_id,
            is_sent=is_sent,
            sent_at=datetime.now(timezone.utc) if is_sent else None,
            error_message=error,
        ))

    if not recipient.kakao_uuid:
        _write_log(is_sent=False, channel="kakao", error="kakao 매칭 미완료")
        return False

    try:
        access_token = await ensure_valid_token(sender, db)
    except ValueError as exc:
        _write_log(is_sent=False, channel="kakao", error=f"발신자 토큰 없음: {exc}")
        log_event(
            "warning", "inquiry_reply_notify_sender_token_missing",
            inquiry_id=inquiry.id, sender_id=sender.id,
        )
        return False

    try:
        result = await send_message_to_friends(
            access_token=access_token,
            receiver_uuids=[recipient.kakao_uuid],
            title=title,
            description=message,
            link_url=link_url,
        )
    except Exception as exc:  # 외부 호출 실패를 inquiry 저장과 분리
        _write_log(is_sent=False, channel="kakao", error=f"API 예외: {exc}")
        log_event(
            "error", "inquiry_reply_notify_exception",
            inquiry_id=inquiry.id, reason=str(exc),
        )
        return False

    is_sent = recipient.kakao_uuid in set(result.get("successful_receiver_uuids", []))
    error = None
    if not is_sent:
        error = result.get("detail") or "발송 실패"
        log_event(
            "error", "inquiry_reply_notify_failed",
            inquiry_id=inquiry.id, reason=error,
        )

    _write_log(is_sent=is_sent, channel="kakao", error=error)
    return is_sent


async def notify_new_inquiry_to_group_secretaries(
    db: Session,
    *,
    inquiry: Inquiry,
    reviewer: Reviewer,
) -> int:
    """검토위원 새 문의를 작성자 카카오 계정에서 같은 조 간사에게 보낸다.

    카카오 친구 메시지 API를 사용하므로 작성자 토큰과 수신 간사의 kakao_uuid가
    필요하다. 성공 발송 수를 반환하며, 실패/스킵은 NotificationLog에 남긴다.
    """
    if reviewer.group_no is None:
        log_event(
            "warning", "new_inquiry_notify_reviewer_group_missing",
            inquiry_id=inquiry.id, reviewer_id=reviewer.id,
        )
        return 0

    sender = db.query(User).filter(User.id == reviewer.user_id).first()
    if sender is None:
        log_event(
            "error", "new_inquiry_notify_sender_missing",
            inquiry_id=inquiry.id, reviewer_id=reviewer.id,
        )
        return 0

    recipients = (
        db.query(User)
        .filter(
            User.role == UserRole.SECRETARY,
            User.group_no == reviewer.group_no,
            User.is_active.is_(True),
        )
        .all()
    )
    if not recipients:
        log_event(
            "warning", "new_inquiry_notify_secretary_missing",
            inquiry_id=inquiry.id, group_no=reviewer.group_no,
        )
        return 0

    title, message = _compose_new_inquiry_message(inquiry)
    link_url = f"{settings.frontend_base_url}/inquiries"
    sent_count = 0

    def _write_log(
        recipient: User,
        *,
        is_sent: bool,
        error: str | None,
    ) -> None:
        db.add(NotificationLog(
            sender_id=sender.id,
            recipient_id=recipient.id,
            channel="kakao",
            template_type=INQUIRY_CREATED_TEMPLATE,
            title=title,
            message=message,
            related_building_id=inquiry.building_id,
            is_sent=is_sent,
            sent_at=datetime.now(timezone.utc) if is_sent else None,
            error_message=error,
        ))

    for recipient in recipients:
        if not recipient.kakao_uuid:
            _write_log(
                recipient,
                is_sent=False,
                error="수신자 kakao 매칭 미완료",
            )

    sendable_recipients = [recipient for recipient in recipients if recipient.kakao_uuid]
    if not sendable_recipients:
        return 0

    try:
        access_token = await ensure_valid_token(sender, db)
    except ValueError as exc:
        for recipient in sendable_recipients:
            _write_log(
                recipient,
                is_sent=False,
                error=f"발신자 토큰 없음: {exc}",
            )
        log_event(
            "warning", "new_inquiry_notify_sender_token_missing",
            inquiry_id=inquiry.id, sender_id=sender.id,
        )
        return 0
    except Exception as exc:
        for recipient in sendable_recipients:
            _write_log(
                recipient,
                is_sent=False,
                error=f"발신자 토큰 확인 예외: {exc}",
            )
        log_event(
            "error", "new_inquiry_notify_token_exception",
            inquiry_id=inquiry.id, sender_id=sender.id, reason=str(exc),
        )
        return 0

    for recipient in recipients:
        if not recipient.kakao_uuid:
            continue

        try:
            result = await send_message_to_friends(
                access_token=access_token,
                receiver_uuids=[recipient.kakao_uuid],
                title=title,
                description=message,
                link_url=link_url,
            )
        except Exception as exc:  # 외부 호출 실패를 문의 저장과 분리
            _write_log(recipient, is_sent=False, error=f"API 예외: {exc}")
            log_event(
                "error", "new_inquiry_notify_exception",
                inquiry_id=inquiry.id, recipient_id=recipient.id, reason=str(exc),
            )
            continue

        if "error" in result:
            error = str(result.get("detail", "발송 실패"))
            _write_log(recipient, is_sent=False, error=error)
            log_event(
                "error", "new_inquiry_notify_failed",
                inquiry_id=inquiry.id, recipient_id=recipient.id, reason=error,
            )
            continue

        successful = set(result.get("successful_receiver_uuids", []))
        if recipient.kakao_uuid in successful:
            _write_log(recipient, is_sent=True, error=None)
            sent_count += 1
            continue

        error = str(result.get("failure_info") or result.get("detail") or "발송 실패")
        _write_log(recipient, is_sent=False, error=error)
        log_event(
            "error", "new_inquiry_notify_failed",
            inquiry_id=inquiry.id, recipient_id=recipient.id, reason=error,
        )

    return sent_count
