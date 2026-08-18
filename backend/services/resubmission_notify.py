"""재제출 요청 처리 관련 카카오톡 알림.

간사가 요청을 반려(현행 도서로 검토 요청)할 때 요청자(검토위원)에게 알린다.
알림 실패가 요청 처리 저장을 막지 않도록 예외를 삼키고 성공 여부만 반환한다.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from config import settings
from logging_config import log_event
from models.notification_log import NotificationLog
from models.resubmission_request import ResubmissionRequest
from models.user import User
from services.kakao import ensure_valid_token, send_message_to_friends

RESUBMISSION_REJECTED_TEMPLATE = "resubmission_rejected"


def compose_rejected_message(req: ResubmissionRequest) -> tuple[str, str]:
    """반려 알림 제목/본문.

    `send_message_to_friends` 가 제목을 `[{title}]` 로 감싸므로 여기서는
    대괄호 없는 제목만 만든다.
    """
    title = f"재제출 요청 회신 - {req.mgmt_no}"
    lines = [f"관리번호 {req.mgmt_no}은 현 도서로 검토 바랍니다."]
    reply = (req.reply or "").strip()
    if reply:
        if len(reply) > 140:
            reply = reply[:137] + "..."
        lines.append(f"사유: {reply}")
    return title, "\n".join(lines)


async def notify_resubmission_rejected(
    db: Session,
    sender: User,
    req: ResubmissionRequest,
) -> bool:
    """요청자에게 '현 도서로 검토' 알림을 보낸다. 성공 여부 반환.

    실패/스킵 시에도 NotificationLog 를 남겨 운영에서 추적할 수 있게 한다.
    """
    if not req.requester_id:
        return False

    recipient = db.query(User).filter(User.id == req.requester_id).first()
    if recipient is None:
        return False

    title, message = compose_rejected_message(req)
    # 반려 내역은 건물 상세 화면에 남으므로 알림도 그 화면으로 보낸다.
    link_url = (
        f"{settings.frontend_base_url}/buildings/{req.building_id}?from=my-reviews"
        if req.building_id
        else f"{settings.frontend_base_url}/my-reviews"
    )

    def _write_log(*, is_sent: bool, error: str | None) -> None:
        db.add(NotificationLog(
            sender_id=sender.id,
            recipient_id=recipient.id,
            channel="kakao",
            template_type=RESUBMISSION_REJECTED_TEMPLATE,
            title=title,
            message=message,
            related_building_id=req.building_id,
            is_sent=is_sent,
            sent_at=datetime.now(timezone.utc) if is_sent else None,
            error_message=error,
        ))

    if not recipient.kakao_uuid:
        _write_log(is_sent=False, error="kakao 매칭 미완료")
        return False

    try:
        access_token = await ensure_valid_token(sender, db)
    except ValueError as exc:
        _write_log(is_sent=False, error=f"발신자 토큰 없음: {exc}")
        log_event(
            "warning", "resubmission_reject_notify_sender_token_missing",
            request_id=req.id, sender_id=sender.id,
        )
        return False
    except Exception as exc:
        _write_log(is_sent=False, error=f"발신자 토큰 확인 예외: {exc}")
        log_event(
            "error", "resubmission_reject_notify_token_exception",
            request_id=req.id, sender_id=sender.id, reason=str(exc),
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
    except Exception as exc:  # 외부 호출 실패를 요청 처리와 분리
        _write_log(is_sent=False, error=f"API 예외: {exc}")
        log_event(
            "error", "resubmission_reject_notify_exception",
            request_id=req.id, reason=str(exc),
        )
        return False

    is_sent = recipient.kakao_uuid in set(result.get("successful_receiver_uuids", []))
    error = None
    if not is_sent:
        error = str(
            result.get("failure_info") or result.get("detail") or "발송 실패"
        )
        log_event(
            "error", "resubmission_reject_notify_failed",
            request_id=req.id, reason=error,
        )

    _write_log(is_sent=is_sent, error=error)
    return is_sent
