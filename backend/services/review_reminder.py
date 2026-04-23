"""검토위원 리마인드 알림 서비스.

`review_stages.report_due_date` 를 기준으로 검토서 미제출 건을 찾아 담당 검토위원에게
카카오톡 리마인드를 보낸다. 두 가지 트리거를 지원:

- `d_minus_1`: 내일이 예정일인 미제출 건
- `overdue`: 예정일이 지났는데 아직 미제출인 건

수동 엔드포인트(관리자 버튼)와 cron 스크립트 양쪽에서 동일 함수를 재사용한다.
발송 실패는 NotificationLog 에 개별 사유로 기록되어 운영 화면에서 추적 가능.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from sqlalchemy.orm import Session

from config import settings
from logging_config import log_event
from models.building import Building
from models.notification_log import NotificationLog
from models.review_stage import ReviewStage
from models.reviewer import Reviewer
from models.user import User
from services.kakao import (
    ensure_valid_token,
    send_message_to_friends,
    send_message_to_self,
)


TriggerType = Literal["d_minus_1", "overdue", "within_3_days", "within_n_days"]
TEMPLATE_TYPE = "reminder"

_ROUND_LABEL: dict[str, str] = {
    "preliminary": "예비",
    "supplement_1": "1차 보완",
    "supplement_2": "2차 보완",
    "supplement_3": "3차 보완",
    "supplement_4": "4차 보완",
    "supplement_5": "5차 보완",
}


@dataclass
class ReminderTarget:
    reviewer_user_id: int
    reviewer_name: str
    kakao_uuid: str | None
    building_id: int
    mgmt_no: str
    phase: str
    report_due_date: date


def collect_targets(
    db: Session,
    trigger: TriggerType,
    today: date | None = None,
    *,
    days_ahead: int | None = None,
    sender: User | None = None,
) -> list[ReminderTarget]:
    """트리거 조건에 해당하는 검토서 미제출 건을 모은다.

    `days_ahead` 는 `trigger == "within_n_days"` 일 때 사용되며, 예정일이
    `today + days_ahead` 이하인 미제출 건을 반환한다 (과거 overdue 포함).
    지정되지 않으면 기본 3일.

    `sender` 가 주어지면 그 발신자의 가시성에 맞춰 대상 건을 좁힌다
    (간사 + group_no 인 경우 같은 조 검토위원만). cron/시스템 호출은
    sender=None 으로 두면 기존 동작(전체)을 유지.
    """
    from services.scope import building_visibility_filter

    anchor = today or date.today()
    base_query = (
        db.query(ReviewStage, Building, Reviewer, User)
        .join(Building, ReviewStage.building_id == Building.id)
        .join(Reviewer, Building.reviewer_id == Reviewer.id)
        .join(User, Reviewer.user_id == User.id)
        .filter(
            ReviewStage.report_submitted_at.is_(None),
            ReviewStage.report_due_date.isnot(None),
            User.is_active.is_(True),
        )
    )
    if sender is not None:
        visibility = building_visibility_filter(sender)
        if visibility is not None:
            base_query = base_query.filter(visibility)
    if trigger == "d_minus_1":
        base_query = base_query.filter(
            ReviewStage.report_due_date == anchor + timedelta(days=1)
        )
    elif trigger == "overdue":
        base_query = base_query.filter(ReviewStage.report_due_date < anchor)
    elif trigger == "within_3_days":
        # 하위 호환: within_n_days(3) 의 별칭
        base_query = base_query.filter(
            ReviewStage.report_due_date <= anchor + timedelta(days=3)
        )
    elif trigger == "within_n_days":
        n = 3 if days_ahead is None else max(0, days_ahead)
        base_query = base_query.filter(
            ReviewStage.report_due_date <= anchor + timedelta(days=n)
        )
    else:  # pragma: no cover - 타입 힌트로 방어되지만 안전망
        return []

    return [
        ReminderTarget(
            reviewer_user_id=user.id,
            reviewer_name=user.name,
            kakao_uuid=user.kakao_uuid,
            building_id=building.id,
            mgmt_no=building.mgmt_no,
            phase=stage.phase.value,
            report_due_date=stage.report_due_date,
        )
        for stage, building, reviewer, user in base_query.all()
    ]


def _delta_label(days_until: int) -> str:
    if days_until > 0:
        return f"D-{days_until}"
    if days_until == 0:
        return "D-day"
    return "초과"


def _compose_message(
    trigger: TriggerType,
    targets: list[ReminderTarget],
    today: date | None = None,
) -> tuple[str, str]:
    reference = today or date.today()
    if trigger == "d_minus_1":
        title = "검토서 요청 D-1 안내"
        lead = "검토서 제출 예정일이 내일입니다."
    elif trigger == "overdue":
        title = "검토서 요청 기한 초과"
        lead = "제출 예정일이 지났습니다. 빠른 검토서 제출을 부탁드립니다."
    else:  # within_3_days | within_n_days
        title = "검토서 제출 요청 안내"
        lead = "제출 예정일이 다가오거나 지난 검토서입니다. 빠른 제출을 부탁드립니다."

    lines = [lead]
    for t in targets:
        badge = _delta_label((t.report_due_date - reference).days)
        lines.append(
            f"- {t.mgmt_no} ({_ROUND_LABEL.get(t.phase, t.phase)}) "
            f"예정일 {t.report_due_date.strftime('%Y-%m-%d')} [{badge}]"
        )
    return title, "\n".join(lines)


def _group_by_reviewer(
    targets: list[ReminderTarget],
) -> dict[int, list[ReminderTarget]]:
    grouped: dict[int, list[ReminderTarget]] = {}
    for t in targets:
        grouped.setdefault(t.reviewer_user_id, []).append(t)
    return grouped


def _today_reminder_sent_count(db: Session) -> int:
    """오늘(UTC 자정 이후) 성공 발송된 reminder NotificationLog 수."""
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return (
        db.query(NotificationLog)
        .filter(
            NotificationLog.template_type == TEMPLATE_TYPE,
            NotificationLog.is_sent.is_(True),
            NotificationLog.created_at >= today_start,
        )
        .count()
    )


async def send_review_reminders(
    db: Session,
    sender: User,
    trigger: TriggerType,
    *,
    dry_run: bool = False,
    today: date | None = None,
    recipient_user_ids: list[int] | None = None,
    days_ahead: int | None = None,
) -> dict:
    """담당 검토위원별로 묶어 리마인드 발송. dry_run=True 면 대상만 반환.

    `recipient_user_ids` 가 주어지면 해당 검토위원에게만 발송 대상을 좁힌다.
    None 이면 조건에 맞는 모든 검토위원에게 발송.
    `days_ahead` 는 `trigger == "within_n_days"` 일 때 사용 (기본 3).

    응답 dict 에 `today_sent_count` 필드를 포함해 UI 에서 "오늘 발송 횟수" 를
    표시할 수 있도록 한다.
    """
    targets = collect_targets(db, trigger, today, days_ahead=days_ahead, sender=sender)
    if recipient_user_ids is not None:
        allow = set(recipient_user_ids)
        targets = [t for t in targets if t.reviewer_user_id in allow]
    grouped = _group_by_reviewer(targets)

    if dry_run or not targets:
        return {
            "trigger": trigger,
            "target_count": len(targets),
            "sent": 0,
            "failed": 0,
            "dry_run": dry_run,
            "today_sent_count": _today_reminder_sent_count(db),
            "by_reviewer": [
                {
                    "reviewer_user_id": uid,
                    "reviewer_name": ts[0].reviewer_name,
                    "kakao_matched": bool(ts[0].kakao_uuid),
                    "count": len(ts),
                    "mgmt_nos": [t.mgmt_no for t in ts],
                }
                for uid, ts in grouped.items()
            ],
        }

    # 실 발송 — 발신자(관리자) 카카오 토큰 확보
    try:
        access_token = await ensure_valid_token(sender, db)
    except ValueError as exc:
        for uid, ts in grouped.items():
            title, message = _compose_message(trigger, ts, today)
            db.add(NotificationLog(
                recipient_id=uid,
                channel="kakao",
                template_type=TEMPLATE_TYPE,
                title=title,
                message=message,
                is_sent=False,
                error_message=f"발신자 토큰 없음: {exc}",
            ))
        db.commit()
        log_event(
            "warning", "review_reminder_sender_token_missing",
            sender_id=sender.id, reason=str(exc),
        )
        return {
            "trigger": trigger,
            "target_count": len(targets),
            "sent": 0,
            "failed": len(grouped),
            "dry_run": False,
            "today_sent_count": _today_reminder_sent_count(db),
            "by_reviewer": [],
        }

    summary: list[dict] = []
    sent = 0
    failed = 0
    link_url = f"{settings.frontend_base_url}/my-reviews"

    for uid, ts in grouped.items():
        title, message = _compose_message(trigger, ts, today)
        head = ts[0]

        # 본인에게 쏘는 경우 '나에게 보내기'
        if uid == sender.id:
            try:
                result = await send_message_to_self(
                    access_token=access_token,
                    title=title,
                    description=message,
                    link_url=link_url,
                )
                is_sent = "error" not in result
                channel = "kakao_memo"
                err = None if is_sent else str(result)
            except Exception as exc:
                is_sent = False
                channel = "kakao_memo"
                err = f"API 예외: {exc}"
        elif not head.kakao_uuid:
            is_sent = False
            channel = "kakao"
            err = "kakao 매칭 미완료"
        else:
            try:
                result = await send_message_to_friends(
                    access_token=access_token,
                    receiver_uuids=[head.kakao_uuid],
                    title=title,
                    description=message,
                    link_url=link_url,
                )
                is_sent = head.kakao_uuid in set(
                    result.get("successful_receiver_uuids") or []
                )
                channel = "kakao"
                err = None if is_sent else (result.get("detail") or "발송 실패")
            except Exception as exc:
                is_sent = False
                channel = "kakao"
                err = f"API 예외: {exc}"

        db.add(NotificationLog(
            recipient_id=uid,
            channel=channel,
            template_type=TEMPLATE_TYPE,
            title=title,
            message=message,
            is_sent=is_sent,
            sent_at=datetime.now(timezone.utc) if is_sent else None,
            error_message=err,
        ))

        if is_sent:
            sent += 1
        else:
            failed += 1
            log_event(
                "error", "review_reminder_send_failed",
                recipient_id=uid, trigger=trigger, reason=err,
            )

        summary.append({
            "reviewer_user_id": uid,
            "reviewer_name": head.reviewer_name,
            "count": len(ts),
            "is_sent": is_sent,
            "error": err,
        })

    db.commit()
    return {
        "trigger": trigger,
        "target_count": len(targets),
        "sent": sent,
        "failed": failed,
        "dry_run": False,
        "today_sent_count": _today_reminder_sent_count(db),
        "by_reviewer": summary,
    }
