"""도서 접수/배포 라우터"""

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models.building import Building
from models.inappropriate_note import InappropriateNote
from models.review_stage import ReviewStage, PhaseType
from models.user import User, UserRole
from routers.auth import require_roles
from services.audit import log_action
from services.phase_transition import transition_phase
from services.s3_storage import delete_file

logger = logging.getLogger(__name__)

router = APIRouter()

# 단일 receive 호출에서 감사 로그 items에 보관할 최대 reset 건수.
# 이 값을 넘으면 잘라서 저장하고 overflow_count로 합계만 남긴다.
_RESET_AUDIT_ITEMS_CAP = 100


def _has_review_history(db: Session, stage: ReviewStage) -> bool:
    """검토서 제출 이력이 있는지 판정 (도서 재접수 시 초기화 여부 결정).

    필드 외에 InappropriateNote 자식 행이 남아 있어도 "이력 있음"으로 간주한다.
    """
    if (
        stage.report_submitted_at
        or stage.reviewer_name
        or stage.result
        or stage.review_opinion
        or stage.defect_type_1
        or stage.defect_type_2
        or stage.defect_type_3
        or stage.s3_file_key
        or stage.inappropriate_review_needed
        or stage.inappropriate_decision
        or stage.objection_filed
        or stage.objection_content
        or stage.objection_reason
    ):
        return True
    has_note = (
        db.query(InappropriateNote.id)
        .filter(InappropriateNote.stage_id == stage.id)
        .first()
    )
    return has_note is not None


def _reset_review_history(db: Session, stage: ReviewStage) -> dict:
    """ReviewStage의 검토서 제출 이력을 초기화한다.

    - S3 파일이 있으면 best-effort 삭제 (실패는 warning 로그 후 계속 진행)
    - 부적합 의견(InappropriateNote)도 하드 삭제 (검토서 사라지면 의미 상실)
    - 반환값은 호출 단위 감사 로그용 메타데이터
    """
    old_s3_key = stage.s3_file_key
    s3_deleted = False
    if old_s3_key:
        try:
            s3_deleted = delete_file(old_s3_key)
            if not s3_deleted:
                logger.warning(
                    "도서 재접수: S3 파일 삭제 실패 (없거나 권한 이슈) key=%s stage_id=%s",
                    old_s3_key, stage.id,
                )
        except Exception as exc:
            logger.warning(
                "도서 재접수: S3 파일 삭제 중 예외 key=%s stage_id=%s err=%s",
                old_s3_key, stage.id, exc,
            )
            s3_deleted = False

    notes_deleted = (
        db.query(InappropriateNote)
        .filter(InappropriateNote.stage_id == stage.id)
        .delete(synchronize_session=False)
    )

    stage.report_submitted_at = None
    stage.reviewer_name = None
    stage.result = None
    stage.review_opinion = None
    stage.defect_type_1 = None
    stage.defect_type_2 = None
    stage.defect_type_3 = None
    stage.s3_file_key = None
    stage.inappropriate_review_needed = False
    stage.inappropriate_decision = None
    stage.objection_filed = False
    stage.objection_content = None
    stage.objection_reason = None

    return {
        "stage_id": stage.id,
        "phase": stage.phase.value if stage.phase else None,
        "had_s3_key": bool(old_s3_key),
        "s3_deleted": s3_deleted,
        "notes_deleted": int(notes_deleted or 0),
    }

# 검토서 요청 예정일 기본 유예 기간(접수일 + DEFAULT_DUE_DAYS).
DEFAULT_DUE_DAYS = 14


class DocReceiveRequest(BaseModel):
    mgmt_nos: list[str]
    received_date: date | None = None  # 미입력 시 오늘
    # 검토서 요청 예정일 — 미입력 시 received_date + DEFAULT_DUE_DAYS로 자동 설정.
    # 한 번의 receive 호출 안에서는 모든 건물에 동일 예정일을 일괄 적용한다.
    report_due_date: date | None = None


class DocReceiveResponse(BaseModel):
    updated: int
    not_found: list[str]
    notifications: list[dict]


# 도서 접수 시 다음 단계를 결정:
#   key = 현재 current_phase
#   value = 접수 대상 stage phase (review_stages.phase)
_NEXT_RECEIVE_ROUND: dict[str | None, str] = {
    None: "preliminary",
    "": "preliminary",
    "assigned": "preliminary",                  # 배정완료 → 예비도서 접수
    "doc_received": "preliminary",              # 재접수
    "preliminary": "supplement_1",              # 예비 제출 후 → 1차 보완도서
    "supplement_1_received": "supplement_1",    # 1차 보완도서 재접수
    "supplement_1": "supplement_2",
    "supplement_2_received": "supplement_2",
    "supplement_2": "supplement_3",
    "supplement_3_received": "supplement_3",
    "supplement_3": "supplement_4",
    "supplement_4_received": "supplement_4",
    "supplement_4": "supplement_5",
    "supplement_5_received": "supplement_5",
    # "supplement_5" 이후는 더 이상 접수 불가
}

# stage phase → building.current_phase 접수 상태 문자열
_STAGE_TO_RECEIVED: dict[str, str] = {
    "preliminary": "doc_received",
    "supplement_1": "supplement_1_received",
    "supplement_2": "supplement_2_received",
    "supplement_3": "supplement_3_received",
    "supplement_4": "supplement_4_received",
    "supplement_5": "supplement_5_received",
}

_PHASE_ORDER: dict[str, int] = {
    "preliminary": 0,
    "supplement_1": 1,
    "supplement_2": 2,
    "supplement_3": 3,
    "supplement_4": 4,
    "supplement_5": 5,
}

_ROUND_KOREAN: dict[str, str] = {
    "preliminary": "예비",
    "supplement_1": "1차 보완",
    "supplement_2": "2차 보완",
    "supplement_3": "3차 보완",
    "supplement_4": "4차 보완",
    "supplement_5": "5차 보완",
}


@router.post("/receive", response_model=DocReceiveResponse)
def receive_documents(
    body: DocReceiveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """도서 접수 처리 (예비/보완 1~5차 자동 판별)

    각 건물의 현재 상태를 보고 예비도서인지 몇 차 보완도서인지 자동 결정.
    - review_stages에 해당 단계의 도서접수일 기록
    - 건물의 current_phase를 '_received' 상태로 업데이트
    - 검토위원 × 차수 조합별로 알림 데이터 생성
    """
    received = body.received_date or date.today()
    # 요청 예정일: 명시값 > 기본(접수일 + DEFAULT_DUE_DAYS)
    due_date = body.report_due_date or (received + timedelta(days=DEFAULT_DUE_DAYS))
    updated = 0
    not_found: list[str] = []
    # (검토자 이름, 접수 차수) → 관리번호 목록
    notif_key: dict[tuple[str, str], list[str]] = {}

    # 1. 건축물 일괄 조회
    building_map: dict[str, Building] = {}
    for i in range(0, len(body.mgmt_nos), 1000):
        chunk = body.mgmt_nos[i:i + 1000]
        buildings = db.query(Building).filter(Building.mgmt_no.in_(chunk)).all()
        for b in buildings:
            building_map[b.mgmt_no] = b

    # 2. 차수별로 stage 매핑 준비 — 건물별로 필요한 단계가 다를 수 있음
    # 먼저 각 건물의 접수 대상 phase를 계산
    target_phase_by_building: dict[int, str] = {}
    for b in building_map.values():
        phase = _NEXT_RECEIVE_ROUND.get(b.current_phase)
        if phase:
            target_phase_by_building[b.id] = phase

    # 3. 관련 review_stages 일괄 조회 (대상 phase 조합)
    existing_stages: dict[tuple[int, str], ReviewStage] = {}
    if target_phase_by_building:
        building_ids = list(target_phase_by_building.keys())
        phase_values = set(target_phase_by_building.values())
        # 한번에 전체 조회 후 dict로 인덱싱
        for i in range(0, len(building_ids), 1000):
            chunk = building_ids[i:i + 1000]
            stages = db.query(ReviewStage).filter(
                ReviewStage.building_id.in_(chunk),
                ReviewStage.phase.in_([PhaseType(p) for p in phase_values]),
            ).all()
            for s in stages:
                existing_stages[(s.building_id, s.phase.value)] = s

    # 4. 건물별 처리
    batch_count = 0
    skipped_final: list[str] = []
    # 재접수로 검토서 이력이 초기화된 건들 (감사 로그용)
    reset_records: list[dict] = []
    for mgmt_no in body.mgmt_nos:
        building = building_map.get(mgmt_no)
        if not building:
            not_found.append(mgmt_no)
            continue

        target_phase = target_phase_by_building.get(building.id)
        if not target_phase:
            # 5차 보완 이후 등 더 이상 접수 불가
            skipped_final.append(mgmt_no)
            continue

        # building.current_phase 업데이트 (매트릭스 RECEIVE).
        # 신규 등록 직후(phase 없음)에 도서접수가 들어오면 INITIAL("assigned")을
        # 먼저 통과시켜 매트릭스 일관성을 유지한다.
        if not building.current_phase:
            transition_phase(
                db, building, to_phase="assigned", trigger="initial",
                actor_user_id=current_user.id,
            )
        new_phase = _STAGE_TO_RECEIVED[target_phase]
        # 같은 _received로의 재접수는 from==to → no-op (로그 미생성).
        transition_phase(
            db, building, to_phase=new_phase, trigger="receive",
            actor_user_id=current_user.id,
        )

        key = (building.id, target_phase)
        stage = existing_stages.get(key)
        if stage:
            # 같은 단계 재접수: 검토서 제출 이력이 있으면 초기화
            if _has_review_history(db, stage):
                meta = _reset_review_history(db, stage)
                meta["mgmt_no"] = mgmt_no
                reset_records.append(meta)
            stage.doc_received_at = received
            stage.report_due_date = due_date
        else:
            db.add(ReviewStage(
                building_id=building.id,
                phase=PhaseType(target_phase),
                phase_order=_PHASE_ORDER[target_phase],
                doc_received_at=received,
                report_due_date=due_date,
            ))

        reviewer_name = building.assigned_reviewer_name
        if reviewer_name:
            k = (reviewer_name, target_phase)
            notif_key.setdefault(k, []).append(mgmt_no)

        updated += 1
        batch_count += 1
        if batch_count % 500 == 0:
            db.flush()

    # 호출 단위 감사 로그 (재접수로 이력이 초기화된 건이 있을 때만)
    if reset_records:
        # items 페이로드가 비대해지지 않도록 최대 _RESET_AUDIT_ITEMS_CAP 건까지만 남긴다.
        cap = _RESET_AUDIT_ITEMS_CAP
        items_for_log = reset_records[:cap]
        overflow_count = max(0, len(reset_records) - cap)
        log_action(
            db,
            current_user.id,
            "reset",
            "review_stage",
            None,
            after_data={
                "reason": "doc_re_received",
                "received_date": received.isoformat(),
                "reset_count": len(reset_records),
                "items": items_for_log,
                "overflow_count": overflow_count,
            },
        )

    db.commit()

    # 5. 알림 목록 생성 (검토자 × 차수 별로)
    due_date_str = due_date.strftime("%Y-%m-%d")
    notif_list = []
    for (reviewer, phase), mgmt_nos_list in notif_key.items():
        round_label = _ROUND_KOREAN.get(phase, phase)
        notif_list.append({
            "reviewer_name": reviewer,
            "count": len(mgmt_nos_list),
            "round": round_label,
            "phase": phase,
            "mgmt_nos": mgmt_nos_list,
            "report_due_date": due_date_str,
            "message": (
                f"{round_label}도서 {len(mgmt_nos_list)}건이 웹하드에 "
                f"업로드되었습니다. (관리번호 {', '.join(mgmt_nos_list)})\n"
                f"검토서 요청 예정일: {due_date_str}"
            ),
        })

    # 5차 이후 접수 불가 건은 not_found에 사유와 함께 포함
    for mgmt_no in skipped_final:
        not_found.append(f"{mgmt_no} (5차 보완 이후 접수 불가)")

    return DocReceiveResponse(
        updated=updated,
        not_found=not_found,
        notifications=notif_list,
    )


@router.post("/notify")
async def send_notifications(
    body: list[dict],
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """검토위원에게 카카오톡 알림 발송.

    - 검토위원 이름 → User 테이블에서 매칭 → user.kakao_uuid로 발송
    - 본인에게 발송하는 경우 "나에게 보내기" API 사용 (UUID 불필요)
    - kakao_uuid 미등록 사용자는 /kakao-match 페이지에서 매칭 안내
    """
    from datetime import datetime, timezone
    from models.notification_log import NotificationLog
    from services.kakao import (
        ensure_valid_token,
        send_message_to_friends,
        send_message_to_self,
    )

    # 발신자 카카오 토큰 유효성 체크 (자동 갱신 포함)
    try:
        access_token = await ensure_valid_token(current_user, db)
    except ValueError as exc:
        for notif in body:
            log = NotificationLog(
                recipient_id=None,
                channel="kakao",
                template_type="doc_received",
                title="검토도서 접수 알림",
                message=notif.get("message", ""),
                is_sent=False,
                error_message=f"발신자 카카오 토큰 오류: {exc}",
            )
            db.add(log)
        db.commit()
        return {
            "sent": 0,
            "failed": len(body),
            "total": len(body),
            "error": str(exc),
        }

    # 수신자 이름 → User 인덱스 생성 (한 번의 쿼리)
    names = [notif.get("reviewer_name", "") for notif in body if notif.get("reviewer_name")]
    user_by_name: dict[str, User] = {}
    if names:
        matched_users = db.query(User).filter(User.name.in_(names), User.is_active.is_(True)).all()
        user_by_name = {u.name: u for u in matched_users}

    sent = 0
    failed = 0

    def _log(is_sent: bool, message: str, recipient_id: int | None, channel: str, error: str | None):
        db.add(NotificationLog(
            recipient_id=recipient_id,
            channel=channel,
            template_type="doc_received",
            title="검토도서 접수 알림",
            message=message,
            is_sent=is_sent,
            sent_at=datetime.now(timezone.utc) if is_sent else None,
            error_message=error,
        ))

    for notif in body:
        reviewer_name = notif.get("reviewer_name", "")
        message = notif.get("message", "")

        user = user_by_name.get(reviewer_name)
        if not user:
            _log(False, message, None, "kakao",
                 f"'{reviewer_name}' 사용자가 등록되어 있지 않습니다")
            failed += 1
            continue

        # 본인에게는 "나에게 보내기" API 사용
        if user.id == current_user.id:
            try:
                result = await send_message_to_self(
                    access_token=access_token,
                    title="검토도서 접수 알림",
                    description=message,
                )
            except Exception as e:
                _log(False, message, user.id, "kakao_memo", f"발송 오류: {e}")
                failed += 1
                continue
            if "error" not in result:
                _log(True, message, user.id, "kakao_memo", None)
                sent += 1
            else:
                _log(False, message, user.id, "kakao_memo", str(result))
                failed += 1
            continue

        # 그 외에는 kakao_uuid 필요
        if not user.kakao_uuid:
            _log(False, message, user.id, "kakao",
                 f"'{reviewer_name}' 카카오 친구 매칭이 안 되어 있습니다 (카카오 매칭 페이지에서 매칭 필요)")
            failed += 1
            continue

        try:
            result = await send_message_to_friends(
                access_token=access_token,
                receiver_uuids=[user.kakao_uuid],
                title="검토도서 접수 알림",
                description=message,
            )
        except Exception as e:
            _log(False, message, user.id, "kakao", f"발송 오류: {e}")
            failed += 1
            continue

        if "error" not in result and user.kakao_uuid in (result.get("successful_receiver_uuids") or []):
            _log(True, message, user.id, "kakao", None)
            sent += 1
        else:
            _log(False, message, user.id, "kakao", str(result))
            failed += 1

    db.commit()
    return {"sent": sent, "failed": failed, "total": len(body)}
