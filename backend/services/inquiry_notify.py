"""문의사항 답변 완료 시 검토자(작성자)에게 카카오톡 알림을 전송한다.

발신자(관리자)의 카카오 친구 메시지 API를 사용한다. 수신자가 카카오 매칭이 안 되어
있거나 발신자 토큰이 유효하지 않으면 조용히 스킵하고 NotificationLog에 이유를
남긴다. 본 함수는 inquiry 본체 저장과 독립적이어야 하므로 예외를 삼키고 결과만
반환한다.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from config import settings
from logging_config import log_event
from models.inquiry import Inquiry
from models.notification_log import NotificationLog
from models.user import User
from services.kakao import ensure_valid_token, send_message_to_friends


TEMPLATE_TYPE = "inquiry_reply"


def _compose_message(
    inquiry: Inquiry, sender: User, phase_changed: bool
) -> tuple[str, str]:
    """문의 답변 알림 제목/본문 구성.

    `send_message_to_friends`가 제목을 `[{title}]` 로 한 번 감싸 출력하므로
    본 함수는 대괄호 없는 담백한 제목만 반환해 이중 감쌈을 피한다.
    """
    title = f"문의 답변 - {inquiry.mgmt_no}"
    reply = (inquiry.reply or "").strip() or "(답변 내용이 등록되었습니다)"
    if len(reply) > 140:
        reply = reply[:137] + "..."
    lines = [
        f"담당간사 : {sender.name or '-'}",
        f"답변: {reply}",
    ]
    if phase_changed:
        lines.append("※ 건물의 검토 단계가 변경되었습니다.")
    return title, "\n".join(lines)


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

    title, message = _compose_message(inquiry, sender, phase_changed)
    link_url = f"{settings.frontend_base_url}/my-inquiries"

    def _write_log(*, is_sent: bool, channel: str, error: str | None) -> None:
        db.add(NotificationLog(
            recipient_id=recipient.id,
            channel=channel,
            template_type=TEMPLATE_TYPE,
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
