"""재제출 요청 라우터

검토위원이 배포받은 설계도서로 검토를 진행할 수 없을 때 재제출을 요청한다.
검토위원의 등록은 사유 접수까지만이며 건물 상태를 바꾸지 않는다. 사유를 확인한
간사가 요청 화면에서 다음을 실행한다 (PATCH /{id}).
  - rollback_phase: current_phase 를 접수 직전 단계로 되돌림 (RESUBMIT 트리거)
  - clear_due_date: 해당 검토 단계의 검토서 요청 예정일 삭제

요청 사유는 팀장·총괄간사·조별간사·관리원이 별도 메뉴에서 확인하며,
간사 이상은 회신·처리 상태·단계 되돌리기·예정일 삭제를 수행할 수 있다.
"""

from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from database import get_db
from models.building import Building
from models.resubmission_request import ResubmissionRequest, ResubmissionStatus
from models.review_stage import PhaseType, ReviewStage
from models.reviewer import Reviewer
from models.user import User, UserRole
from routers.auth import get_current_user, require_roles
from services.audit import log_action
from services.phase_transition import (
    InvalidPhaseTransition,
    next_phase_for,
    transition_phase,
)
from services.resubmission_notify import notify_resubmission_rejected

router = APIRouter()

# 접수 상태(building.current_phase) → 해당 검토 단계(review_stages.phase)
RECEIVED_TO_STAGE_PHASE: dict[str, str] = {
    "doc_received": "preliminary",
    "supplement_1_received": "supplement_1",
    "supplement_2_received": "supplement_2",
    "supplement_3_received": "supplement_3",
    "supplement_4_received": "supplement_4",
    "supplement_5_received": "supplement_5",
}

MAX_REASON_LENGTH = 2000

# 안내 메시지용 단계 한글 라벨
_PHASE_LABELS: dict[str, str] = {
    "assigned": "배정완료",
    "doc_received": "예비도서 접수",
    "preliminary": "예비검토서 제출",
    "supplement_1_received": "보완도서(1차) 접수",
    "supplement_1": "보완검토서(1차) 제출",
    "supplement_2_received": "보완도서(2차) 접수",
    "supplement_2": "보완검토서(2차) 제출",
    "supplement_3_received": "보완도서(3차) 접수",
    "supplement_3": "보완검토서(3차) 제출",
    "supplement_4_received": "보완도서(4차) 접수",
    "supplement_4": "보완검토서(4차) 제출",
    "supplement_5_received": "보완도서(5차) 접수",
    "supplement_5": "보완검토서(5차) 제출",
}


# --- Pydantic 스키마 ---

class ResubmissionCreateRequest(BaseModel):
    mgmt_no: str
    reason: str = Field(min_length=1, max_length=MAX_REASON_LENGTH)


class ResubmissionUpdateRequest(BaseModel):
    reply: str | None = Field(default=None, max_length=MAX_REASON_LENGTH)
    # 간사 처리 액션.
    #   complete — 요청 수용: 단계를 접수 직전으로 되돌리고 예정일 삭제
    #   reject   — 반려: 단계·예정일 유지, 요청자에게 현행 검토 카카오 알림
    # 미지정이면 회신 메모/상태만 저장한다.
    #   revert   — 대기로 복구: 처리완료로 되돌린 단계·삭제한 예정일을 원상복구
    action: Literal["complete", "reject", "revert"] | None = None
    # 상태만 직접 바꿀 때 사용 (예: 완료 건을 대기로 되돌리기)
    status: str | None = None


class ResubmissionItem(BaseModel):
    id: int
    building_id: int | None
    mgmt_no: str
    building_name: str | None = None
    phase: str
    from_phase: str | None
    to_phase: str | None
    current_phase: str | None = None
    # 해당 검토 단계에 현재 남아 있는 요청 예정일 (간사가 삭제 여부를 판단)
    current_due_date: str | None = None
    # 간사가 지운 예정일 (삭제 전 값)
    cleared_due_date: str | None
    requester_id: int | None
    requester_name: str
    reviewer_group_no: int | None = None
    reason: str
    status: str
    reply: str | None
    re_received_at: str | None
    handled_by_name: str | None = None
    handled_at: str | None
    created_at: str
    updated_at: str


class ResubmissionListResponse(BaseModel):
    items: list[ResubmissionItem]
    total: int


# --- 헬퍼 ---

def _visibility_filter(current_user: User):
    """목록 가시성 필터. None 이면 전체 조회.

    조가 배정된 간사는 자기 조 검토위원이 담당하는 건물 또는 자기 조 검토위원이
    올린 요청만 본다. 관리번호/담당자 연결이 사후 보정될 수 있어 문의사항과 같은
    3중 조건(건물 id / 관리번호 / 작성자)을 사용한다.
    """
    if current_user.role in (
        UserRole.TEAM_LEADER,
        UserRole.CHIEF_SECRETARY,
        UserRole.MANAGER,
    ):
        return None
    if current_user.role == UserRole.SECRETARY:
        if current_user.group_no is None:
            return None
        same_group_reviewer_ids = (
            select(Reviewer.id).where(Reviewer.group_no == current_user.group_no)
        )
        same_group_reviewer_user_ids = (
            select(Reviewer.user_id).where(Reviewer.group_no == current_user.group_no)
        )
        same_group_building_ids = (
            select(Building.id).where(Building.reviewer_id.in_(same_group_reviewer_ids))
        )
        same_group_mgmt_nos = (
            select(Building.mgmt_no).where(
                Building.reviewer_id.in_(same_group_reviewer_ids)
            )
        )
        return or_(
            ResubmissionRequest.building_id.in_(same_group_building_ids),
            ResubmissionRequest.mgmt_no.in_(same_group_mgmt_nos),
            ResubmissionRequest.requester_id.in_(same_group_reviewer_user_ids),
        )
    return ResubmissionRequest.id.is_(None)


def _stage_of(db: Session, building_id: int | None, stage_phase: str):
    """요청 대상 검토 단계 stage. 없으면 None."""
    if building_id is None:
        return None
    try:
        phase = PhaseType(stage_phase)
    except ValueError:
        return None
    return (
        db.query(ReviewStage)
        .filter(
            ReviewStage.building_id == building_id,
            ReviewStage.phase == phase,
        )
        .first()
    )


def _to_item(
    req: ResubmissionRequest,
    *,
    building_name: str | None = None,
    current_phase: str | None = None,
    current_due_date: str | None = None,
    reviewer_group_no: int | None = None,
    handled_by_name: str | None = None,
) -> ResubmissionItem:
    return ResubmissionItem(
        id=req.id,
        building_id=req.building_id,
        mgmt_no=req.mgmt_no,
        building_name=building_name,
        phase=req.phase,
        from_phase=req.from_phase,
        to_phase=req.to_phase,
        current_phase=current_phase,
        current_due_date=current_due_date,
        cleared_due_date=req.cleared_due_date,
        requester_id=req.requester_id,
        requester_name=req.requester_name,
        reviewer_group_no=reviewer_group_no,
        reason=req.reason,
        status=req.status.value,
        reply=req.reply,
        re_received_at=str(req.re_received_at) if req.re_received_at else None,
        handled_by_name=handled_by_name,
        handled_at=str(req.handled_at) if req.handled_at else None,
        created_at=str(req.created_at),
        updated_at=str(req.updated_at),
    )


# --- 엔드포인트 ---

@router.post("", status_code=201)
def create_resubmission_request(
    body: ResubmissionCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """재제출 요청 등록 — 해당 건물의 담당 검토자만 가능.

    담당 판정은 `Reviewer.user_id == current_user.id` 그리고
    `building.reviewer_id == reviewer.id` (동명이인 위험 때문에 이름 매칭 금지).
    도서 접수 상태에서만 요청할 수 있다. 등록은 사유 접수까지만 하고, 단계 되돌리기와
    검토서 요청 예정일 삭제는 사유를 확인한 간사가 요청 화면에서 실행한다
    (PATCH /{id} 의 rollback_phase / clear_due_date).
    """
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status_code=400, detail="재제출 사유를 입력해주세요")

    building = db.query(Building).filter(Building.mgmt_no == body.mgmt_no).first()
    if not building:
        raise HTTPException(status_code=404, detail="건축물을 찾을 수 없습니다")

    reviewer = db.query(Reviewer).filter(Reviewer.user_id == current_user.id).first()
    if reviewer is None or building.reviewer_id != reviewer.id:
        raise HTTPException(
            status_code=403,
            detail="담당 건물에만 재제출을 요청할 수 있습니다",
        )

    from_phase = building.current_phase or ""
    stage_phase = RECEIVED_TO_STAGE_PHASE.get(from_phase)
    if stage_phase is None:
        raise HTTPException(
            status_code=400,
            detail="도서 접수 상태에서만 재제출을 요청할 수 있습니다",
        )

    duplicated = (
        db.query(ResubmissionRequest.id)
        .filter(
            ResubmissionRequest.building_id == building.id,
            ResubmissionRequest.status == ResubmissionStatus.PENDING,
        )
        .first()
    )
    if duplicated:
        raise HTTPException(
            status_code=400,
            detail="이미 처리 대기 중인 재제출 요청이 있습니다",
        )

    ip = request.client.host if request.client and request.client.host else None

    # 단계와 예정일은 그대로 둔다. 사유를 확인한 간사가 요청 화면에서 처리한다.
    stage = _stage_of(db, building.id, stage_phase)
    current_due_date = (
        stage.report_due_date.isoformat() if stage and stage.report_due_date else None
    )

    req = ResubmissionRequest(
        building_id=building.id,
        mgmt_no=building.mgmt_no,
        phase=stage_phase,
        from_phase=from_phase,
        requester_id=current_user.id,
        requester_name=current_user.name,
        reason=reason,
    )
    db.add(req)
    db.flush()

    log_action(
        db,
        current_user.id,
        "resubmission_request",
        "building",
        building.id,
        after_data={
            "mgmt_no": building.mgmt_no,
            "current_phase": from_phase,
            "stage_phase": stage_phase,
            "report_due_date": current_due_date,
            "resubmission_request_id": req.id,
            "reason": reason,
        },
        ip_address=ip,
    )
    db.commit()
    db.refresh(req)
    return {
        "message": "재제출 요청이 등록되었습니다",
        "id": req.id,
        "phase": stage_phase,
        "current_phase": from_phase,
    }


@router.get("", response_model=ResubmissionListResponse)
def list_resubmission_requests(
    status_filter: str = Query("pending"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(
            UserRole.TEAM_LEADER,
            UserRole.CHIEF_SECRETARY,
            UserRole.SECRETARY,
            UserRole.MANAGER,
        )
    ),
):
    """재제출 요청 목록. 조가 배정된 간사는 자기 조 건만 노출."""
    query = db.query(ResubmissionRequest)

    visibility = _visibility_filter(current_user)
    if visibility is not None:
        query = query.filter(visibility)

    if status_filter == "pending":
        query = query.filter(ResubmissionRequest.status == ResubmissionStatus.PENDING)
    elif status_filter in ("closed", "completed"):
        # 처리완료와 반려는 모두 '처리 끝난 건'으로 함께 보여준다.
        query = query.filter(
            ResubmissionRequest.status.in_(
                [ResubmissionStatus.COMPLETED, ResubmissionStatus.REJECTED]
            )
        )

    total = query.count()
    items = (
        query.order_by(ResubmissionRequest.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )

    building_ids = {r.building_id for r in items if r.building_id is not None}
    building_map: dict[int, tuple[str | None, str | None, int | None]] = {}
    if building_ids:
        rows = (
            db.query(
                Building.id,
                Building.building_name,
                Building.current_phase,
                Reviewer.group_no,
            )
            .outerjoin(Reviewer, Reviewer.id == Building.reviewer_id)
            .filter(Building.id.in_(building_ids))
            .all()
        )
        building_map = {
            bid: (name, phase, group_no) for bid, name, phase, group_no in rows
        }

    # 요청별 대상 stage 의 현재 예정일 — 간사가 삭제 여부를 판단하는 값
    due_map: dict[tuple[int, str], str] = {}
    if building_ids:
        due_rows = (
            db.query(
                ReviewStage.building_id,
                ReviewStage.phase,
                ReviewStage.report_due_date,
            )
            .filter(
                ReviewStage.building_id.in_(building_ids),
                ReviewStage.report_due_date.isnot(None),
            )
            .all()
        )
        for bid, phase, due in due_rows:
            phase_value = phase.value if hasattr(phase, "value") else str(phase)
            due_map[(bid, phase_value)] = due.isoformat()

    handler_ids = {r.handled_by for r in items if r.handled_by is not None}
    handler_map: dict[int, str] = {}
    if handler_ids:
        handler_map = {
            uid: name
            for uid, name in db.query(User.id, User.name)
            .filter(User.id.in_(handler_ids))
            .all()
        }

    result = []
    for req in items:
        name, phase, group_no = building_map.get(req.building_id, (None, None, None))
        result.append(
            _to_item(
                req,
                building_name=name,
                current_phase=phase,
                current_due_date=due_map.get((req.building_id, req.phase)),
                reviewer_group_no=group_no,
                handled_by_name=(
                    handler_map.get(req.handled_by) if req.handled_by else None
                ),
            )
        )
    return ResubmissionListResponse(items=result, total=total)


@router.get("/my", response_model=ResubmissionListResponse)
def list_my_resubmission_requests(
    page: int = Query(1, ge=1),
    size: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """내가 등록한 재제출 요청 목록 — 내 검토 대상 화면의 버튼 상태 표시용."""
    query = db.query(ResubmissionRequest).filter(
        ResubmissionRequest.requester_id == current_user.id
    )
    total = query.count()
    items = (
        query.order_by(ResubmissionRequest.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    return ResubmissionListResponse(
        items=[_to_item(req) for req in items], total=total
    )


@router.patch("/{request_id}")
async def update_resubmission_request(
    request_id: int,
    body: ResubmissionUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(
            UserRole.TEAM_LEADER,
            UserRole.CHIEF_SECRETARY,
            UserRole.SECRETARY,
        )
    ),
):
    """재제출 요청 처리 (간사 이상).

    검토위원의 등록은 사유 접수까지이고, 실제 조치는 여기서 간사가 선택한다.
      action=complete — 요청 수용. 단계를 접수 직전으로 되돌리고 예정일을 지운다.
                        이미 처리된 항목은 건너뛰므로 반복 호출해도 안전하다.
      action=reject   — 반려. 단계·예정일은 그대로 두고 요청자에게
                        "현 도서로 검토 바랍니다" 카카오 알림을 보낸다.
    action 없이 reply/status 만 보내면 메모·상태만 저장한다.
    """
    req = (
        db.query(ResubmissionRequest)
        .filter(ResubmissionRequest.id == request_id)
        .first()
    )
    if not req:
        raise HTTPException(status_code=404, detail="재제출 요청을 찾을 수 없습니다")

    visibility = _visibility_filter(current_user)
    if visibility is not None:
        visible = (
            db.query(ResubmissionRequest.id)
            .filter(ResubmissionRequest.id == request_id, visibility)
            .first()
        )
        if not visible:
            raise HTTPException(status_code=403, detail="수정 권한이 없습니다")

    if body.reply is not None:
        req.reply = body.reply.strip() or None

    rolled_back_to = None
    cleared_due_date = None
    restored_phase = None
    restored_due_date = None
    target_status: ResubmissionStatus | None = None

    if body.action == "complete":
        # 요청 수용 — 단계 되돌리기 + 예정일 삭제. 이미 된 항목은 건너뛴다.
        building = (
            db.query(Building).filter(Building.id == req.building_id).first()
            if req.building_id
            else None
        )
        if building is None:
            raise HTTPException(status_code=404, detail="건축물을 찾을 수 없습니다")

        if not req.to_phase:
            target = next_phase_for("resubmit", building.current_phase)
            if target is None:
                raise HTTPException(
                    status_code=400,
                    detail="도서 접수 상태가 아니어서 이전 단계로 되돌릴 수 없습니다",
                )
            ip = request.client.host if request.client and request.client.host else None
            try:
                transition_phase(
                    db, building, to_phase=target, trigger="resubmit",
                    actor_user_id=current_user.id, ip_address=ip,
                    reason=f"resubmission_request:#{req.id}",
                )
            except InvalidPhaseTransition as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            # from_phase 는 등록 시점 값을 유지하고, 실제 되돌린 결과만 기록한다.
            req.to_phase = target
            rolled_back_to = target

        stage = _stage_of(db, req.building_id, req.phase)
        if stage is not None and stage.report_due_date is not None:
            cleared_due_date = stage.report_due_date.isoformat()
            stage.report_due_date = None
            req.cleared_due_date = cleared_due_date

        target_status = ResubmissionStatus.COMPLETED

    elif body.action == "reject":
        # 반려 — 단계·예정일은 그대로 두고 요청자에게 현행 검토 알림만 보낸다.
        target_status = ResubmissionStatus.REJECTED

    elif body.action == "revert":
        # 대기로 — 처리완료를 잘못 누른 경우의 복구. 단계와 예정일을 원래대로 돌린다.
        if req.to_phase:
            building = (
                db.query(Building).filter(Building.id == req.building_id).first()
                if req.building_id
                else None
            )
            if building is None:
                raise HTTPException(status_code=404, detail="건축물을 찾을 수 없습니다")
            # 처리완료 이후 단계가 또 바뀌었다면 임의 복원은 위험하므로 막는다.
            if building.current_phase != req.to_phase:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "처리완료 이후 단계가 변경되어 되돌릴 수 없습니다 "
                        f"(현재 {_PHASE_LABELS.get(building.current_phase or '', '-')})"
                    ),
                )
            if not req.from_phase:
                raise HTTPException(
                    status_code=400, detail="되돌릴 이전 단계 정보가 없습니다"
                )
            ip = request.client.host if request.client and request.client.host else None
            try:
                transition_phase(
                    db, building, to_phase=req.from_phase, trigger="manual",
                    actor_user_id=current_user.id, ip_address=ip,
                    reason=f"resubmission_revert:#{req.id}",
                )
            except InvalidPhaseTransition as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            restored_phase = req.from_phase
            req.to_phase = None

        if req.cleared_due_date:
            stage = _stage_of(db, req.building_id, req.phase)
            if stage is None:
                raise HTTPException(
                    status_code=400, detail="대상 검토 단계를 찾을 수 없습니다"
                )
            # 재접수 등으로 새 예정일이 잡혔으면 덮어쓰지 않는다.
            if stage.report_due_date is None:
                stage.report_due_date = date.fromisoformat(req.cleared_due_date)
                restored_due_date = req.cleared_due_date
            req.cleared_due_date = None

        target_status = ResubmissionStatus.PENDING

    elif body.status:
        try:
            target_status = ResubmissionStatus(body.status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="알 수 없는 상태값입니다") from exc

    if target_status is not None and target_status != req.status:
        req.status = target_status
        if target_status == ResubmissionStatus.PENDING:
            req.handled_by = None
            req.handled_at = None
        else:
            req.handled_by = current_user.id
            req.handled_at = datetime.now(timezone.utc)

    log_action(
        db,
        current_user.id,
        "resubmission_update",
        "resubmission_request",
        req.id,
        after_data={
            "mgmt_no": req.mgmt_no,
            "action": body.action,
            "status": req.status.value,
            "reply": req.reply,
            "rolled_back_to": rolled_back_to,
            "cleared_due_date": cleared_due_date,
            "restored_phase": restored_phase,
            "restored_due_date": restored_due_date,
        },
    )
    db.commit()
    db.refresh(req)

    notified = None
    if body.action == "reject":
        # 알림 실패가 반려 처리 자체를 되돌리지 않도록 커밋 이후에 보낸다.
        notified = await notify_resubmission_rejected(db, current_user, req)
        db.commit()

    done = []
    if rolled_back_to:
        done.append(
            f"단계를 {_PHASE_LABELS.get(rolled_back_to, rolled_back_to)}(으)로 되돌렸습니다"
        )
    if cleared_due_date:
        done.append(f"검토서 요청 예정일({cleared_due_date})을 삭제했습니다")
    if restored_phase:
        done.append(
            f"단계를 {_PHASE_LABELS.get(restored_phase, restored_phase)}(으)로 복구했습니다"
        )
    if restored_due_date:
        done.append(f"검토서 요청 예정일({restored_due_date})을 복구했습니다")
    if body.action == "revert" and not done:
        done.append("대기 상태로 되돌렸습니다")
    if body.action == "reject":
        done.append(
            "요청자에게 현행 검토 알림을 보냈습니다"
            if notified
            else "반려 처리했습니다 (카카오 알림 실패 — 알림 현황에서 확인해주세요)"
        )
    return {
        "message": " / ".join(done) if done else "업데이트 되었습니다",
        "rolled_back_to": rolled_back_to,
        "cleared_due_date": cleared_due_date,
        "restored_phase": restored_phase,
        "restored_due_date": restored_due_date,
        "notified": notified,
    }
