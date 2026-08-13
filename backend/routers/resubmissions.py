"""재제출 요청 라우터

검토위원이 배포받은 설계도서로 검토를 진행할 수 없을 때 재제출을 요청한다.
요청이 접수되면 다음이 한 트랜잭션으로 처리된다.
  1) building.current_phase 를 접수 직전 단계로 되돌린다 (RESUBMIT 트리거)
  2) 해당 접수 단계 stage 의 report_due_date 를 비운다
  3) 재제출 요청 레코드 + 감사 로그 + 단계 전환 로그를 남긴다

요청 사유는 팀장·총괄간사·조별간사·관리원이 별도 메뉴에서 확인하며,
간사 이상은 회신과 처리 상태를 남길 수 있다.
"""

from datetime import datetime, timezone

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


# --- Pydantic 스키마 ---

class ResubmissionCreateRequest(BaseModel):
    mgmt_no: str
    reason: str = Field(min_length=1, max_length=MAX_REASON_LENGTH)


class ResubmissionUpdateRequest(BaseModel):
    reply: str | None = Field(default=None, max_length=MAX_REASON_LENGTH)
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


def _to_item(
    req: ResubmissionRequest,
    *,
    building_name: str | None = None,
    current_phase: str | None = None,
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
    도서 접수 상태에서만 요청할 수 있고, 성공 시 단계가 접수 직전으로 되돌아가며
    해당 단계의 검토서 요청 예정일이 지워진다. 이후 도서가 다시 접수돼도 예정일은
    비워진 채로 유지되고(distribution.receive 참고), 간사가 사유를 확인한 뒤 정한다.
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

    to_phase = next_phase_for("resubmit", from_phase)
    ip = request.client.host if request.client and request.client.host else None

    try:
        transition_phase(
            db, building, to_phase=to_phase, trigger="resubmit",
            actor_user_id=current_user.id, ip_address=ip,
            reason=f"resubmission_request:{reason[:200]}",
        )
    except InvalidPhaseTransition as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 접수 단계 stage 의 검토서 요청 예정일 제거
    stage = (
        db.query(ReviewStage)
        .filter(
            ReviewStage.building_id == building.id,
            ReviewStage.phase == PhaseType(stage_phase),
        )
        .first()
    )
    cleared_due_date = None
    if stage and stage.report_due_date:
        cleared_due_date = stage.report_due_date.isoformat()
        stage.report_due_date = None

    req = ResubmissionRequest(
        building_id=building.id,
        mgmt_no=building.mgmt_no,
        phase=stage_phase,
        from_phase=from_phase,
        to_phase=to_phase,
        cleared_due_date=cleared_due_date,
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
        before_data={
            "current_phase": from_phase,
            "report_due_date": cleared_due_date,
        },
        after_data={
            "mgmt_no": building.mgmt_no,
            "current_phase": to_phase,
            "stage_phase": stage_phase,
            "report_due_date": None,
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
        "from_phase": from_phase,
        "to_phase": to_phase,
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
    elif status_filter == "completed":
        query = query.filter(ResubmissionRequest.status == ResubmissionStatus.COMPLETED)

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
def update_resubmission_request(
    request_id: int,
    body: ResubmissionUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(
            UserRole.TEAM_LEADER,
            UserRole.CHIEF_SECRETARY,
            UserRole.SECRETARY,
        )
    ),
):
    """재제출 요청 회신/처리 상태 변경 (간사 이상).

    단계 되돌리기는 등록 시점에 이미 처리됐으므로 여기서는 상태와 회신만 남긴다.
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

    if body.status:
        try:
            new_status = ResubmissionStatus(body.status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="알 수 없는 상태값입니다") from exc
        if new_status != req.status:
            req.status = new_status
            if new_status == ResubmissionStatus.COMPLETED:
                req.handled_by = current_user.id
                req.handled_at = datetime.now(timezone.utc)
            else:
                req.handled_by = None
                req.handled_at = None

    log_action(
        db,
        current_user.id,
        "resubmission_update",
        "resubmission_request",
        req.id,
        after_data={
            "mgmt_no": req.mgmt_no,
            "status": req.status.value,
            "reply": req.reply,
        },
    )
    db.commit()
    return {"message": "업데이트 되었습니다"}
