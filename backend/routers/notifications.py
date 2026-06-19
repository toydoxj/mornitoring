"""알림 로그 조회 + 카카오톡 발송 라우터"""

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.notification_log import NotificationLog
from models.user import User, UserRole
from routers.auth import get_current_user, require_roles
from logging_config import log_event
from services.kakao import ensure_valid_token, send_message_to_friends, send_message_to_self
from services.scope import (
    secretary_hidden_user_ids_subquery,
    visible_building_ids_subquery,
    visible_reviewer_user_ids,
)

router = APIRouter()

# pair(발신자/수신자) 당 일간 발송 제한
PAIR_DAILY_LIMIT = 20
# 1회 호출당 최대 수신자 수 (카카오 권장)
BATCH_SIZE = 5
PROGRAM_IMPROVEMENT_RECIPIENT_NAME = "정지훈"
PROGRAM_IMPROVEMENT_TEMPLATE = "program_improvement"


class NotificationResponse(BaseModel):
    id: int
    sender_id: int | None = None
    sender_name: str | None = None
    sender_email: str | None = None
    recipient_id: int | None = None
    recipient_name: str | None = None
    recipient_email: str | None = None
    channel: str
    template_type: str
    title: str
    message: str | None = None
    is_sent: bool
    sent_at: datetime | None = None
    retry_count: int
    error_message: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    total: int


class SendRequest(BaseModel):
    recipient_ids: list[int]
    title: str
    message: str
    template_type: str = "review_request"
    link_url: str | None = None
    related_building_id: int | None = None


class SendResultItem(BaseModel):
    recipient_id: int
    recipient_name: str
    is_sent: bool
    error: str | None = None


class SendResponse(BaseModel):
    sent_count: int
    failed_count: int
    results: list[SendResultItem]


class ProgramImprovementRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)


class ProgramImprovementResponse(BaseModel):
    message: str
    is_sent: bool
    recipient_id: int
    recipient_name: str
    error: str | None = None


def _notification_to_response(
    log: NotificationLog,
    users_by_id: dict[int, User],
) -> NotificationResponse:
    """알림 로그에 발신자/수신자 표시 정보를 붙여 응답한다."""
    sender = users_by_id.get(log.sender_id) if log.sender_id else None
    recipient = users_by_id.get(log.recipient_id) if log.recipient_id else None
    return NotificationResponse(
        id=log.id,
        sender_id=log.sender_id,
        sender_name=sender.name if sender else None,
        sender_email=sender.email if sender else None,
        recipient_id=log.recipient_id,
        recipient_name=recipient.name if recipient else None,
        recipient_email=recipient.email if recipient else None,
        channel=log.channel,
        template_type=log.template_type,
        title=log.title,
        message=log.message,
        is_sent=log.is_sent,
        sent_at=log.sent_at,
        retry_count=log.retry_count,
        error_message=log.error_message,
        created_at=log.created_at,
    )


def _notifications_to_response(
    db: Session,
    logs: list[NotificationLog],
    total: int,
) -> NotificationListResponse:
    user_ids = {
        uid
        for log in logs
        for uid in (log.sender_id, log.recipient_id)
        if uid is not None
    }
    users_by_id: dict[int, User] = {}
    if user_ids:
        users = db.query(User).filter(User.id.in_(user_ids)).all()
        users_by_id = {u.id: u for u in users}
    return NotificationListResponse(
        items=[_notification_to_response(log, users_by_id) for log in logs],
        total=total,
    )


def _find_program_improvement_recipient(db: Session) -> User | None:
    """프로그램 개선 요청 알림을 받을 운영 담당자를 찾는다."""
    return (
        db.query(User)
        .filter(
            User.name == PROGRAM_IMPROVEMENT_RECIPIENT_NAME,
            User.is_active.is_(True),
            User.role.in_([
                UserRole.CHIEF_SECRETARY,
                UserRole.TEAM_LEADER,
                UserRole.SECRETARY,
            ]),
        )
        .order_by(User.id.asc())
        .first()
    )


@router.post("/program-improvement", response_model=ProgramImprovementResponse)
async def send_program_improvement_request(
    body: ProgramImprovementRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """매뉴얼 화면의 프로그램 개선 요청을 정지훈 담당자에게 카카오톡으로 알린다.

    현재 로그인한 사용자의 카카오 토큰으로 정지훈 담당자에게 친구 메시지를 보낸다.
    즉, 요청자 계정에서 직접 보내는 방식이며 요청 본문은 NotificationLog에 함께 기록한다.
    """
    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="개선 요청 내용을 입력해주세요")

    recipient = _find_program_improvement_recipient(db)
    if recipient is None:
        log_event(
            "error",
            "program_improvement_recipient_missing",
            requester_id=current_user.id,
            recipient_name=PROGRAM_IMPROVEMENT_RECIPIENT_NAME,
        )
        raise HTTPException(
            status_code=404,
            detail=f"{PROGRAM_IMPROVEMENT_RECIPIENT_NAME} 수신자 계정을 찾을 수 없습니다",
        )

    title = "프로그램 개선 요청"
    message = (
        f"작성자: {current_user.name} ({current_user.email})\n"
        f"역할: {current_user.role.value}\n\n"
        f"요청 내용:\n{content}"
    )
    link_url = f"{settings.frontend_base_url.rstrip('/')}/reviewer-manual"

    is_sent = False
    error_message: str | None = None
    if not recipient.kakao_uuid:
        error_message = "수신자 카카오 친구 매칭이 안 되어 있습니다"
    else:
        try:
            access_token = await ensure_valid_token(current_user, db)
            result = await send_message_to_friends(
                access_token=access_token,
                receiver_uuids=[recipient.kakao_uuid],
                title=title,
                description=message,
                link_url=link_url,
            )
            successful = set(result.get("successful_receiver_uuids", []))
            is_sent = recipient.kakao_uuid in successful
            if not is_sent:
                failure_info = result.get("failure_info", []) or []
                failure_messages: list[str] = []
                for failure in failure_info:
                    receiver_uuids = failure.get("receiver_uuids", []) or []
                    if recipient.kakao_uuid in receiver_uuids:
                        failure_messages.append(failure.get("msg", "발송 실패"))
                error_message = (
                    "; ".join(failure_messages)
                    or str(result.get("detail") or result.get("error") or "발송 실패")
                )
        except ValueError as exc:
            error_message = f"발신자 카카오 토큰 사용 불가: {exc}"
        except Exception as exc:  # 외부 알림 실패가 요청 기록 자체를 막지 않게 한다.
            error_message = f"카카오 알림 예외: {exc}"
            log_event(
                "error",
                "program_improvement_notify_exception",
                requester_id=current_user.id,
                recipient_id=recipient.id,
                reason=str(exc),
            )

    db.add(NotificationLog(
        sender_id=current_user.id,
        recipient_id=recipient.id,
        channel="kakao",
        template_type=PROGRAM_IMPROVEMENT_TEMPLATE,
        title=title,
        message=message,
        related_building_id=None,
        is_sent=is_sent,
        sent_at=datetime.now(timezone.utc) if is_sent else None,
        error_message=error_message,
    ))
    db.commit()

    return ProgramImprovementResponse(
        message=(
            "프로그램 개선 요청이 카카오 알림으로 전송되었습니다"
            if is_sent
            else "프로그램 개선 요청은 기록되었지만 카카오 알림 발송에 실패했습니다"
        ),
        is_sent=is_sent,
        recipient_id=recipient.id,
        recipient_name=recipient.name,
        error=error_message,
    )


@router.post("/send", response_model=SendResponse)
async def send_notifications(
    body: SendRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY, UserRole.SECRETARY)
    ),
):
    """수신자 다중 선택 → 카카오톡 친구에게 메시지 발송 + NotificationLog 기록.

    - 수신자는 kakao_uuid가 매칭되어 있어야 함
    - 발신자(현재 사용자)는 카카오 로그인이 되어 있어야 함
    - pair 당 일간 20건 제한 체크
    - 5명씩 분할 호출
    """
    if not body.recipient_ids:
        raise HTTPException(status_code=400, detail="수신자를 선택해주세요")

    # 가시성 가드: 간사(조 배정)는 같은 조 검토위원에게만 발송 가능.
    # 위반 user_id 가 하나라도 섞이면 요청 전체 거부 (감사·재시도 명확성).
    visibility = visible_reviewer_user_ids(current_user)
    if visibility is not None:
        allowed_ids = {
            uid for (uid,) in db.query(User.id).filter(visibility).all()
        }
        # 본인에게 보내기는 항상 허용.
        allowed_ids.add(current_user.id)
        invalid_ids = [
            rid for rid in body.recipient_ids if rid not in allowed_ids
        ]
        if invalid_ids:
            raise HTTPException(
                status_code=403,
                detail={
                    "message": "조 권한 외 수신자가 포함되어 있습니다",
                    "invalid_recipient_ids": invalid_ids,
                },
            )

    try:
        access_token = await ensure_valid_token(current_user, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    recipients = (
        db.query(User).filter(User.id.in_(body.recipient_ids)).all()
    )
    recipients_by_id = {u.id: u for u in recipients}

    # pair 일간 카운터: 오늘 0시(UTC) 이후 동일 발신자/수신자 발송 수
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    pair_counts_rows = (
        db.query(NotificationLog.recipient_id, func.count(NotificationLog.id))
        .filter(
            NotificationLog.is_sent.is_(True),
            NotificationLog.channel == "kakao",
            NotificationLog.sender_id == current_user.id,
            NotificationLog.created_at >= today_start,
            NotificationLog.recipient_id.in_(body.recipient_ids),
        )
        .group_by(NotificationLog.recipient_id)
        .all()
    )
    pair_counts: dict[int, int] = {rid: cnt for rid, cnt in pair_counts_rows}

    # 발송 대상 분류
    valid_targets: list[tuple[int, str, str]] = []  # (recipient_id, name, kakao_uuid)
    self_target: tuple[int, str] | None = None  # (recipient_id, name) — 본인
    skipped_results: list[SendResultItem] = []

    for rid in body.recipient_ids:
        user = recipients_by_id.get(rid)
        if not user:
            skipped_results.append(SendResultItem(
                recipient_id=rid, recipient_name="(없음)",
                is_sent=False, error="수신자를 찾을 수 없습니다",
            ))
            continue
        # 본인은 "나에게 보내기" API로 별도 처리 (UUID 불필요)
        if rid == current_user.id:
            self_target = (rid, user.name)
            continue
        if not user.kakao_uuid:
            skipped_results.append(SendResultItem(
                recipient_id=rid, recipient_name=user.name,
                is_sent=False, error="카카오 친구 매칭이 안 되어 있습니다",
            ))
            continue
        if pair_counts.get(rid, 0) >= PAIR_DAILY_LIMIT:
            skipped_results.append(SendResultItem(
                recipient_id=rid, recipient_name=user.name,
                is_sent=False, error=f"일일 발송 제한({PAIR_DAILY_LIMIT}건) 초과",
            ))
            continue
        valid_targets.append((rid, user.name, user.kakao_uuid))

    sent_results: list[SendResultItem] = []

    # 본인에게 "나에게 보내기" 발송
    if self_target is not None:
        self_rid, self_name = self_target
        self_result = await send_message_to_self(
            access_token=access_token,
            title=body.title,
            description=body.message,
            link_url=body.link_url or "",
        )
        self_is_sent = "error" not in self_result
        self_error = None if self_is_sent else self_result.get("detail", "발송 실패")
        if not self_is_sent:
            log_event(
                "error", "kakao_message_self_failed",
                recipient_id=self_rid,
                reason=self_result.get("error", "unknown"),
            )
        db.add(NotificationLog(
            sender_id=current_user.id,
            recipient_id=self_rid,
            channel="kakao_memo",
            template_type=body.template_type,
            title=body.title,
            message=body.message,
            related_building_id=body.related_building_id,
            is_sent=self_is_sent,
            sent_at=datetime.now(timezone.utc) if self_is_sent else None,
            error_message=self_error,
        ))
        sent_results.append(SendResultItem(
            recipient_id=self_rid, recipient_name=self_name,
            is_sent=self_is_sent, error=self_error,
        ))

    # 5명씩 배치 호출
    for i in range(0, len(valid_targets), BATCH_SIZE):
        batch = valid_targets[i : i + BATCH_SIZE]
        uuids = [t[2] for t in batch]

        result = await send_message_to_friends(
            access_token=access_token,
            receiver_uuids=uuids,
            title=body.title,
            description=body.message,
            link_url=body.link_url or "",
        )

        success_uuids = set(result.get("successful_receiver_uuids", []))
        failure_info = result.get("failure_info", []) or []
        failure_msg_by_uuid: dict[str, str] = {}
        for f in failure_info:
            for u in f.get("receiver_uuids", []):
                failure_msg_by_uuid[u] = f.get("msg", "발송 실패")

        api_error_msg = result.get("detail") if "error" in result else None

        for rid, name, uuid in batch:
            is_sent = uuid in success_uuids
            error_msg: str | None = None
            if not is_sent:
                error_msg = (
                    failure_msg_by_uuid.get(uuid)
                    or api_error_msg
                    or "발송 실패"
                )
                log_event(
                    "error", "kakao_message_friend_failed",
                    recipient_id=rid, reason=error_msg,
                )

            log = NotificationLog(
                sender_id=current_user.id,
                recipient_id=rid,
                channel="kakao",
                template_type=body.template_type,
                title=body.title,
                message=body.message,
                related_building_id=body.related_building_id,
                is_sent=is_sent,
                sent_at=datetime.now(timezone.utc) if is_sent else None,
                error_message=error_msg,
            )
            db.add(log)
            sent_results.append(SendResultItem(
                recipient_id=rid, recipient_name=name,
                is_sent=is_sent, error=error_msg,
            ))

    db.commit()

    all_results = sent_results + skipped_results
    return SendResponse(
        sent_count=sum(1 for r in all_results if r.is_sent),
        failed_count=sum(1 for r in all_results if not r.is_sent),
        results=all_results,
    )


class ReviewReminderRequest(BaseModel):
    trigger: str  # "d_minus_1" | "overdue" | "within_3_days" | "within_n_days"
    dry_run: bool = False
    # 지정 시 해당 user_id 의 검토위원에게만 발송 (리마인드 페이지 체크박스 선택 발송)
    recipient_user_ids: list[int] | None = None
    # trigger == "within_n_days" 에서 사용 (기본 3). 0 이면 오늘까지 + 초과만.
    days_ahead: int | None = None


@router.post("/review-reminder")
async def send_review_reminder_endpoint(
    body: ReviewReminderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY, UserRole.SECRETARY)
    ),
):
    """검토위원 리마인드 알림 수동 발송 (팀장/총괄간사/간사).

    간사(조 배정)는 같은 조 검토위원 대상으로만 발송 가능.
    `recipient_user_ids` 가 가시성 외라면 403 으로 거부.

    trigger 값:
      - `within_n_days`: 예정일이 today + days_ahead 이하인 미제출(초과 포함). UI 기본값.
      - `overdue`: 예정일이 지났는데 미제출인 건.
      - `within_3_days` / `d_minus_1`: 하위 호환(cron 스크립트용).

    `dry_run=true` 이면 대상자 프리뷰만 반환하고 실제 발송·로그 기록은 하지 않는다.
    응답에는 오늘(UTC) 성공 발송된 리마인드 수 `today_sent_count` 가 포함된다.
    """
    from services.review_reminder import send_review_reminders

    if body.trigger not in {"d_minus_1", "overdue", "within_3_days", "within_n_days"}:
        raise HTTPException(status_code=400, detail="trigger 값이 올바르지 않습니다")
    if body.trigger == "within_n_days" and body.days_ahead is not None and body.days_ahead < 0:
        raise HTTPException(status_code=400, detail="days_ahead 는 0 이상이어야 합니다")

    # 명시적으로 받은 recipient_user_ids 가시성 검증
    if body.recipient_user_ids:
        visibility = visible_reviewer_user_ids(current_user)
        if visibility is not None:
            allowed_ids = {
                uid for (uid,) in db.query(User.id).filter(visibility).all()
            }
            allowed_ids.add(current_user.id)
            invalid_ids = [
                rid for rid in body.recipient_user_ids if rid not in allowed_ids
            ]
            if invalid_ids:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "message": "조 권한 외 수신자가 포함되어 있습니다",
                        "invalid_recipient_ids": invalid_ids,
                    },
                )

    return await send_review_reminders(
        db, current_user, body.trigger,
        dry_run=body.dry_run,
        recipient_user_ids=body.recipient_user_ids,
        days_ahead=body.days_ahead,
    )


@router.get("", response_model=NotificationListResponse)
def list_notifications(
    is_sent: bool | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY, UserRole.SECRETARY)
    ),
):
    """알림 로그 목록 조회 (팀장/총괄간사/간사).

    간사(조 배정)는 같은 조 검토위원에게 발송된 알림 + 같은 조 건물 관련
    알림만 노출 (recipient 또는 related_building 기준).
    """
    from sqlalchemy import or_

    query = db.query(NotificationLog)

    user_visibility = visible_reviewer_user_ids(current_user)
    building_visibility_ids = visible_building_ids_subquery(current_user)
    hidden_user_ids = secretary_hidden_user_ids_subquery(current_user)
    if user_visibility is not None or building_visibility_ids is not None:
        from sqlalchemy import select as _select
        # 가시 reviewer user_id 셋 + 가시 building_id 셋 중 하나라도 매치
        visible_user_ids_select = (
            _select(User.id).where(user_visibility)
            if user_visibility is not None else None
        )
        clauses = []
        if visible_user_ids_select is not None:
            clauses.append(NotificationLog.recipient_id.in_(visible_user_ids_select))
        if building_visibility_ids is not None:
            clauses.append(
                NotificationLog.related_building_id.in_(building_visibility_ids)
            )
        if clauses:
            query = query.filter(or_(*clauses))
    if hidden_user_ids is not None:
        query = query.filter(
            or_(
                NotificationLog.recipient_id.is_(None),
                NotificationLog.recipient_id.not_in(hidden_user_ids),
            )
        )

    if is_sent is not None:
        query = query.filter(NotificationLog.is_sent == is_sent)

    total = query.count()
    items = (
        query.order_by(NotificationLog.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    return _notifications_to_response(db, items, total)


@router.get("/my", response_model=NotificationListResponse)
def list_my_notifications(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """내가 받은 알림 목록 (모든 로그인 사용자)"""
    query = (
        db.query(NotificationLog)
        .filter(NotificationLog.recipient_id == current_user.id)
    )
    total = query.count()
    items = (
        query.order_by(NotificationLog.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    return _notifications_to_response(db, items, total)
