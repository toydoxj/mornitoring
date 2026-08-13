"""도서 접수/배포 라우터"""

import logging
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session, joinedload

from database import get_db
from engines.deploy_batch import DEPLOY_BATCH_NUMBERS, deploy_batch_of
from engines.folder_distribution import distribute_by_folder_name
from models.building import Building
from models.deploy_batch_stage import DeployBatchStage
from models.inappropriate_note import InappropriateNote
from models.resubmission_request import ResubmissionRequest, ResubmissionStatus
from models.review_opinion_detail import ReviewOpinionDetail
from models.review_severity_summary import ReviewSeveritySummary
from models.review_stage import ReviewStage, PhaseType
from models.reviewer import Reviewer
from models.user import User, UserRole
from routers.auth import require_roles
from services.audit import log_action
from services.business_date import business_today
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
        or stage.severity_l0_count
        or stage.severity_l1_count
        or stage.severity_l2_count
        or stage.severity_l3_count
        or stage.severity_l4_count
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
    if has_note is not None:
        return True
    has_severity_summary = (
        db.query(ReviewSeveritySummary.id)
        .filter(ReviewSeveritySummary.stage_id == stage.id)
        .first()
    )
    if has_severity_summary is not None:
        return True
    has_opinion_detail = (
        db.query(ReviewOpinionDetail.id)
        .filter(ReviewOpinionDetail.stage_id == stage.id)
        .first()
    )
    return has_opinion_detail is not None


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
    severity_summaries_deleted = (
        db.query(ReviewSeveritySummary)
        .filter(ReviewSeveritySummary.stage_id == stage.id)
        .delete(synchronize_session=False)
    )
    opinion_details_deleted = (
        db.query(ReviewOpinionDetail)
        .filter(ReviewOpinionDetail.stage_id == stage.id)
        .delete(synchronize_session=False)
    )

    stage.report_submitted_at = None
    stage.reviewer_name = None
    stage.result = None
    stage.review_opinion = None
    stage.defect_type_1 = None
    stage.defect_type_2 = None
    stage.defect_type_3 = None
    stage.severity_l0_count = 0
    stage.severity_l1_count = 0
    stage.severity_l2_count = 0
    stage.severity_l3_count = 0
    stage.severity_l4_count = 0
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
        "severity_summaries_deleted": int(severity_summaries_deleted or 0),
        "opinion_details_deleted": int(opinion_details_deleted or 0),
    }

# 검토서 요청 예정일 기본 유예 기간(접수일 + DEFAULT_DUE_DAYS).
DEFAULT_DUE_DAYS = 14


class DocReceiveRequest(BaseModel):
    mgmt_nos: list[str]
    received_date: date | None = None  # 미입력 시 오늘
    # 검토서 요청 예정일 — 미입력 시 received_date + DEFAULT_DUE_DAYS로 자동 설정.
    # 한 번의 receive 호출 안에서는 모든 건물에 동일 예정일을 일괄 적용한다.
    report_due_date: date | None = None
    # true면 DB를 바꾸지 않고 보정 대상만 계산해 돌려준다 (접수 전 미리보기).
    dry_run: bool = False


class BatchStageAdjustment(BaseModel):
    """배포차수 기준 단계와 자동 판별이 어긋나 보정된 건."""

    mgmt_no: str
    deploy_batch: int
    expected_phase: str      # 차수 기준 단계 (제출 단계 값)
    calculated_phase: str    # 자동 판별된 접수 대상 단계 ("-"면 더 진행 불가)
    corrected_phase: str     # 보정 후 current_phase
    direction: Literal["ahead", "behind"]   # 기준 대비 앞서감 / 뒤처짐


class DocReceiveResponse(BaseModel):
    updated: int
    not_found: list[str]
    notifications: list[dict]
    # 배포차수 기준에 맞춰 보정된 건 (dry_run이면 보정 예정 목록)
    adjustments: list[BatchStageAdjustment] = []
    dry_run: bool = False


class BatchStageItem(BaseModel):
    batch_no: int
    phase: str | None       # None이면 기준 미설정 (보정 건너뜀)


class BatchStageListResponse(BaseModel):
    items: list[BatchStageItem]


class BatchStageUpdateRequest(BaseModel):
    items: list[BatchStageItem]


class FolderDistributionRequest(BaseModel):
    source_dir: str
    target_dir: str
    dry_run: bool = True
    operation: Literal["move", "copy"] = "move"
    overwrite: bool = False


class FolderDistributionDetail(BaseModel):
    status: str
    item_name: str
    mgmt_no: str | None
    reviewer_name: str | None
    reviewer_dir_name: str | None
    destination: str | None
    reason: str | None


class FolderDistributionResponse(BaseModel):
    classified: int
    skipped: int
    dry_run: bool
    operation: str
    overwrite: bool
    assignment_count: int
    unassigned_building_count: int
    classified_mgmt_nos: list[str]
    reviewer_counts: dict[str, int]
    details: list[FolderDistributionDetail]


class FolderAssignmentItem(BaseModel):
    reviewer_name: str
    group_no: int | None
    folder_name: str


class FolderAssignmentMapResponse(BaseModel):
    assignment: dict[str, FolderAssignmentItem]
    assignment_count: int
    unassigned_building_count: int


def _folder_name_for_reviewer(reviewer_name: str, group_no: int | None) -> str:
    group_label = f"{group_no}조" if group_no is not None else "조미정"
    return f"{group_label}-{reviewer_name}"


def _build_folder_distribution_assignment(
    db: Session,
) -> tuple[dict[str, FolderAssignmentItem], int]:
    """DB에 등록된 관리번호 -> 검토위원 분배 정보 매핑을 만든다."""
    buildings = (
        db.query(Building)
        .options(joinedload(Building.reviewer).joinedload(Reviewer.user))
        .all()
    )
    reviewers = (
        db.query(Reviewer)
        .options(joinedload(Reviewer.user))
        .all()
    )
    group_by_name = {
        r.user.name.strip(): r.group_no
        for r in reviewers
        if r.user and r.user.name and r.user.name.strip()
    }
    assignment: dict[str, FolderAssignmentItem] = {}
    unassigned = 0
    for building in buildings:
        reviewer_name = building.assigned_reviewer_name
        group_no = None
        if not reviewer_name and building.reviewer and building.reviewer.user:
            reviewer_name = building.reviewer.user.name
        if building.reviewer:
            group_no = building.reviewer.group_no
        if building.mgmt_no and reviewer_name and reviewer_name.strip():
            reviewer_name = reviewer_name.strip()
            if group_no is None:
                group_no = group_by_name.get(reviewer_name)
            assignment[building.mgmt_no] = FolderAssignmentItem(
                reviewer_name=reviewer_name,
                group_no=group_no,
                folder_name=_folder_name_for_reviewer(reviewer_name, group_no),
            )
        else:
            unassigned += 1
    return assignment, unassigned


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


# 기준 단계로 지정 가능한 값 (제출 단계). _PHASE_ORDER 키와 동일.
_BATCH_STAGE_PHASES = tuple(_PHASE_ORDER)

# 자동 판별이 불가능한 상태(5차 보완 제출 등)를 비교할 때 쓰는 가상 순서.
# 어떤 기준 단계보다도 크므로 항상 "앞서감"으로 판정된다.
_BEYOND_LAST_ORDER = max(_PHASE_ORDER.values()) + 1


def _load_batch_stage_map(db: Session) -> dict[int, str]:
    """배포차수 → 기준 단계. 설정이 없는 차수는 키가 없다."""
    rows = db.query(DeployBatchStage).all()
    return {row.batch_no: row.phase for row in rows}


def _resolve_receive_target(
    building: Building,
    batch_stage_map: dict[int, str],
) -> tuple[str | None, dict | None]:
    """건물의 접수 대상 단계와 배포차수 보정 정보를 계산한다.

    반환: (접수 대상 제출 단계, 보정 정보 또는 None)
    보정 정보가 있으면 호출부가 current_phase를 강제로 맞춰야 한다.

    규칙 — 기준 R, 자동 판별 C:
      C == R  정상 진행 (보정 없음)
      C <  R  기준보다 뒤처짐 → R의 접수 단계로 강제
      C >  R  기준보다 앞서감 → R의 제출 단계로 강제
    """
    calculated = _NEXT_RECEIVE_ROUND.get(building.current_phase)
    batch_no = deploy_batch_of(building.mgmt_no)
    expected = batch_stage_map.get(batch_no) if batch_no is not None else None

    # 기준 미설정이거나 관리번호가 정규 형식이 아니면 기존 동작 그대로.
    if expected is None:
        return calculated, None
    # 최종완료 건은 배포차수 보정 대상에서 제외한다.
    if building.current_phase == "completed" or building.final_result:
        return calculated, None

    calculated_order = (
        _PHASE_ORDER[calculated] if calculated is not None else _BEYOND_LAST_ORDER
    )
    expected_order = _PHASE_ORDER[expected]
    if calculated_order == expected_order:
        return calculated, None

    direction = "ahead" if calculated_order > expected_order else "behind"
    corrected_phase = expected if direction == "ahead" else _STAGE_TO_RECEIVED[expected]
    return expected, {
        "mgmt_no": building.mgmt_no,
        "deploy_batch": batch_no,
        "expected_phase": expected,
        "calculated_phase": calculated or "-",
        "corrected_phase": corrected_phase,
        "direction": direction,
    }


@router.get("/batch-stages", response_model=BatchStageListResponse)
def get_batch_stages(
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
    """배포차수별 기준 검토 단계 조회. 미설정 차수는 phase=None으로 채워 반환."""
    stage_map = _load_batch_stage_map(db)
    return BatchStageListResponse(items=[
        BatchStageItem(batch_no=batch_no, phase=stage_map.get(batch_no))
        for batch_no in DEPLOY_BATCH_NUMBERS
    ])


@router.put("/batch-stages", response_model=BatchStageListResponse)
def update_batch_stages(
    body: BatchStageUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.CHIEF_SECRETARY)),
):
    """배포차수별 기준 검토 단계 일괄 수정 (총괄간사 전용).

    phase=None 으로 보내면 해당 차수의 기준을 지운다(보정 건너뜀).
    """
    for item in body.items:
        if item.batch_no not in DEPLOY_BATCH_NUMBERS:
            raise HTTPException(status_code=400, detail="허용되지 않는 배포차수입니다")
        if item.phase is not None and item.phase not in _BATCH_STAGE_PHASES:
            raise HTTPException(status_code=400, detail="허용되지 않는 검토 단계입니다")

    existing = {row.batch_no: row for row in db.query(DeployBatchStage).all()}
    before = {batch_no: row.phase for batch_no, row in existing.items()}
    for item in body.items:
        row = existing.get(item.batch_no)
        if item.phase is None:
            if row is not None:
                db.delete(row)
            continue
        if row is None:
            db.add(DeployBatchStage(
                batch_no=item.batch_no,
                phase=item.phase,
                updated_by_user_id=current_user.id,
            ))
        else:
            row.phase = item.phase
            row.updated_by_user_id = current_user.id

    log_action(
        db,
        current_user.id,
        "update",
        "deploy_batch_stage",
        None,
        before_data={"stages": before},
        after_data={"stages": {item.batch_no: item.phase for item in body.items}},
    )
    db.commit()

    stage_map = _load_batch_stage_map(db)
    return BatchStageListResponse(items=[
        BatchStageItem(batch_no=batch_no, phase=stage_map.get(batch_no))
        for batch_no in DEPLOY_BATCH_NUMBERS
    ])


@router.get("/folder-assignment-map", response_model=FolderAssignmentMapResponse)
def get_folder_assignment_map(
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """브라우저 로컬 폴더 분배용 관리번호 -> 검토위원명 매핑을 반환한다."""
    assignment, unassigned = _build_folder_distribution_assignment(db)
    return FolderAssignmentMapResponse(
        assignment=assignment,
        assignment_count=len(assignment),
        unassigned_building_count=unassigned,
    )


@router.post("/folder-distribution", response_model=FolderDistributionResponse)
def distribute_folders(
    body: FolderDistributionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """로컬 폴더 항목을 DB의 관리번호/검토위원 매핑으로 검토위원별 분배한다."""
    assignment_items, unassigned = _build_folder_distribution_assignment(db)
    if not assignment_items:
        raise HTTPException(
            status_code=400,
            detail="DB에 검토위원이 배정된 관리번호가 없습니다",
        )
    assignment = {
        mgmt_no: item.folder_name
        for mgmt_no, item in assignment_items.items()
    }

    try:
        result = distribute_by_folder_name(
            body.source_dir,
            body.target_dir,
            assignment,
            dry_run=body.dry_run,
            operation=body.operation,
            overwrite=body.overwrite,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=f"폴더 접근 권한이 없습니다: {exc}") from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"폴더 처리 중 오류가 발생했습니다: {exc}") from exc

    result["unassigned_building_count"] = unassigned
    return result


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

    배포차수에 기준 단계가 설정돼 있으면 자동 판별 결과를 기준에 맞춰 보정한다.
    기준보다 뒤처졌으면 기준 단계의 접수 상태로, 앞서갔으면 기준 단계의 제출
    상태로 강제하며, 앞서간 건은 재접수로 보아 알림을 따로 묶는다.

    검토위원의 재제출 요청으로 되돌려진 건(대기중 + 아직 재접수 전)은 도서가
    다시 들어와도 검토서 요청 예정일을 비운 채 접수한다. 예정일은 사유를 확인한
    간사가 별도로 정한다.

    dry_run=true 면 DB를 바꾸지 않고 보정 대상만 계산해 돌려준다.
    """
    received = body.received_date or business_today()
    # 요청 예정일: 명시값 > 기본(접수일 + DEFAULT_DUE_DAYS)
    due_date = body.report_due_date or (received + timedelta(days=DEFAULT_DUE_DAYS))
    updated = 0
    not_found: list[str] = []
    # (검토자 이름, 접수 차수, 재접수 여부, 예정일 부여 여부) → 관리번호 목록
    notif_key: dict[tuple[str, str, bool, bool], list[str]] = {}

    # 1. 건축물 일괄 조회
    building_map: dict[str, Building] = {}
    for i in range(0, len(body.mgmt_nos), 1000):
        chunk = body.mgmt_nos[i:i + 1000]
        buildings = db.query(Building).filter(Building.mgmt_no.in_(chunk)).all()
        for b in buildings:
            building_map[b.mgmt_no] = b

    # 2. 차수별로 stage 매핑 준비 — 건물별로 필요한 단계가 다를 수 있음
    # 먼저 각 건물의 접수 대상 phase를 계산 (배포차수 기준 보정 포함)
    batch_stage_map = _load_batch_stage_map(db)
    target_phase_by_building: dict[int, str] = {}
    adjustment_by_building: dict[int, dict] = {}
    for b in building_map.values():
        phase, adjustment = _resolve_receive_target(b, batch_stage_map)
        if phase:
            target_phase_by_building[b.id] = phase
        if adjustment:
            adjustment_by_building[b.id] = adjustment

    # 미리보기: DB를 건드리지 않고 보정 대상만 돌려준다.
    if body.dry_run:
        adjustments = [
            adjustment_by_building[building_map[mgmt_no].id]
            for mgmt_no in body.mgmt_nos
            if mgmt_no in building_map
            and building_map[mgmt_no].id in adjustment_by_building
        ]
        missing = [m for m in body.mgmt_nos if m not in building_map]
        receivable = sum(
            1 for m in body.mgmt_nos
            if m in building_map and building_map[m].id in target_phase_by_building
        )
        db.rollback()
        return DocReceiveResponse(
            updated=receivable,
            not_found=missing,
            notifications=[],
            adjustments=[BatchStageAdjustment(**a) for a in adjustments],
            dry_run=True,
        )

    # 2-1. 재제출 요청으로 되돌려진 건 — 재접수해도 예정일을 비워 둔다.
    #      이미 한 번 재접수된 요청(re_received_at 기록됨)은 대상에서 빠진다.
    pending_resubmit_ids: set[int] = set()
    if building_map:
        rows = (
            db.query(ResubmissionRequest.building_id)
            .filter(
                ResubmissionRequest.building_id.in_(
                    [b.id for b in building_map.values()]
                ),
                ResubmissionRequest.status == ResubmissionStatus.PENDING,
                ResubmissionRequest.re_received_at.is_(None),
            )
            .all()
        )
        pending_resubmit_ids = {bid for (bid,) in rows if bid is not None}

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
    applied_adjustments: list[dict] = []
    # 재제출 요청분으로 접수돼 예정일을 비운 건들 (감사 로그 + 요청 표시용)
    resubmit_received: list[tuple[int, str]] = []
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

        adjustment = adjustment_by_building.get(building.id)
        # building.current_phase 업데이트 (매트릭스 RECEIVE).
        # 신규 등록 직후(phase 없음)에 도서접수가 들어오면 INITIAL("assigned")을
        # 먼저 통과시켜 매트릭스 일관성을 유지한다.
        if not building.current_phase:
            transition_phase(
                db, building, to_phase="assigned", trigger="initial",
                actor_user_id=current_user.id,
            )
        if adjustment:
            # 배포차수 기준으로 강제 보정 — 되돌리기·점프가 필요해 별도 트리거를 쓴다.
            transition_phase(
                db, building, to_phase=adjustment["corrected_phase"],
                trigger="batch_align",
                actor_user_id=current_user.id,
                reason=(
                    f"배포 {adjustment['deploy_batch']}차수 기준 "
                    f"{_ROUND_KOREAN.get(adjustment['expected_phase'], adjustment['expected_phase'])} "
                    f"(자동 판별: {_ROUND_KOREAN.get(adjustment['calculated_phase'], adjustment['calculated_phase'])})"
                ),
            )
            applied_adjustments.append(adjustment)
        else:
            new_phase = _STAGE_TO_RECEIVED[target_phase]
            # 같은 _received로의 재접수는 from==to → no-op (로그 미생성).
            transition_phase(
                db, building, to_phase=new_phase, trigger="receive",
                actor_user_id=current_user.id,
            )

        # 기준보다 앞서간 건은 제출 상태를 유지해야 하므로 검토서 이력을 지우지 않고
        # 접수일·요청 예정일만 갱신한다.
        keep_review_history = bool(adjustment) and adjustment["direction"] == "ahead"
        # 재제출 요청분 접수는 예정일을 비워 두고 간사가 따로 정한다.
        is_resubmit_receive = building.id in pending_resubmit_ids
        stage_due_date = None if is_resubmit_receive else due_date
        if is_resubmit_receive:
            resubmit_received.append((building.id, mgmt_no))

        key = (building.id, target_phase)
        stage = existing_stages.get(key)
        if stage:
            # 같은 단계 재접수: 검토서 제출 이력이 있으면 초기화
            if not keep_review_history and _has_review_history(db, stage):
                meta = _reset_review_history(db, stage)
                meta["mgmt_no"] = mgmt_no
                reset_records.append(meta)
            stage.doc_received_at = received
            stage.report_due_date = stage_due_date
        else:
            db.add(ReviewStage(
                building_id=building.id,
                phase=PhaseType(target_phase),
                phase_order=_PHASE_ORDER[target_phase],
                doc_received_at=received,
                report_due_date=stage_due_date,
            ))

        reviewer_name = building.assigned_reviewer_name
        if reviewer_name:
            k = (
                reviewer_name,
                target_phase,
                keep_review_history,
                stage_due_date is not None,
            )
            notif_key.setdefault(k, []).append(mgmt_no)

        updated += 1
        batch_count += 1
        if batch_count % 500 == 0:
            db.flush()

    # 재제출 요청분 접수 표시 — 요청 상태는 간사가 직접 닫으므로 시각만 기록한다.
    if resubmit_received:
        resubmit_building_ids = [bid for bid, _ in resubmit_received]
        db.query(ResubmissionRequest).filter(
            ResubmissionRequest.building_id.in_(resubmit_building_ids),
            ResubmissionRequest.status == ResubmissionStatus.PENDING,
            ResubmissionRequest.re_received_at.is_(None),
        ).update({ResubmissionRequest.re_received_at: sa_func.now()},
                 synchronize_session=False)
        log_action(
            db,
            current_user.id,
            "resubmission_re_receive",
            "building",
            None,
            after_data={
                "received_date": received.isoformat(),
                "report_due_date": None,
                "count": len(resubmit_received),
                "mgmt_nos": [m for _, m in resubmit_received[:_RESET_AUDIT_ITEMS_CAP]],
                "overflow_count": max(
                    0, len(resubmit_received) - _RESET_AUDIT_ITEMS_CAP
                ),
            },
        )

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

    # 5. 알림 목록 생성 (검토자 × 차수 × 재접수 여부 × 예정일 부여 여부 별로)
    due_date_str = due_date.strftime("%Y-%m-%d")
    notif_list = []
    for (reviewer, phase, is_re_receive, has_due), mgmt_nos_list in notif_key.items():
        round_label = _ROUND_KOREAN.get(phase, phase)
        # 기준보다 앞서가 있던 건은 이미 검토서를 낸 단계로 도서가 다시 들어온 것이라
        # 검토위원이 구분할 수 있도록 "재접수"로 표기한다.
        doc_label = f"{round_label}도서 재접수" if is_re_receive else f"{round_label}도서"
        # 예정일 안내는 신규 접수에만 넣는다.
        # - 재접수(이미 검토서를 낸 단계로 도서가 다시 들어온 건)
        # - 재제출 요청분(예정일을 비운 채 접수한 건)
        # 위 두 경우는 예정일을 따로 정하므로 메시지에서 뺀다.
        show_due = has_due and not is_re_receive
        message = (
            f"{doc_label} {len(mgmt_nos_list)}건이 웹하드에 "
            f"업로드되었습니다. (관리번호 {', '.join(mgmt_nos_list)})"
        )
        if show_due:
            message += f"\n검토서 요청 예정일: {due_date_str}"
        notif_list.append({
            "reviewer_name": reviewer,
            "count": len(mgmt_nos_list),
            "round": round_label,
            "phase": phase,
            "re_receive": is_re_receive,
            "mgmt_nos": mgmt_nos_list,
            "report_due_date": due_date_str if show_due else None,
            "message": message,
        })

    # 5차 이후 접수 불가 건은 not_found에 사유와 함께 포함
    for mgmt_no in skipped_final:
        not_found.append(f"{mgmt_no} (5차 보완 이후 접수 불가)")

    return DocReceiveResponse(
        updated=updated,
        not_found=not_found,
        notifications=notif_list,
        adjustments=[BatchStageAdjustment(**a) for a in applied_adjustments],
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
                sender_id=current_user.id,
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
            sender_id=current_user.id,
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
