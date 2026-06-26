"""검토서 업로드/조회 라우터"""

import tempfile
import uuid
import zipfile
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased, selectinload
from starlette.background import BackgroundTask
from starlette.responses import FileResponse

from database import get_db
from dependencies import stream_upload_to_tempfile
from models.building import Building
from models.review_opinion_detail import ReviewOpinionDetail
from models.review_severity_summary import ReviewSeveritySummary
from models.review_stage import ReviewStage, PhaseType
from models.reviewer import Reviewer
from models.user import User, UserRole
from routers.auth import get_current_user, require_roles
from engines.review_validator import validate_review_file
from engines.review_extractor import extract_review_data
from engines.opinion_text import clean_opinion_detail_content
from engines.opinion_quality_analyzer import match_opinion_quality
from services.business_date import business_today


def _ensure_reviewer_can_access_building(
    building: Building, current_user: User, db: Session
) -> None:
    """REVIEWER는 본인 담당(reviewer_id 매칭) 건물만 접근 허용. 아니면 404로 거부.

    동명이인 위험을 피하기 위해 reviewer_id만 사용한다(`assigned_reviewer_name` 매칭 X).
    존재 자체를 노출하지 않기 위해 403이 아닌 404를 반환한다.
    """
    if current_user.role != UserRole.REVIEWER:
        return
    reviewer = db.query(Reviewer).filter(Reviewer.user_id == current_user.id).first()
    if reviewer is None or building.reviewer_id != reviewer.id:
        raise HTTPException(status_code=404, detail="건축물을 찾을 수 없습니다")


def _ensure_user_assigned_as_reviewer(
    building: Building, current_user: User, db: Session
) -> None:
    """Reviewer 행이 있는 사용자에게 본인 담당 건물만 허용."""
    reviewer = db.query(Reviewer).filter(Reviewer.user_id == current_user.id).first()
    if reviewer is None or building.reviewer_id != reviewer.id:
        raise HTTPException(status_code=404, detail="건축물을 찾을 수 없습니다")


def _ensure_review_upload_permission(
    building: Building, current_user: User, db: Session
) -> None:
    """검토서 업로드 권한 확인.

    - REVIEWER: 본인 담당 건물만 업로드
    - CHIEF_SECRETARY: 검토위원 제출이 어려운 경우 대리 업로드
    """
    if current_user.role == UserRole.CHIEF_SECRETARY:
        return
    if current_user.role in (UserRole.REVIEWER, UserRole.SECRETARY):
        _ensure_user_assigned_as_reviewer(building, current_user, db)
        return
    raise HTTPException(status_code=403, detail="검토서 업로드 권한이 없습니다")


def _assigned_reviewer_name_for_upload(building: Building) -> str | None:
    """대리 업로드 검증에 사용할 배정 검토위원명."""
    if building.reviewer and building.reviewer.user:
        return building.reviewer.user.name
    return building.assigned_reviewer_name


def _expected_reviewer_for_upload(
    building: Building, current_user: User
) -> tuple[str | None, str]:
    """검토서 F4와 대조할 이름과 라벨."""
    if current_user.role == UserRole.CHIEF_SECRETARY:
        reviewer_name = _assigned_reviewer_name_for_upload(building)
        if not reviewer_name:
            raise HTTPException(
                status_code=400,
                detail="검토위원이 배정되지 않아 대리 업로드할 수 없습니다",
            )
        return reviewer_name, "배정 검토위원"
    return current_user.name, "로그인 사용자"

# 판정결과 한글 라벨
_RESULT_KOREAN = {
    "pass": "적합",
    "simple_error": "단순오류",
    "recalculate": "재계산",
}
from engines.phase_machine import get_next_phase, can_advance, is_completed
from services.s3_storage import (
    upload_review_file,
    upload_generic_file,
    get_download_url,
    list_review_files,
    delete_file,
    stream_s3_file_to_writer,
)
from services.audit import log_action
from services.phase_transition import (
    InvalidPhaseTransition,
    next_phase_for,
    transition_phase,
)
from services.scope import (
    building_visibility_filter,
    is_building_visible_to,
)

router = APIRouter()
SEVERITY_LABELS = ("L0", "L1", "L2", "L3", "L4")
UNCLASSIFIED_SEVERITY = "NA"
EDITABLE_SEVERITIES = {*SEVERITY_LABELS, UNCLASSIFIED_SEVERITY}
QUALITY_DECISIONS = {"suitable", "unsuitable"}


def _reviewer_display_name_for_building(building: Building | None) -> str | None:
    """건물에 배정된 검토위원 표시명."""
    if building is None:
        return None
    if building.reviewer and building.reviewer.user:
        return building.reviewer.user.name
    return building.assigned_reviewer_name


def _mgmt_no_from_review_filename(filename: str | None) -> str | None:
    """S3 파일명에서 관리번호를 추출한다."""
    if not filename:
        return None
    stem = Path(filename).stem.strip()
    return stem or None


def _attach_review_file_metadata(db: Session, files: list[dict]) -> list[dict]:
    """검토서 파일 목록에 관리번호/건물 ID/업로드 검토자명을 일괄 보강한다.

    프론트가 파일마다 `/api/buildings`를 호출하지 않도록 여기서 한 번에 붙인다.
    """
    keys = [str(f.get("key") or "") for f in files if f.get("key")]
    stages = []
    if keys:
        stages = (
            db.query(ReviewStage)
            .options(
                selectinload(ReviewStage.building)
                .selectinload(Building.reviewer)
                .selectinload(Reviewer.user)
            )
            .filter(ReviewStage.s3_file_key.in_(keys))
            .all()
        )
    stage_by_key = {stage.s3_file_key: stage for stage in stages if stage.s3_file_key}

    fallback_mgmt_nos = {
        mgmt_no
        for f in files
        if str(f.get("key") or "") not in stage_by_key
        for mgmt_no in [_mgmt_no_from_review_filename(f.get("filename"))]
        if mgmt_no
    }
    buildings_by_mgmt_no: dict[str, Building] = {}
    if fallback_mgmt_nos:
        buildings = (
            db.query(Building)
            .options(selectinload(Building.reviewer).selectinload(Reviewer.user))
            .filter(Building.mgmt_no.in_(fallback_mgmt_nos))
            .all()
        )
        buildings_by_mgmt_no = {
            building.mgmt_no: building
            for building in buildings
            if building.mgmt_no
        }

    enriched = []
    for f in files:
        item = dict(f)
        key = str(item.get("key") or "")
        stage = stage_by_key.get(key)
        if stage and stage.building:
            item["stage_id"] = stage.id
            item["building_id"] = stage.building.id
            item["mgmt_no"] = stage.building.mgmt_no
            item["reviewer_name"] = (
                stage.reviewer_name
                or _reviewer_display_name_for_building(stage.building)
            )
        else:
            mgmt_no = _mgmt_no_from_review_filename(item.get("filename"))
            building = buildings_by_mgmt_no.get(mgmt_no or "")
            item["stage_id"] = None
            item["building_id"] = building.id if building else None
            item["mgmt_no"] = mgmt_no
            item["reviewer_name"] = _reviewer_display_name_for_building(building)
        enriched.append(item)

    return enriched


class SeveritySummaryResponse(BaseModel):
    category: str
    severity: str
    count: int

    model_config = {"from_attributes": True}


class ReviewStageResponse(BaseModel):
    id: int
    building_id: int
    phase: str
    phase_order: int
    doc_received_at: date | None = None
    report_submitted_at: date | None = None
    reviewer_name: str | None = None
    result: str | None = None
    defect_type_1: str | None = None
    defect_type_2: str | None = None
    defect_type_3: str | None = None
    severity_l0_count: int = 0
    severity_l1_count: int = 0
    severity_l2_count: int = 0
    severity_l3_count: int = 0
    severity_l4_count: int = 0
    severity_summaries: list[SeveritySummaryResponse] = []
    review_opinion: str | None = None
    s3_file_key: str | None = None
    inappropriate_review_needed: bool = False
    inappropriate_decision: str | None = None

    model_config = {"from_attributes": True}


class OpinionDetailResponse(BaseModel):
    id: int
    stage_id: int
    building_id: int
    mgmt_no: str
    building_name: str | None = None
    phase: str
    phase_group: str
    row_number: int | None = None
    category: str
    severity: str
    content: str
    quality_decision: str = "unsuitable"
    result: str | None = None


class OpinionDetailListResponse(BaseModel):
    items: list[OpinionDetailResponse]
    total: int


class QualityCheckItem(BaseModel):
    building_id: int
    mgmt_no: str
    full_address: str | None = None
    building_name: str | None = None
    group_no: int | None = None
    reviewer_name: str | None = None
    quality_categories: list[str]
    severity_levels: list[str]
    detail_count: int


class QualityCheckListResponse(BaseModel):
    items: list[QualityCheckItem]
    total: int


class QualityCheckResolveResponse(BaseModel):
    building_id: int
    updated_count: int


class OpinionSeverityUpdate(BaseModel):
    severity: str


class OpinionQualityDecisionUpdate(BaseModel):
    quality_decision: str


class FieldChange(BaseModel):
    field: str
    label: str
    old_value: str | None = None
    new_value: str | None = None
    # "building" = 빌딩 DB에 저장 및 업데이트
    # "review_stage" = review_stages 테이블에 저장
    # "reference" = 비교만 표시, DB 미반영
    scope: str = "building"


class UploadResponse(BaseModel):
    success: bool
    message: str
    errors: list[str] = []
    warnings: list[str] = []
    stage_id: int | None = None
    changes: list[FieldChange] = []


PHASE_ORDER_MAP = {
    "preliminary": 0,
    "supplement_1": 1,
    "supplement_2": 2,
    "supplement_3": 3,
    "supplement_4": 4,
    "supplement_5": 5,
}

RECEIVED_TO_SUBMIT_PHASE = {
    "doc_received": "preliminary",
    "supplement_1_received": "supplement_1",
    "supplement_2_received": "supplement_2",
    "supplement_3_received": "supplement_3",
    "supplement_4_received": "supplement_4",
    "supplement_5_received": "supplement_5",
}

SUBMITTED_UPLOAD_PHASES = set(PHASE_ORDER_MAP)

UPLOAD_PHASE_LABELS = {
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


def _phase_label(phase: str | None) -> str:
    return UPLOAD_PHASE_LABELS.get(phase or "", phase or "-")


def _resolve_upload_phase(building: Building, requested_phase: str) -> tuple[str | None, list[str]]:
    """현재 단계 기준으로 검토서 업로드 대상 단계를 결정한다.

    - 도서 접수 상태(_received): 최초 업로드 허용, 제출 단계로 매핑
    - 이미 제출된 현재 단계(preliminary/supplement_N): 같은 단계 재업로드 허용
    - 그 외 단계 또는 요청 단계 불일치: 업로드 차단
    """
    requested = (requested_phase or "").strip()
    current = (building.current_phase or "").strip()

    if not requested:
        return None, ["검토 단계 정보가 없습니다. 새로고침 후 다시 시도해주세요."]
    if not current:
        return None, ["현재 단계가 없어 검토서를 업로드할 수 없습니다. 도서 접수 후 업로드해주세요."]
    if requested != current:
        return None, [
            f"요청 단계({_phase_label(requested)})가 현재 단계({_phase_label(current)})와 일치하지 않습니다. "
            "새로고침 후 다시 업로드해주세요."
        ]
    if current in RECEIVED_TO_SUBMIT_PHASE:
        return RECEIVED_TO_SUBMIT_PHASE[current], []
    if current in SUBMITTED_UPLOAD_PHASES:
        return current, []
    return None, [
        f"현재 단계({_phase_label(current)})에서는 검토서를 업로드할 수 없습니다. "
        "도서 접수 상태에서 업로드하거나, 이미 제출된 현재 단계에서만 재업로드할 수 있습니다."
    ]


@router.post("/upload/preview", response_model=UploadResponse)
async def preview_upload(
    file: UploadFile = File(...),
    mgmt_no: str = Query(..., description="관리번호"),
    phase: str = Query(..., description="검토 단계"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """검토서 유효성 검증 + 변경사항 미리보기 (저장하지 않음)"""

    if not file.filename:
        raise HTTPException(status_code=400, detail="파일이 없습니다")

    building = db.query(Building).filter(Building.mgmt_no == mgmt_no).first()
    if not building:
        raise HTTPException(status_code=404, detail=f"관리번호 {mgmt_no}을 찾을 수 없습니다")
    # 비용 큰 파일 파싱 전에 fail-fast로 권한 검증
    _ensure_review_upload_permission(building, current_user, db)
    expected_reviewer_name, reviewer_label = _expected_reviewer_for_upload(
        building, current_user
    )

    target_phase, phase_errors = _resolve_upload_phase(building, phase)
    if phase_errors:
        return UploadResponse(success=False, message="업로드 불가", errors=phase_errors)

    tmp_path = await stream_upload_to_tempfile(
        file, max_mb=10, suffix=Path(file.filename).suffix
    )

    try:
        validation = validate_review_file(
            file_path=tmp_path, filename=file.filename,
            expected_mgmt_no=mgmt_no,
            submitter_name=expected_reviewer_name,
            expected_phase=target_phase,
            submitter_label=reviewer_label,
        )

        if not validation.is_valid:
            return UploadResponse(success=False, message="유효성 검증 실패", errors=validation.errors)

        # 변경사항 감지 (건축물 필드)
        extracted_data = validation.extracted_data
        changes = _detect_changes(building, extracted_data)

        # 검토결과(ReviewStage.result) 비교 추가
        review_info = extract_review_data(tmp_path)
        extracted_result = review_info.get("result")
        if extracted_result:
            actual_phase = target_phase
            try:
                phase_type = PhaseType(actual_phase)
                result_change = _detect_result_change(
                    db, building.id, phase_type, extracted_result
                )
                if result_change:
                    # 검토결과는 변경내역 목록 최상단에 노출
                    changes.insert(0, result_change)
            except ValueError:
                pass

        return UploadResponse(
            success=True,
            message="검증 통과. 변경사항을 확인하고 업로드 버튼을 눌러주세요.",
            warnings=validation.warnings,
            changes=changes,
        )
    finally:
        tmp_path.unlink(missing_ok=True)


def _detect_changes(building: Building, extracted_data: dict) -> list[FieldChange]:
    """건축물 정보 변경사항 감지 (DB 업데이트 여부와 무관하게 차이 표시)"""
    BUILDING_UPDATE_MAP = {
        "architect_firm": ("architect_firm", "건축사(소속)"),
        "architect_name": ("architect_name", "건축사(성명)"),
        "struct_eng_firm": ("struct_eng_firm", "책임구조기술자(소속)"),
        "struct_eng_name": ("struct_eng_name", "책임구조기술자(성명)"),
        "main_structure_type": ("main_structure", "주구조형식"),
        "high_risk_type": ("high_risk_type", "고위험유형"),
        "seismic_level": ("seismic_level", "내진등급"),
        "struct_drawing_qual": ("drawing_creator_qualification", "도면작성자 자격"),
    }
    DETAIL_CATEGORY_MAP = {
        "type_construction_method": ("detail_category1", "공법"),
        "type_transfer_structure": ("detail_category2", "전이구조"),
        "type_seismic_isolation": ("detail_category3", "면진&제진"),
        "type_special_shear_wall": ("detail_category4", "특수전단벽"),
        "type_flat_plate": ("detail_category5", "무량판"),
        "type_cantilever": ("detail_category6", "캔틸래버"),
        "type_long_span": ("detail_category7", "장스팬"),
        "type_high_rise": ("detail_category8", "고층"),
    }

    changes: list[FieldChange] = []

    # main_structure(주구조형식)는 참고 비교만 — DB에 반영하지 않으므로 scope="reference"
    REFERENCE_ONLY_FIELDS = {"main_structure"}

    for extract_key, (db_field, label) in {**BUILDING_UPDATE_MAP, **DETAIL_CATEGORY_MAP}.items():
        new_val = extracted_data.get(extract_key)
        if not new_val:
            continue
        old_val = getattr(building, db_field, None)
        scope = "reference" if db_field in REFERENCE_ONLY_FIELDS else "building"
        if old_val and old_val != new_val:
            changes.append(FieldChange(field=db_field, label=label, old_value=str(old_val), new_value=new_val, scope=scope))
        elif not old_val:
            changes.append(FieldChange(field=db_field, label=f"{label} (신규)", old_value="-", new_value=new_val, scope=scope))

    if extracted_data.get("type_is_piloti") and not building.detail_category9:
        changes.append(FieldChange(field="detail_category9", label="필로티 (신규)", old_value="-", new_value="필로티"))

    return changes


def _detect_result_change(
    db,
    building_id: int,
    phase_type_value,
    extracted_result,
) -> "FieldChange | None":
    """검토결과(ReviewStage.result) 변경 감지.

    비교 기준 우선순위:
    1. 같은 단계에 기존 result가 있으면 → 재업로드로 간주하고 그 값과 비교
    2. 없으면 → 이전 단계(phase_order 최대) 중 result가 있는 stage와 비교
    3. 없으면 → (신규)
    """
    new_label = _RESULT_KOREAN.get(extracted_result.value) if extracted_result else None
    if not new_label:
        return None

    # 1. 같은 단계 기존 result
    current_stage = (
        db.query(ReviewStage)
        .filter(
            ReviewStage.building_id == building_id,
            ReviewStage.phase == phase_type_value,
        )
        .first()
    )
    current_order = PHASE_ORDER_MAP.get(phase_type_value.value, 0)

    old_result = None
    old_phase_label = ""
    if current_stage and current_stage.result is not None:
        old_result = current_stage.result
        old_phase_label = "재업로드"
    else:
        # 2. 이전 단계 중 result 있는 stage (phase_order < current)
        prev_stage = (
            db.query(ReviewStage)
            .filter(
                ReviewStage.building_id == building_id,
                ReviewStage.result.isnot(None),
            )
            .all()
        )
        prev_stage_sorted = sorted(
            [s for s in prev_stage if PHASE_ORDER_MAP.get(s.phase.value, 0) < current_order],
            key=lambda s: PHASE_ORDER_MAP.get(s.phase.value, 0),
            reverse=True,
        )
        if prev_stage_sorted:
            prev = prev_stage_sorted[0]
            old_result = prev.result
            old_phase_label = _PHASE_DISPLAY.get(prev.phase.value, prev.phase.value)

    if old_result is None:
        # 이전 단계 결과 없음 → 신규
        return FieldChange(
            field="result",
            label="검토결과 (신규)",
            old_value="-",
            new_value=new_label,
            scope="review_stage",
        )

    # 동일하면 "유지" 표시 (변경 없음이지만 정보 전달)
    if old_result == extracted_result:
        label_suffix = f" (이전 {old_phase_label} 동일)" if old_phase_label else " (동일)"
        return FieldChange(
            field="result",
            label=f"검토결과{label_suffix}",
            old_value=_RESULT_KOREAN.get(old_result.value, old_result.value),
            new_value=new_label,
            scope="review_stage",
        )

    # 변경
    label_prefix = f"검토결과 (이전 {old_phase_label})" if old_phase_label else "검토결과"
    return FieldChange(
        field="result",
        label=label_prefix,
        old_value=_RESULT_KOREAN.get(old_result.value, old_result.value),
        new_value=new_label,
        scope="review_stage",
    )


# 단계 표시용 짧은 라벨
_PHASE_DISPLAY: dict[str, str] = {
    "preliminary": "예비",
    "supplement_1": "보완 1차",
    "supplement_2": "보완 2차",
    "supplement_3": "보완 3차",
    "supplement_4": "보완 4차",
    "supplement_5": "보완 5차",
}


def _apply_changes(building: Building, extracted_data: dict):
    """건축물 정보 변경 적용.

    주의: main_structure(주구조형식)는 미리보기에서는 비교 표시하지만
    빌딩 DB에는 반영하지 않는다.
    """
    BUILDING_UPDATE_MAP = {
        "architect_firm": "architect_firm",
        "architect_name": "architect_name",
        "struct_eng_firm": "struct_eng_firm",
        "struct_eng_name": "struct_eng_name",
        # "main_structure_type": "main_structure",  # 의도적으로 제외
        "high_risk_type": "high_risk_type",
        "seismic_level": "seismic_level",
        "struct_drawing_qual": "drawing_creator_qualification",
    }
    DETAIL_CATEGORY_MAP = {
        "type_construction_method": "detail_category1",
        "type_transfer_structure": "detail_category2",
        "type_seismic_isolation": "detail_category3",
        "type_special_shear_wall": "detail_category4",
        "type_flat_plate": "detail_category5",
        "type_cantilever": "detail_category6",
        "type_long_span": "detail_category7",
        "type_high_rise": "detail_category8",
    }

    for extract_key, db_field in {**BUILDING_UPDATE_MAP, **DETAIL_CATEGORY_MAP}.items():
        new_val = extracted_data.get(extract_key)
        if new_val:
            setattr(building, db_field, new_val)

    if extracted_data.get("type_is_piloti"):
        building.detail_category9 = "필로티"


def _apply_severity_counts(stage: ReviewStage, extracted: dict) -> None:
    counts = extracted.get("severity_counts") or {}
    stage.severity_l0_count = int(counts.get("L0", 0) or 0)
    stage.severity_l1_count = int(counts.get("L1", 0) or 0)
    stage.severity_l2_count = int(counts.get("L2", 0) or 0)
    stage.severity_l3_count = int(counts.get("L3", 0) or 0)
    stage.severity_l4_count = int(counts.get("L4", 0) or 0)


def _apply_severity_summaries(db: Session, stage: ReviewStage, extracted: dict) -> None:
    """검토서 상세의견의 분류별 심각도 집계를 저장한다.

    재업로드 시 기존 집계를 그대로 두면 통계가 중복되므로, 같은 stage의 집계는
    매 업로드마다 전체 교체한다.
    """
    if stage.id is None:
        db.add(stage)
        db.flush()

    db.query(ReviewSeveritySummary).filter(
        ReviewSeveritySummary.stage_id == stage.id
    ).delete(synchronize_session="fetch")

    rows = extracted.get("category_severity_counts") or []
    valid_severities = {"L0", "L1", "L2", "L3", "L4"}
    for row in rows:
        category = str(row.get("category") or "").strip()
        severity = str(row.get("severity") or "").strip().upper()
        count = int(row.get("count") or 0)
        if not category or severity not in valid_severities or count <= 0:
            continue
        db.add(ReviewSeveritySummary(
            stage_id=stage.id,
            category=category,
            severity=severity,
            count=count,
        ))


def _phase_group_for_review(phase: str) -> str:
    return "preliminary" if phase == "preliminary" else "supplement"


def _apply_opinion_details(
    db: Session,
    stage: ReviewStage,
    phase: str,
    extracted: dict,
) -> None:
    """상세검토 내용 원문을 예비검토/보완검토 구분과 함께 저장한다."""
    if stage.id is None:
        db.add(stage)
        db.flush()

    db.query(ReviewOpinionDetail).filter(
        ReviewOpinionDetail.stage_id == stage.id
    ).delete(synchronize_session="fetch")

    rows = extracted.get("opinion_entries") or []
    phase_group = _phase_group_for_review(phase)
    valid_severities = {"L0", "L1", "L2", "L3", "L4"}
    for row in rows:
        category = str(row.get("category") or "").strip()
        severity = str(row.get("severity") or "").strip().upper()
        content = clean_opinion_detail_content(row.get("content"))
        if not category or severity not in valid_severities or not content:
            continue
        raw_row_number = row.get("row")
        row_number = int(raw_row_number) if raw_row_number else None
        db.add(ReviewOpinionDetail(
            stage_id=stage.id,
            phase=phase,
            phase_group=phase_group,
            row_number=row_number,
            category=category,
            severity=severity,
            content=content,
        ))


def _normalize_editable_severity(value: str | None) -> str:
    severity = (value or "").strip().upper()
    if severity in ("", "UNCLASSIFIED", "NONE"):
        return UNCLASSIFIED_SEVERITY
    if severity not in EDITABLE_SEVERITIES:
        raise HTTPException(status_code=400, detail="허용되지 않는 심각도입니다")
    return severity


def _rebuild_stage_severity_from_details(db: Session, stage: ReviewStage) -> None:
    if stage.id is None:
        db.add(stage)
        db.flush()

    db.query(ReviewSeveritySummary).filter(
        ReviewSeveritySummary.stage_id == stage.id
    ).delete(synchronize_session="fetch")
    db.flush()

    counts_by_severity = {label: 0 for label in SEVERITY_LABELS}
    rows = (
        db.query(
            ReviewOpinionDetail.category,
            ReviewOpinionDetail.severity,
            func.count(ReviewOpinionDetail.id),
        )
        .filter(
            ReviewOpinionDetail.stage_id == stage.id,
            ReviewOpinionDetail.severity.in_(SEVERITY_LABELS),
        )
        .group_by(ReviewOpinionDetail.category, ReviewOpinionDetail.severity)
        .all()
    )

    for category, severity, count in rows:
        count_value = int(count or 0)
        if count_value <= 0:
            continue
        counts_by_severity[severity] += count_value
        db.add(ReviewSeveritySummary(
            stage_id=stage.id,
            category=category,
            severity=severity,
            count=count_value,
        ))

    for label in SEVERITY_LABELS:
        setattr(stage, f"severity_{label.lower()}_count", counts_by_severity[label])


def _opinion_detail_response(
    detail: ReviewOpinionDetail,
    stage: ReviewStage,
    building: Building,
) -> OpinionDetailResponse:
    phase = stage.phase.value if hasattr(stage.phase, "value") else str(stage.phase)
    result = stage.result.value if stage.result else None
    return OpinionDetailResponse(
        id=detail.id,
        stage_id=stage.id,
        building_id=building.id,
        mgmt_no=building.mgmt_no,
        building_name=building.building_name,
        phase=phase,
        phase_group=detail.phase_group,
        row_number=detail.row_number,
        category=detail.category,
        severity=detail.severity,
        content=detail.content,
        quality_decision=detail.quality_decision or "unsuitable",
        result=result,
    )


def _resolve_inappropriate_review_needed(
    stage: ReviewStage | None,
    requested_value: bool,
) -> bool:
    """부적정 사례 검토 필요 체크는 검토서 재업로드로 해제할 수 없게 보존."""
    return bool(requested_value or (stage and stage.inappropriate_review_needed))


def _quality_check_base_query(db: Session, current_user: User):
    """검토서 확인 대상 후보가 되는 미처리 상세 의견 기본 쿼리."""
    query = (
        db.query(ReviewOpinionDetail, ReviewStage, Building)
        .join(ReviewStage, ReviewOpinionDetail.stage_id == ReviewStage.id)
        .join(Building, ReviewStage.building_id == Building.id)
        .filter(
            or_(
                ReviewOpinionDetail.quality_decision.is_(None),
                ReviewOpinionDetail.quality_decision != "suitable",
            ),
        )
    )
    visibility = building_visibility_filter(current_user)
    if visibility is not None:
        query = query.filter(visibility)
    return query


def _is_quality_check_target(detail: ReviewOpinionDetail) -> bool:
    """심각도 L3/L4 또는 표현 품질 규칙에 걸린 상세 의견인지 확인한다."""
    return detail.severity in ("L3", "L4") or bool(
        match_opinion_quality(detail.content or "")
    )


def _sorted_severity_levels(values: set[str]) -> list[str]:
    """심각도 레이블은 L0~L4 순서를 유지한다."""
    order = {label: idx for idx, label in enumerate(SEVERITY_LABELS)}
    return sorted(values, key=lambda value: (order.get(value, len(order)), value))


@router.get("/quality-checks", response_model=QualityCheckListResponse)
def list_quality_checks(
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(
            UserRole.TEAM_LEADER,
            UserRole.CHIEF_SECRETARY,
            UserRole.SECRETARY,
        )
    ),
):
    """심각도 L3/L4 또는 표현 품질 문제 대상인 검토서 확인 목록."""
    actual_user = aliased(User)
    actual_reviewer = aliased(Reviewer)
    rows = (
        _quality_check_base_query(db, current_user)
        .add_columns(
            Reviewer.group_no.label("assigned_group_no"),
            User.name.label("assigned_reviewer_name"),
            actual_reviewer.group_no.label("actual_group_no"),
        )
        .outerjoin(Reviewer, Building.reviewer_id == Reviewer.id)
        .outerjoin(User, Reviewer.user_id == User.id)
        .outerjoin(
            actual_user,
            and_(
                actual_user.name == ReviewStage.reviewer_name,
                actual_user.role == UserRole.REVIEWER,
            ),
        )
        .outerjoin(actual_reviewer, actual_reviewer.user_id == actual_user.id)
        .order_by(
            Building.mgmt_no,
            ReviewStage.phase_order.desc(),
            ReviewOpinionDetail.row_number,
            ReviewOpinionDetail.id,
        )
        .all()
    )

    item_map: dict[int, dict] = {}
    for detail, stage, building, assigned_group_no, assigned_name, actual_group_no in rows:
        matches = match_opinion_quality(detail.content or "")
        is_severity_target = detail.severity in ("L3", "L4")
        if not (is_severity_target or matches):
            continue
        reviewer_name = (stage.reviewer_name or "").strip()
        if not reviewer_name:
            reviewer_name = assigned_name or building.assigned_reviewer_name or None
        group_no = actual_group_no if (stage.reviewer_name or "").strip() else assigned_group_no

        item = item_map.setdefault(
            building.id,
            {
                "building_id": building.id,
                "mgmt_no": building.mgmt_no,
                "full_address": _address_of(building),
                "building_name": building.building_name,
                "group_no": group_no,
                "reviewer_name": reviewer_name,
                "quality_categories": set(),
                "severity_levels": set(),
                "detail_count": 0,
            },
        )
        item["detail_count"] = int(item["detail_count"]) + 1
        item["quality_categories"].update(match.category for match in matches)
        if detail.severity:
            item["severity_levels"].add(detail.severity)

    items = []
    for item in sorted(item_map.values(), key=lambda value: value["mgmt_no"]):
        item["quality_categories"] = sorted(item["quality_categories"])
        item["severity_levels"] = _sorted_severity_levels(item["severity_levels"])
        items.append(QualityCheckItem(**item))
    return QualityCheckListResponse(items=items, total=len(items))


@router.patch(
    "/quality-checks/{building_id}/suitable",
    response_model=QualityCheckResolveResponse,
)
def mark_quality_check_suitable(
    building_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(
            UserRole.TEAM_LEADER,
            UserRole.CHIEF_SECRETARY,
            UserRole.SECRETARY,
        )
    ),
):
    """해당 건물의 검토서 확인 대상 상세 의견을 적합 처리한다."""
    rows = (
        _quality_check_base_query(db, current_user)
        .filter(Building.id == building_id)
        .all()
    )
    updated_count = 0
    for detail, _stage, _building in rows:
        if not _is_quality_check_target(detail):
            continue
        detail.quality_decision = "suitable"
        updated_count += 1

    if updated_count == 0:
        raise HTTPException(status_code=404, detail="검토서 확인 대상을 찾을 수 없습니다")

    from routers.buildings import clear_stats_cache

    clear_stats_cache()
    db.commit()
    return QualityCheckResolveResponse(
        building_id=building_id,
        updated_count=updated_count,
    )


@router.get("/opinion-details", response_model=OpinionDetailListResponse)
def list_opinion_details(
    search: str | None = None,
    severity: str | None = None,
    phase_group: str | None = None,
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
    query = (
        db.query(ReviewOpinionDetail, ReviewStage, Building)
        .join(ReviewStage, ReviewOpinionDetail.stage_id == ReviewStage.id)
        .join(Building, ReviewStage.building_id == Building.id)
    )
    visibility = building_visibility_filter(current_user)
    if visibility is not None:
        query = query.filter(visibility)

    if severity:
        query = query.filter(
            ReviewOpinionDetail.severity == _normalize_editable_severity(severity)
        )
    if phase_group:
        if phase_group not in ("preliminary", "supplement"):
            raise HTTPException(status_code=400, detail="허용되지 않는 단계 구분입니다")
        query = query.filter(ReviewOpinionDetail.phase_group == phase_group)
    if search:
        pattern = f"%{search.strip()}%"
        query = query.filter(or_(
            Building.mgmt_no.ilike(pattern),
            Building.building_name.ilike(pattern),
            ReviewOpinionDetail.category.ilike(pattern),
            ReviewOpinionDetail.content.ilike(pattern),
        ))

    total = query.count()
    rows = (
        query.order_by(
            Building.mgmt_no,
            ReviewStage.phase_order,
            ReviewOpinionDetail.row_number,
            ReviewOpinionDetail.id,
        )
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    return OpinionDetailListResponse(
        items=[
            _opinion_detail_response(detail, stage, building)
            for detail, stage, building in rows
        ],
        total=total,
    )


@router.patch("/opinion-details/{detail_id}/severity", response_model=OpinionDetailResponse)
def update_opinion_detail_severity(
    detail_id: int,
    body: OpinionSeverityUpdate,
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
    severity = _normalize_editable_severity(body.severity)
    query = (
        db.query(ReviewOpinionDetail, ReviewStage, Building)
        .join(ReviewStage, ReviewOpinionDetail.stage_id == ReviewStage.id)
        .join(Building, ReviewStage.building_id == Building.id)
        .filter(ReviewOpinionDetail.id == detail_id)
    )
    visibility = building_visibility_filter(current_user)
    if visibility is not None:
        query = query.filter(visibility)

    row = query.first()
    if row is None:
        raise HTTPException(status_code=404, detail="의견 상세를 찾을 수 없습니다")

    detail, stage, building = row
    detail.severity = severity
    _rebuild_stage_severity_from_details(db, stage)

    from routers.buildings import clear_stats_cache

    clear_stats_cache()
    db.commit()
    db.refresh(detail)
    db.refresh(stage)
    return _opinion_detail_response(detail, stage, building)


@router.patch(
    "/opinion-details/{detail_id}/quality-decision",
    response_model=OpinionDetailResponse,
)
def update_opinion_detail_quality_decision(
    detail_id: int,
    body: OpinionQualityDecisionUpdate,
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
    decision = body.quality_decision
    if decision not in QUALITY_DECISIONS:
        raise HTTPException(status_code=400, detail="허용되지 않는 표현 품질 판정입니다")

    query = (
        db.query(ReviewOpinionDetail, ReviewStage, Building)
        .join(ReviewStage, ReviewOpinionDetail.stage_id == ReviewStage.id)
        .join(Building, ReviewStage.building_id == Building.id)
        .filter(ReviewOpinionDetail.id == detail_id)
    )
    visibility = building_visibility_filter(current_user)
    if visibility is not None:
        query = query.filter(visibility)

    row = query.first()
    if row is None:
        raise HTTPException(status_code=404, detail="의견 상세를 찾을 수 없습니다")

    detail, stage, building = row
    detail.quality_decision = decision

    from routers.buildings import clear_stats_cache

    clear_stats_cache()
    db.commit()
    db.refresh(detail)
    return _opinion_detail_response(detail, stage, building)


@router.post("/upload", response_model=UploadResponse)
async def upload_review(
    file: UploadFile = File(...),
    mgmt_no: str = Query(..., description="관리번호"),
    phase: str = Query(..., description="검토 단계"),
    inappropriate_review_needed: bool = Query(False, description="부적정 사례 검토 필요 여부"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """검토서 업로드 확정 (유효성 검증 + DB 저장 + 건축물 정보 변경 적용)"""

    if not file.filename:
        raise HTTPException(status_code=400, detail="파일이 없습니다")

    # 건축물 확인
    building = db.query(Building).filter(Building.mgmt_no == mgmt_no).first()
    if not building:
        raise HTTPException(status_code=404, detail=f"관리번호 {mgmt_no}을 찾을 수 없습니다")
    # 비용 큰 파일 파싱·DB 쓰기 전에 fail-fast로 권한 검증
    _ensure_review_upload_permission(building, current_user, db)
    expected_reviewer_name, reviewer_label = _expected_reviewer_for_upload(
        building, current_user
    )

    actual_phase, phase_errors = _resolve_upload_phase(building, phase)
    if phase_errors:
        return UploadResponse(success=False, message="업로드 불가", errors=phase_errors)

    # 임시 파일 저장
    tmp_path = await stream_upload_to_tempfile(
        file, max_mb=10, suffix=Path(file.filename).suffix
    )

    try:
        # 2. 유효성 검증 (expected_phase 기준으로 차수 라벨 체크)
        validation = validate_review_file(
            file_path=tmp_path,
            filename=file.filename,
            expected_mgmt_no=mgmt_no,
            submitter_name=expected_reviewer_name,
            expected_phase=actual_phase,
            submitter_label=reviewer_label,
        )

        if not validation.is_valid:
            return UploadResponse(
                success=False,
                message="유효성 검증 실패",
                errors=validation.errors,
            )

        # 3. 검토서 내용 추출
        extracted = extract_review_data(tmp_path)
        submitted_reviewer_name = validation.reviewer_name or expected_reviewer_name
        try:
            phase_type = PhaseType(actual_phase)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"잘못된 검토 단계: {phase}")

        phase_order = PHASE_ORDER_MAP.get(actual_phase, 0)

        # 4. review_stages 생성 또는 업데이트
        stage = (
            db.query(ReviewStage)
            .filter(
                ReviewStage.building_id == building.id,
                ReviewStage.phase == phase_type,
            )
            .first()
        )

        if stage:
            # 기존 단계 업데이트 (재업로드)
            # 새 파일 업로드 전에 기존 S3 파일 삭제 (날짜 경로가 다르면 orphan 방지)
            old_s3_key = stage.s3_file_key
            stage.report_submitted_at = business_today()
            stage.reviewer_name = submitted_reviewer_name
            if extracted["result"]:
                stage.result = extracted["result"]
            if extracted["defect_type_1"]:
                stage.defect_type_1 = extracted["defect_type_1"]
            if extracted["defect_type_2"]:
                stage.defect_type_2 = extracted["defect_type_2"]
            if extracted["defect_type_3"]:
                stage.defect_type_3 = extracted["defect_type_3"]
            stage.review_opinion = extracted["review_opinion"]
            _apply_severity_counts(stage, extracted)
            _apply_severity_summaries(db, stage, extracted)
            _apply_opinion_details(db, stage, actual_phase, extracted)
            stage.inappropriate_review_needed = _resolve_inappropriate_review_needed(
                stage,
                inappropriate_review_needed,
            )
            new_s3_key = upload_review_file(tmp_path, mgmt_no, actual_phase, file.filename)
            stage.s3_file_key = new_s3_key
            if old_s3_key and old_s3_key != new_s3_key:
                try:
                    delete_file(old_s3_key)
                except Exception:
                    pass  # 이전 파일 삭제 실패는 무시 (이미 없거나 권한 이슈)
        else:
            # 새 단계 생성
            stage = ReviewStage(
                building_id=building.id,
                phase=phase_type,
                phase_order=phase_order,
                report_submitted_at=business_today(),
                reviewer_name=submitted_reviewer_name,
                result=extracted["result"],
                defect_type_1=extracted["defect_type_1"],
                defect_type_2=extracted["defect_type_2"],
                defect_type_3=extracted["defect_type_3"],
                review_opinion=extracted["review_opinion"],
                inappropriate_review_needed=_resolve_inappropriate_review_needed(
                    None,
                    inappropriate_review_needed,
                ),
                s3_file_key=upload_review_file(tmp_path, mgmt_no, actual_phase, file.filename),
            )
            _apply_severity_counts(stage, extracted)
            db.add(stage)
            _apply_severity_summaries(db, stage, extracted)
            _apply_opinion_details(db, stage, actual_phase, extracted)

        # 5. 건축물 current_phase 전환 (매트릭스 UPLOAD).
        # 출발 phase가 _received일 때만 다음 단계로 전환한다. 그 외(이미 제출 완료
        # 상태에서의 검토서 재업로드 등)는 phase 그대로 유지하고 stage 데이터만 갱신.
        target_after_upload = next_phase_for("upload", building.current_phase)
        if target_after_upload:
            transition_phase(
                db, building, to_phase=target_after_upload, trigger="upload",
                actor_user_id=current_user.id,
            )

        # 6. 건축물 정보 변경 적용 — detect를 먼저 호출해야 변경 전 값과 비교 가능.
        # apply가 먼저 setattr하면 _detect_changes의 getattr이 new_val을 읽어 변경이 사라짐.
        changes = _detect_changes(building, validation.extracted_data)
        _apply_changes(building, validation.extracted_data)

        log_action(
            db,
            current_user.id,
            "upload",
            "review_stage",
            stage.id,
            after_data={
                "mgmt_no": mgmt_no,
                "phase": phase,
                "reviewer_name": submitted_reviewer_name,
                "proxy_upload": current_user.role == UserRole.CHIEF_SECRETARY,
            },
        )
        db.commit()
        db.refresh(stage)

        return UploadResponse(
            success=True,
            message=f"검토서가 제출되었습니다 (관리번호: {mgmt_no}, 단계: {phase})",
            warnings=validation.warnings,
            stage_id=stage.id,
            changes=changes,
        )

    finally:
        tmp_path.unlink(missing_ok=True)


@router.get("/files")
def list_uploaded_files(
    phase: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(
            UserRole.TEAM_LEADER,
            UserRole.CHIEF_SECRETARY,
            UserRole.MANAGER,
        )
    ),
):
    """업로드된 검토서 파일 목록 (팀장/총괄간사/관리원)."""
    prefix = "reviews/"
    if phase:
        from services.s3_storage import PHASE_FOLDER_MAP
        phase_folder = PHASE_FOLDER_MAP.get(phase, phase)
        prefix = f"reviews/{phase_folder}/"

    files = list_review_files(prefix)
    return _attach_review_file_metadata(db, files)


MAX_REVIEW_FILE_ZIP_COUNT = 500


class ReviewFilesZipRequest(BaseModel):
    keys: list[str]
    archive_name: str | None = None


def _normalize_review_file_keys(keys: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_key in keys:
        key = (raw_key or "").strip()
        if not key:
            continue
        if not key.startswith("reviews/"):
            raise HTTPException(status_code=400, detail="검토서 파일만 다운로드할 수 있습니다")
        if key not in seen:
            seen.add(key)
            normalized.append(key)

    if not normalized:
        raise HTTPException(status_code=400, detail="다운로드할 파일이 없습니다")
    if len(normalized) > MAX_REVIEW_FILE_ZIP_COUNT:
        raise HTTPException(
            status_code=400,
            detail=f"한 번에 최대 {MAX_REVIEW_FILE_ZIP_COUNT}개까지 다운로드할 수 있습니다",
        )
    return normalized


def _safe_zip_download_filename(name: str | None) -> str:
    fallback = f"review-files-{datetime.now():%Y%m%d-%H%M%S}.zip"
    raw = (name or fallback).strip() or fallback
    cleaned = "".join(
        ch if ch.isalnum() or ch in {" ", "-", "_", "."} else "_"
        for ch in raw.replace("\\", "_").replace("/", "_")
    ).strip(" ._")
    if not cleaned:
        cleaned = fallback
    if cleaned.lower().endswith(".zip"):
        cleaned = cleaned[:-4]
    return f"{cleaned[:150]}.zip"


def _unique_zip_member_name(key: str, used_names: set[str]) -> str:
    filename = Path(key).name.strip() or "review-file"
    filename = filename.replace("\\", "_").replace("/", "_")
    path = Path(filename)
    stem = path.stem or "review-file"
    suffix = path.suffix
    candidate = f"{stem}{suffix}"
    index = 2
    while candidate in used_names:
        candidate = f"{stem} ({index}){suffix}"
        index += 1
    used_names.add(candidate)
    return candidate


@router.post("/files/download-zip")
def download_files_zip(
    payload: ReviewFilesZipRequest,
    current_user: User = Depends(
        require_roles(
            UserRole.TEAM_LEADER,
            UserRole.CHIEF_SECRETARY,
            UserRole.MANAGER,
        )
    ),
):
    """선택한 검토서 파일들을 ZIP 하나로 다운로드한다."""
    del current_user
    keys = _normalize_review_file_keys(payload.keys)
    archive_filename = _safe_zip_download_filename(payload.archive_name)

    tmp = tempfile.NamedTemporaryFile(
        prefix="review-files-",
        suffix=".zip",
        delete=False,
    )
    zip_path = Path(tmp.name)
    tmp.close()

    try:
        with zipfile.ZipFile(
            zip_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            allowZip64=True,
        ) as archive:
            used_names: set[str] = set()
            for key in keys:
                member_name = _unique_zip_member_name(key, used_names)
                info = zipfile.ZipInfo(
                    filename=member_name,
                    date_time=datetime.now().timetuple()[:6],
                )
                info.compress_type = zipfile.ZIP_DEFLATED
                with archive.open(info, "w") as member:
                    try:
                        stream_s3_file_to_writer(key, member)
                    except FileNotFoundError as exc:
                        raise HTTPException(
                            status_code=404,
                            detail=f"파일을 찾을 수 없습니다: {key}",
                        ) from exc
                    except Exception as exc:
                        raise HTTPException(
                            status_code=502,
                            detail="검토서 ZIP 생성 중 S3 파일을 읽지 못했습니다",
                        ) from exc

        return FileResponse(
            path=zip_path,
            media_type="application/zip",
            filename=archive_filename,
            background=BackgroundTask(zip_path.unlink, missing_ok=True),
        )
    except Exception:
        zip_path.unlink(missing_ok=True)
        raise


@router.get("/files/download")
def download_file(
    key: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(
            UserRole.TEAM_LEADER,
            UserRole.CHIEF_SECRETARY,
            UserRole.MANAGER,
        )
    ),
):
    """검토서 파일 다운로드 URL 생성 (presigned URL 반환만)."""
    url = get_download_url(key)
    if not url:
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다")
    return {"download_url": url}


@router.delete("/files")
def delete_review_file(
    key: str = Query(..., description="삭제할 S3 객체 키"),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """검토서 파일 삭제 (팀장/총괄간사).

    - S3 객체 삭제
    - 해당 key 를 참조하던 ReviewStage.s3_file_key 는 NULL 로 비움 (검토 결과/제출일
      같은 이력은 유지). 필요 시 운영자가 직접 재업로드 또는 초기화.
    - 감사 로그에 삭제자·key 기록.
    """
    # 1) 같은 key 를 가진 stage 조회 (s3_file_key 클리어 대상)
    affected_stages = (
        db.query(ReviewStage).filter(ReviewStage.s3_file_key == key).all()
    )
    affected_stage_ids = [s.id for s in affected_stages]

    # 2) S3 객체 삭제 시도 (실패해도 DB 변경은 진행 — 감사 로그에 결과 남김)
    s3_deleted = False
    try:
        s3_deleted = delete_file(key)
    except Exception:
        s3_deleted = False

    # 3) S3 에도 없고 참조 stage 도 없으면 실제 삭제할 것이 없음 → 404 (audit 생략)
    if not s3_deleted and not affected_stage_ids:
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다")

    # 4) 실제 상태 변경 후에만 audit + commit
    for stage in affected_stages:
        stage.s3_file_key = None
    log_action(
        db, current_user.id, "delete", "review_file",
        after_data={
            "key": key,
            "s3_deleted": s3_deleted,
            "stage_ids": affected_stage_ids,
        },
    )
    db.commit()
    if affected_stage_ids:
        from routers.buildings import clear_stats_cache

        clear_stats_cache()

    return {
        "key": key,
        "s3_deleted": s3_deleted,
        "stage_ids": affected_stage_ids,
    }


@router.get("/stages/{building_id}", response_model=list[ReviewStageResponse])
def get_review_stages(
    building_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """건축물의 검토 단계 목록 조회 (REVIEWER는 본인 담당만)"""
    building = db.query(Building).filter(Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="건축물을 찾을 수 없습니다")
    _ensure_reviewer_can_access_building(building, current_user, db)

    stages = (
        db.query(ReviewStage)
        .filter(ReviewStage.building_id == building_id)
        .order_by(ReviewStage.phase_order)
        .all()
    )
    return stages


@router.delete("/stages/{stage_id}")
def delete_review_stage(
    stage_id: int,
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
    """검토 단계 이력 전체를 삭제한다."""
    query = (
        db.query(ReviewStage)
        .join(Building, ReviewStage.building_id == Building.id)
        .filter(ReviewStage.id == stage_id)
    )
    visibility = building_visibility_filter(current_user)
    if visibility is not None:
        query = query.filter(visibility)

    stage = query.first()
    if stage is None:
        raise HTTPException(status_code=404, detail="검토 단계를 찾을 수 없습니다")

    from models.inappropriate_note import InappropriateNote

    stage_phase = stage.phase.value if hasattr(stage.phase, "value") else str(stage.phase)
    stage_building_id = stage.building_id
    old_s3_key = stage.s3_file_key
    s3_deleted = False
    if old_s3_key:
        try:
            s3_deleted = delete_file(old_s3_key)
        except Exception:
            s3_deleted = False

    inappropriate_notes_deleted = (
        db.query(InappropriateNote)
        .filter(InappropriateNote.stage_id == stage.id)
        .delete(synchronize_session=False)
    )
    opinion_details_deleted = (
        db.query(ReviewOpinionDetail)
        .filter(ReviewOpinionDetail.stage_id == stage.id)
        .delete(synchronize_session=False)
    )
    severity_summaries_deleted = (
        db.query(ReviewSeveritySummary)
        .filter(ReviewSeveritySummary.stage_id == stage.id)
        .delete(synchronize_session=False)
    )

    log_action(
        db,
        current_user.id,
        "delete",
        "review_stage",
        stage.id,
        after_data={
            "stage_id": stage.id,
            "building_id": stage_building_id,
            "phase": stage_phase,
            "s3_file_key": old_s3_key,
            "s3_deleted": s3_deleted,
            "inappropriate_notes_deleted": int(inappropriate_notes_deleted or 0),
            "opinion_details_deleted": int(opinion_details_deleted or 0),
            "severity_summaries_deleted": int(severity_summaries_deleted or 0),
        },
    )
    db.delete(stage)

    from routers.buildings import clear_stats_cache

    clear_stats_cache()
    db.commit()
    return {
        "stage_id": stage_id,
        "building_id": stage_building_id,
        "phase": stage_phase,
        "s3_deleted": s3_deleted,
    }


class InquiryCreateRequest(BaseModel):
    mgmt_no: str
    phase: str
    content: str


class InquiryUpdateRequest(BaseModel):
    reply: str | None = None
    status: str | None = None  # asking_agency / completed
    # 단계 변경을 함께 수행할 경우 사용. 지정되면 해당 건물의 current_phase가 갱신되고,
    # inquiry 상태는 자동으로 COMPLETED로 통합된다.
    new_phase: str | None = None


class InquiryContentUpdateRequest(BaseModel):
    content: str


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
    "completed": "완료",
}


def _can_manage_inquiry(inquiry, current_user: User, db: Session) -> bool:
    """간사 이상 사용자가 해당 문의를 관리할 수 있는지 확인."""
    if current_user.role in (UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY):
        return True
    if current_user.role == UserRole.SECRETARY:
        if current_user.group_no is None:
            return True
        building = db.query(Building).filter(Building.id == inquiry.building_id).first()
        if building and is_building_visible_to(current_user, building, db):
            return True
        if getattr(inquiry, "mgmt_no", None):
            mgmt_building = (
                db.query(Building)
                .filter(Building.mgmt_no == inquiry.mgmt_no)
                .first()
            )
            if mgmt_building and is_building_visible_to(current_user, mgmt_building, db):
                return True
        if inquiry.submitter_id is not None:
            return (
                db.query(Reviewer.id)
                .filter(
                    Reviewer.user_id == inquiry.submitter_id,
                    Reviewer.group_no == current_user.group_no,
                )
                .first()
                is not None
            )
        return False
    return False


def _inquiry_visibility_filter(current_user: User):
    """문의 목록용 가시성 필터.

    같은 조 간사는 현재 건물 담당자 기준뿐 아니라 문의 작성 검토위원의 조 기준도
    함께 사용한다. 실제 운영에서는 관리번호/담당자 연결이 사후 보정될 수 있어서
    building_id 하나만 보면 간사 문의함에서 누락될 수 있다.
    """
    from models.inquiry import Inquiry

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
            select(Building.id)
            .where(Building.reviewer_id.in_(same_group_reviewer_ids))
        )
        same_group_mgmt_nos = (
            select(Building.mgmt_no)
            .where(Building.reviewer_id.in_(same_group_reviewer_ids))
        )
        return or_(
            Inquiry.building_id.in_(same_group_building_ids),
            Inquiry.mgmt_no.in_(same_group_mgmt_nos),
            Inquiry.submitter_id.in_(same_group_reviewer_user_ids),
        )
    return Inquiry.id.is_(None)


@router.post("/inquiry")
async def create_inquiry(
    body: InquiryCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """문의사항 등록 — 해당 건물의 담당 검토자만 가능.

    담당 판정은 `Reviewer.user_id == current_user.id` 그리고
    `building.reviewer_id == reviewer.id`. 이름 기반 매칭은 동명이인 위험으로 제거.
    역할(role)은 무관 — REVIEWER가 아닌 사용자도 Reviewer 행이 있으면 문의 가능.
    """
    from logging_config import log_event
    from models.inquiry import Inquiry
    from models.reviewer import Reviewer
    from services.inquiry_notify import notify_new_inquiry_to_group_secretaries

    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="문의 내용을 입력해주세요")

    building = db.query(Building).filter(Building.mgmt_no == body.mgmt_no).first()
    if not building:
        raise HTTPException(status_code=404, detail="건축물을 찾을 수 없습니다")

    reviewer = db.query(Reviewer).filter(Reviewer.user_id == current_user.id).first()
    if reviewer is None or building.reviewer_id != reviewer.id:
        raise HTTPException(
            status_code=403,
            detail="담당 건물에만 문의를 등록할 수 있습니다",
        )

    inquiry = Inquiry(
        building_id=building.id,
        mgmt_no=body.mgmt_no,
        phase=body.phase,
        submitter_id=current_user.id,
        submitter_name=current_user.name,
        content=content,
    )
    db.add(inquiry)
    db.commit()
    db.refresh(inquiry)
    inquiry_id = inquiry.id

    try:
        await notify_new_inquiry_to_group_secretaries(
            db,
            inquiry=inquiry,
            reviewer=reviewer,
        )
        db.commit()
    except Exception as exc:
        # 문의 저장은 이미 완료된 상태다. 알림 예외가 사용자 저장 성공을 막지 않게 한다.
        db.rollback()
        log_event(
            "error", "new_inquiry_notify_unhandled",
            inquiry_id=inquiry_id, reason=str(exc),
        )

    # inquiry.id 를 반환해 프론트가 바로 첨부 업로드를 이어갈 수 있게 한다
    return {"message": "문의가 등록되었습니다", "id": inquiry_id}


@router.patch("/inquiry/{inquiry_id}/content")
def update_inquiry_content(
    inquiry_id: int,
    body: InquiryContentUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """문의 본문 수정.

    작성자는 완료 전 문의만 수정할 수 있고, 간사 이상은 가시 범위 내 문의를 수정할 수 있다.
    """
    from models.inquiry import Inquiry, InquiryStatus

    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="문의 내용을 입력해주세요")

    inquiry = db.query(Inquiry).filter(Inquiry.id == inquiry_id).first()
    if not inquiry:
        raise HTTPException(status_code=404, detail="문의를 찾을 수 없습니다")

    is_owner = inquiry.submitter_id == current_user.id
    can_manage = _can_manage_inquiry(inquiry, current_user, db)
    if not is_owner and not can_manage:
        raise HTTPException(status_code=403, detail="수정 권한이 없습니다")
    if is_owner and not can_manage and inquiry.status == InquiryStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="완료된 문의는 수정할 수 없습니다")

    inquiry.content = content
    db.commit()
    db.refresh(inquiry)
    return {"message": "문의가 수정되었습니다", "id": inquiry.id, "content": inquiry.content}


@router.delete("/inquiry/{inquiry_id}", status_code=204)
def delete_inquiry(
    inquiry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """문의 삭제.

    작성자는 완료 전 문의만 삭제할 수 있고, 간사 이상은 가시 범위 내 문의를 삭제할 수 있다.
    첨부 파일은 S3 삭제를 시도하되 실패해도 DB 삭제를 막지 않는다.
    """
    from models.inquiry import Inquiry, InquiryAttachment, InquiryStatus

    inquiry = db.query(Inquiry).filter(Inquiry.id == inquiry_id).first()
    if not inquiry:
        raise HTTPException(status_code=404, detail="문의를 찾을 수 없습니다")

    is_owner = inquiry.submitter_id == current_user.id
    can_manage = _can_manage_inquiry(inquiry, current_user, db)
    if not is_owner and not can_manage:
        raise HTTPException(status_code=403, detail="삭제 권한이 없습니다")
    if is_owner and not can_manage and inquiry.status == InquiryStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="완료된 문의는 삭제할 수 없습니다")

    attachments = (
        db.query(InquiryAttachment)
        .filter(InquiryAttachment.inquiry_id == inquiry.id)
        .all()
    )
    for att in attachments:
        try:
            delete_file(att.s3_key)
        except Exception:
            pass
        db.delete(att)
    db.delete(inquiry)
    db.commit()


@router.patch("/inquiry/{inquiry_id}")
async def update_inquiry(
    inquiry_id: int,
    body: InquiryUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(
            UserRole.TEAM_LEADER,
            UserRole.CHIEF_SECRETARY,
            UserRole.SECRETARY,
        )
    ),
):
    """문의사항 답변/상태/단계 변경.

    `new_phase`가 주어지면 해당 건물의 current_phase를 갱신하고, 본 문의 상태는
    자동으로 COMPLETED 로 설정된다. 건물 단계 변경 권한은 상위 라우터의
    require_roles 와 동일한 관리자군(팀장/총괄간사/간사)에서 이미 강제된다.

    inquiry가 이번 호출로 COMPLETED 로 전환되는 순간 작성자(검토위원)에게
    카카오톡 답변 완료 알림을 전송한다. 알림 실패는 inquiry 저장을 막지 않는다.
    """
    from models.inquiry import Inquiry, InquiryStatus
    from services.inquiry_notify import notify_inquiry_reply

    inquiry = db.query(Inquiry).filter(Inquiry.id == inquiry_id).first()
    if not inquiry:
        raise HTTPException(status_code=404, detail="문의를 찾을 수 없습니다")
    if not _can_manage_inquiry(inquiry, current_user, db):
        raise HTTPException(status_code=403, detail="수정 권한이 없습니다")

    previous_status = inquiry.status
    phase_changed = False

    if body.reply is not None:
        inquiry.reply = body.reply

    if body.new_phase is not None:
        new_phase = body.new_phase.strip()
        if not new_phase:
            raise HTTPException(status_code=400, detail="변경할 단계를 선택해주세요")
        building = (
            db.query(Building).filter(Building.id == inquiry.building_id).first()
        )
        if not building:
            raise HTTPException(status_code=404, detail="건축물을 찾을 수 없습니다")
        if building.current_phase != new_phase:
            try:
                transition_phase(
                    db, building, to_phase=new_phase, trigger="manual",
                    actor_user_id=current_user.id,
                    reason=f"inquiry_reply:#{inquiry.id}",
                )
            except InvalidPhaseTransition as exc:
                current_label = _PHASE_LABELS.get(
                    building.current_phase or "",
                    building.current_phase or "-",
                )
                target_label = _PHASE_LABELS.get(new_phase, new_phase)
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"현재 단계({current_label})에서 {target_label}(으)로 "
                        "변경할 수 없습니다. 가능한 인접 단계만 선택해주세요."
                    ),
                ) from exc
            phase_changed = True
        inquiry.status = InquiryStatus.COMPLETED
    elif body.status:
        inquiry.status = InquiryStatus(body.status)

    db.commit()
    db.refresh(inquiry)

    if (
        previous_status != InquiryStatus.COMPLETED
        and inquiry.status == InquiryStatus.COMPLETED
    ):
        await notify_inquiry_reply(
            db, current_user, inquiry, phase_changed=phase_changed
        )
        db.commit()

    return {"message": "업데이트 되었습니다"}


@router.get("/inquiries")
def list_inquiries(
    status_filter: str = "active",
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
    """문의사항 목록 조회. 간사(조 배정)는 같은 조 건물의 문의만 노출."""
    from models.inquiry import Inquiry, InquiryStatus

    query = db.query(Inquiry)

    visibility = _inquiry_visibility_filter(current_user)
    if visibility is not None:
        query = query.filter(visibility)

    if status_filter == "active":
        query = query.filter(Inquiry.status.in_([InquiryStatus.OPEN, InquiryStatus.ASKING_AGENCY]))
    elif status_filter == "closed":
        query = query.filter(Inquiry.status == InquiryStatus.COMPLETED)

    total = query.count()
    items = query.order_by(Inquiry.created_at.desc()).offset((page - 1) * size).limit(size).all()

    # 인라인 단계 변경 UI에서 초기값으로 노출하기 위해 현재 단계를 함께 내려준다
    building_ids = {i.building_id for i in items}
    current_phase_map: dict[int, str | None] = {}
    if building_ids:
        rows = (
            db.query(Building.id, Building.current_phase)
            .filter(Building.id.in_(building_ids))
            .all()
        )
        current_phase_map = {bid: phase for bid, phase in rows}

    att_map = _inquiry_attachments_map(db, [i.id for i in items])

    result = []
    for inq in items:
        result.append({
            "id": inq.id,
            "building_id": inq.building_id,
            "mgmt_no": inq.mgmt_no,
            "phase": inq.phase,
            "current_phase": current_phase_map.get(inq.building_id),
            "submitter_id": inq.submitter_id,
            "submitter_name": inq.submitter_name,
            "content": inq.content,
            "reply": inq.reply,
            "status": inq.status.value,
            "created_at": str(inq.created_at),
            "updated_at": str(inq.updated_at),
            "attachments": [
                _inquiry_attachment_to_dict(a) for a in att_map.get(inq.id, [])
            ],
        })

    return {"items": result, "total": total}


@router.get("/my-inquiries")
def list_my_inquiries(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """내가 작성한 문의사항 목록 (모든 로그인 사용자).

    작성자 식별은 `submitter_id == current_user.id`만 사용.
    이름 기반 매칭(submitter_name)은 동명이인 위험으로 제거.
    submitter_id가 NULL인 historical 데이터는 본 목록에 노출되지 않는다.
    """
    from models.inquiry import Inquiry

    query = db.query(Inquiry).filter(Inquiry.submitter_id == current_user.id)
    total = query.count()
    items = (
        query.order_by(Inquiry.created_at.desc())
        .offset((page - 1) * size).limit(size).all()
    )
    att_map = _inquiry_attachments_map(db, [i.id for i in items])
    return {
        "items": [
            {
                "id": inq.id,
                "building_id": inq.building_id,
                "mgmt_no": inq.mgmt_no,
                "phase": inq.phase,
                "submitter_id": inq.submitter_id,
                "submitter_name": inq.submitter_name,
                "content": inq.content,
                "reply": inq.reply,
                "status": inq.status.value,
                "created_at": str(inq.created_at),
                "updated_at": str(inq.updated_at),
                "attachments": [
                    _inquiry_attachment_to_dict(a) for a in att_map.get(inq.id, [])
                ],
            }
            for inq in items
        ],
        "total": total,
    }


@router.get("/building-inquiries/{mgmt_no}")
def get_building_inquiries(
    mgmt_no: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """건물별 문의사항 이력 조회.

    가시성 정책: REVIEWER 는 본인 reviewer_id, SECRETARY(조 배정) 는 같은 조 건물,
    팀장/총괄간사/조 미배정 간사는 전체. 위반 시 404.
    """
    from models.inquiry import Inquiry, InquiryAttachment

    building = db.query(Building).filter(Building.mgmt_no == mgmt_no).first()
    if not building:
        raise HTTPException(status_code=404, detail="건축물을 찾을 수 없습니다")
    if not is_building_visible_to(current_user, building, db):
        raise HTTPException(status_code=404, detail="건축물을 찾을 수 없습니다")
    _ensure_reviewer_can_access_building(building, current_user, db)

    items = (
        db.query(Inquiry)
        .filter(Inquiry.mgmt_no == mgmt_no)
        .order_by(Inquiry.created_at.desc())
        .all()
    )
    att_map = _inquiry_attachments_map(db, [i.id for i in items])
    return [
        {
            "id": inq.id,
            "submitter_id": inq.submitter_id,
            "phase": inq.phase,
            "submitter_name": inq.submitter_name,
            "content": inq.content,
            "reply": inq.reply,
            "status": inq.status.value,
            "created_at": str(inq.created_at),
            "updated_at": str(inq.updated_at),
            "attachments": [
                _inquiry_attachment_to_dict(a) for a in att_map.get(inq.id, [])
            ],
        }
        for inq in items
    ]


# ---- 문의사항 첨부파일 ----

class InquiryAttachmentResponse(BaseModel):
    id: int
    inquiry_id: int
    kind: str  # "question" | "reply"
    filename: str
    file_size: int
    content_type: str | None = None
    uploaded_by: int
    created_at: datetime
    download_url: str | None = None


def _inquiry_attachment_to_dict(att) -> dict:
    return {
        "id": att.id,
        "inquiry_id": att.inquiry_id,
        "kind": att.kind.value if hasattr(att.kind, "value") else str(att.kind),
        "filename": att.filename,
        "file_size": att.file_size,
        "content_type": att.content_type,
        "uploaded_by": att.uploaded_by,
        "created_at": att.created_at.isoformat() if att.created_at else None,
        "download_url": get_download_url(att.s3_key),
    }


def _inquiry_attachments_map(db: Session, inquiry_ids: list[int]) -> dict[int, list]:
    """inquiry_id → [InquiryAttachment, ...] 맵을 한 번의 쿼리로 생성."""
    from models.inquiry import InquiryAttachment
    if not inquiry_ids:
        return {}
    rows = (
        db.query(InquiryAttachment)
        .filter(InquiryAttachment.inquiry_id.in_(inquiry_ids))
        .order_by(InquiryAttachment.created_at)
        .all()
    )
    out: dict[int, list] = {}
    for a in rows:
        out.setdefault(a.inquiry_id, []).append(a)
    return out


@router.post(
    "/inquiry/{inquiry_id}/attachments",
    response_model=InquiryAttachmentResponse,
    status_code=201,
)
async def upload_inquiry_attachment(
    inquiry_id: int,
    kind: str = Query(..., description="question | reply"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """문의사항 첨부 업로드.

    - kind="question": 문의 작성자(submitter_id == current_user.id) 만 허용
    - kind="reply": 간사 이상(TEAM_LEADER/CHIEF_SECRETARY/SECRETARY) 만 허용
    """
    from models.inquiry import Inquiry, InquiryAttachment, InquiryAttachmentKind

    if kind not in {"question", "reply"}:
        raise HTTPException(status_code=400, detail="kind 는 question 또는 reply")

    inquiry = db.query(Inquiry).filter(Inquiry.id == inquiry_id).first()
    if not inquiry:
        raise HTTPException(status_code=404, detail="문의를 찾을 수 없습니다")

    if kind == "question":
        if inquiry.submitter_id != current_user.id:
            raise HTTPException(
                status_code=403, detail="문의 작성자만 질문 첨부를 올릴 수 있습니다"
            )
    else:  # reply
        if current_user.role not in (
            UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY, UserRole.SECRETARY
        ):
            raise HTTPException(status_code=403, detail="답변 첨부 권한이 없습니다")

    if not file.filename:
        raise HTTPException(status_code=400, detail="파일이 없습니다")

    suffix = Path(file.filename).suffix
    tmp_path = await stream_upload_to_tempfile(file, max_mb=20, suffix=suffix)
    try:
        unique = uuid.uuid4().hex[:8]
        s3_key = f"inquiries/{inquiry_id}/{kind}/{unique}_{file.filename}"
        resolved_type = file.content_type or "application/octet-stream"
        upload_generic_file(tmp_path, s3_key, content_type=resolved_type)

        att = InquiryAttachment(
            inquiry_id=inquiry_id,
            kind=InquiryAttachmentKind(kind),
            filename=file.filename,
            s3_key=s3_key,
            file_size=tmp_path.stat().st_size,
            content_type=resolved_type,
            uploaded_by=current_user.id,
        )
        db.add(att)
        db.commit()
        db.refresh(att)
        return InquiryAttachmentResponse(**_inquiry_attachment_to_dict(att))
    finally:
        tmp_path.unlink(missing_ok=True)


@router.delete("/inquiry-attachments/{attachment_id}", status_code=204)
def delete_inquiry_attachment(
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from models.inquiry import InquiryAttachment

    att = (
        db.query(InquiryAttachment)
        .filter(InquiryAttachment.id == attachment_id)
        .first()
    )
    if not att:
        raise HTTPException(status_code=404, detail="첨부파일을 찾을 수 없습니다")

    is_owner = att.uploaded_by == current_user.id
    is_admin = current_user.role in (UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    if not is_owner and not is_admin:
        raise HTTPException(status_code=403, detail="삭제 권한이 없습니다")

    try:
        delete_file(att.s3_key)
    except Exception:
        pass
    db.delete(att)
    db.commit()


@router.get("/inquiry-attachments/{attachment_id}/download")
def download_inquiry_attachment(
    attachment_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    from models.inquiry import InquiryAttachment

    att = (
        db.query(InquiryAttachment)
        .filter(InquiryAttachment.id == attachment_id)
        .first()
    )
    if not att:
        raise HTTPException(status_code=404, detail="첨부파일을 찾을 수 없습니다")
    return {"download_url": get_download_url(att.s3_key), "filename": att.filename}


@router.get("/download/{stage_id}")
def download_review(
    stage_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """검토서 파일 다운로드 (S3 presigned URL 반환). REVIEWER는 본인 담당 stage만."""
    stage = db.query(ReviewStage).filter(ReviewStage.id == stage_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="검토 단계를 찾을 수 없습니다")
    if not stage.s3_file_key:
        raise HTTPException(status_code=404, detail="업로드된 검토서가 없습니다")

    building = db.query(Building).filter(Building.id == stage.building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="검토 단계를 찾을 수 없습니다")
    _ensure_reviewer_can_access_building(building, current_user, db)

    url = get_download_url(stage.s3_file_key)
    if not url:
        return {"download_url": None, "message": "S3가 설정되지 않았습니다 (로컬 모드)"}
    return {"download_url": url}


@router.post("/advance/{building_id}")
def advance_phase(
    building_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY, UserRole.SECRETARY)
    ),
):
    """건축물의 검토 단계를 다음 단계로 전환 (간사 이상)"""
    building = db.query(Building).filter(Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="건축물을 찾을 수 없습니다")

    if not building.current_phase:
        raise HTTPException(status_code=400, detail="현재 진행 중인 단계가 없습니다")

    # 현재 단계의 최신 결과 확인
    try:
        current_phase_type = PhaseType(building.current_phase)
    except ValueError:
        raise HTTPException(status_code=400, detail="알 수 없는 단계입니다")

    current_stage = (
        db.query(ReviewStage)
        .filter(
            ReviewStage.building_id == building.id,
            ReviewStage.phase == current_phase_type,
        )
        .first()
    )

    if not current_stage or not current_stage.result:
        raise HTTPException(status_code=400, detail="현재 단계의 검토 결과가 없습니다")

    # 완료 결과면 최종 판정 처리
    if is_completed(current_stage.result):
        building.final_result = current_stage.result.value
        db.commit()
        return {"message": "최종 판정 완료", "final_result": current_stage.result.value}

    # 보완 필요 시 다음 단계로 전환 (간사 수동 → MANUAL 트리거)
    if can_advance(current_stage.result):
        next_phase = get_next_phase(current_phase_type)
        if not next_phase:
            raise HTTPException(status_code=400, detail="더 이상 진행할 단계가 없습니다")
        next_phase_str = next_phase.value if hasattr(next_phase, "value") else str(next_phase)
        try:
            transition_phase(
                db, building, to_phase=next_phase_str, trigger="manual",
                actor_user_id=current_user.id,
                reason="advance_button",
            )
        except InvalidPhaseTransition as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        db.commit()
        return {"message": f"다음 단계로 전환: {next_phase_str}", "next_phase": next_phase_str}

    raise HTTPException(status_code=400, detail="단계 전환 조건이 충족되지 않았습니다")


# ==============================
# 부적합 대상 검토 (간사 이상)
# ==============================

from models.review_stage import InappropriateDecision  # noqa: E402


class InappropriateReviewItem(BaseModel):
    stage_id: int
    building_id: int
    mgmt_no: str
    building_name: str | None = None
    full_address: str | None = None
    gross_area: float | None = None
    floors_above: int | None = None
    is_special_structure: bool | None = None
    is_high_rise: bool | None = None
    is_multi_use: bool | None = None
    current_phase: str | None = None
    latest_result: str | None = None
    inappropriate_decision: str | None = None
    latest_note: str | None = None
    latest_note_author: str | None = None
    note_count: int = 0
    phase: str


class InappropriateReviewListResponse(BaseModel):
    items: list[InappropriateReviewItem]
    total: int


def _address_of(b: Building) -> str | None:
    parts: list[str] = []
    for v in (b.sido, b.sigungu, b.beopjeongdong):
        if v:
            parts.append(str(v))
    main = b.main_lot_no or ""
    sub = b.sub_lot_no or ""
    if main and sub:
        parts.append(f"{main}-{sub}")
    elif main:
        parts.append(str(main))
    if b.special_lot_no:
        parts.append(str(b.special_lot_no))
    return " ".join(parts) if parts else None


@router.get("/inappropriate", response_model=InappropriateReviewListResponse)
def list_inappropriate_reviews(
    decision: str | None = None,
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
    """부적합 검토 필요로 체크된 stage 목록 (간사 이상).

    간사(조 배정)는 같은 조 건물의 stage 만 노출.
    decision: 'pending' | 'confirmed' | 'rejected' 필터링 (선택)
    """
    query = (
        db.query(ReviewStage, Building)
        .join(Building, ReviewStage.building_id == Building.id)
        .filter(ReviewStage.inappropriate_review_needed.is_(True))
    )

    visibility = building_visibility_filter(current_user)
    if visibility is not None:
        query = query.filter(visibility)

    if decision == "pending":
        query = query.filter(
            (ReviewStage.inappropriate_decision.is_(None))
            | (ReviewStage.inappropriate_decision == InappropriateDecision.PENDING)
        )
    elif decision == "confirmed_serious":
        query = query.filter(ReviewStage.inappropriate_decision == InappropriateDecision.CONFIRMED_SERIOUS)
    elif decision == "confirmed_simple":
        query = query.filter(ReviewStage.inappropriate_decision == InappropriateDecision.CONFIRMED_SIMPLE)
    elif decision == "excluded":
        query = query.filter(ReviewStage.inappropriate_decision == InappropriateDecision.EXCLUDED)

    rows = query.order_by(Building.mgmt_no, ReviewStage.phase_order.desc()).all()
    # 건물별 최신 stage만
    latest_by_building: dict[int, tuple[ReviewStage, Building]] = {}
    for stage, building in rows:
        if building.id not in latest_by_building:
            latest_by_building[building.id] = (stage, building)

    # 각 stage의 최신 의견과 개수 조회
    stage_ids = [s.id for s, _ in latest_by_building.values()]
    latest_note_by_stage: dict[int, InappropriateNote] = {}
    note_count_by_stage: dict[int, int] = {}
    if stage_ids:
        notes = (
            db.query(InappropriateNote)
            .filter(InappropriateNote.stage_id.in_(stage_ids))
            .order_by(InappropriateNote.stage_id, InappropriateNote.created_at.desc())
            .all()
        )
        for n in notes:
            note_count_by_stage[n.stage_id] = note_count_by_stage.get(n.stage_id, 0) + 1
            if n.stage_id not in latest_note_by_stage:
                latest_note_by_stage[n.stage_id] = n

    items = []
    for stage, b in latest_by_building.values():
        latest_note = latest_note_by_stage.get(stage.id)
        items.append(
            InappropriateReviewItem(
                stage_id=stage.id,
                building_id=b.id,
                mgmt_no=b.mgmt_no,
                building_name=b.building_name,
                full_address=_address_of(b),
                gross_area=float(b.gross_area) if b.gross_area is not None else None,
                floors_above=b.floors_above,
                is_special_structure=b.is_special_structure,
                is_high_rise=b.is_high_rise,
                is_multi_use=b.is_multi_use,
                current_phase=b.current_phase,
                latest_result=stage.result.value if stage.result else None,
                inappropriate_decision=(
                    stage.inappropriate_decision.value
                    if stage.inappropriate_decision
                    else "pending"
                ),
                latest_note=latest_note.content if latest_note else None,
                latest_note_author=latest_note.author_name if latest_note else None,
                note_count=note_count_by_stage.get(stage.id, 0),
                phase=stage.phase.value,
            )
        )
    return InappropriateReviewListResponse(items=items, total=len(items))


class InappropriateDecisionRequest(BaseModel):
    decision: str  # pending / confirmed_serious / confirmed_simple / excluded


@router.patch("/inappropriate/{stage_id}")
def set_inappropriate_decision(
    stage_id: int,
    body: InappropriateDecisionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY, UserRole.SECRETARY)
    ),
):
    """부적합 검토 판정 변경 (간사 이상)."""
    try:
        new_decision = InappropriateDecision(body.decision)
    except ValueError:
        raise HTTPException(status_code=400, detail="잘못된 판정값")

    stage = db.query(ReviewStage).filter(ReviewStage.id == stage_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="검토 단계를 찾을 수 없습니다")
    if not stage.inappropriate_review_needed:
        raise HTTPException(status_code=400, detail="부적합 검토 대상이 아닙니다")

    stage.inappropriate_decision = new_decision
    log_action(
        db, current_user.id, "inappropriate_decision", "review_stage", stage.id,
        after_data={"decision": new_decision.value},
    )
    db.commit()
    return {"stage_id": stage.id, "decision": new_decision.value}


# --- 간사진 의견 (다중, 작성자 기록) ---

from models.inappropriate_note import InappropriateNote  # noqa: E402


class InappropriateNoteResponse(BaseModel):
    id: int
    stage_id: int
    author_id: int
    author_name: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class InappropriateNoteCreate(BaseModel):
    content: str


@router.get("/inappropriate/{stage_id}/notes", response_model=list[InappropriateNoteResponse])
def list_inappropriate_notes(
    stage_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(
        require_roles(
            UserRole.TEAM_LEADER,
            UserRole.CHIEF_SECRETARY,
            UserRole.SECRETARY,
            UserRole.MANAGER,
        )
    ),
):
    """부적합 stage의 간사진 의견 목록 (최신순)"""
    notes = (
        db.query(InappropriateNote)
        .filter(InappropriateNote.stage_id == stage_id)
        .order_by(InappropriateNote.created_at.desc())
        .all()
    )
    return notes


@router.post("/inappropriate/{stage_id}/notes", response_model=InappropriateNoteResponse)
def create_inappropriate_note(
    stage_id: int,
    body: InappropriateNoteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY, UserRole.SECRETARY)
    ),
):
    """간사진 의견 추가"""
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="내용을 입력하세요")

    stage = db.query(ReviewStage).filter(ReviewStage.id == stage_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="검토 단계를 찾을 수 없습니다")
    if not stage.inappropriate_review_needed:
        raise HTTPException(status_code=400, detail="부적합 검토 대상이 아닙니다")

    note = InappropriateNote(
        stage_id=stage_id,
        author_id=current_user.id,
        author_name=current_user.name,
        content=content,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@router.delete("/inappropriate/notes/{note_id}", status_code=204)
def delete_inappropriate_note(
    note_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY, UserRole.SECRETARY)
    ),
):
    """의견 삭제 (작성자 본인 또는 팀장/총괄간사)"""
    note = db.query(InappropriateNote).filter(InappropriateNote.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="의견을 찾을 수 없습니다")
    is_owner = note.author_id == current_user.id
    is_admin = current_user.role in (UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    if not is_owner and not is_admin:
        raise HTTPException(status_code=403, detail="삭제 권한이 없습니다")
    db.delete(note)
    db.commit()
