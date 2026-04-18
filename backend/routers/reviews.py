"""검토서 업로드/조회 라우터"""

import tempfile
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models.building import Building
from models.review_stage import ReviewStage, PhaseType
from models.reviewer import Reviewer
from models.user import User, UserRole
from routers.auth import get_current_user, require_roles
from engines.review_validator import validate_review_file
from engines.review_extractor import extract_review_data


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

# 판정결과 한글 라벨
_RESULT_KOREAN = {
    "pass": "적합",
    "simple_error": "단순오류",
    "recalculate": "재계산",
}
from engines.phase_machine import get_next_phase, can_advance, is_completed
from services.s3_storage import upload_review_file, get_download_url, list_review_files, delete_file
from services.audit import log_action

router = APIRouter()


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
    review_opinion: str | None = None
    s3_file_key: str | None = None
    inappropriate_review_needed: bool = False
    inappropriate_decision: str | None = None

    model_config = {"from_attributes": True}


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
    _ensure_reviewer_can_access_building(building, current_user, db)

    with tempfile.NamedTemporaryFile(suffix=Path(file.filename).suffix, delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        # 업로드 단계 매핑 (receive → submit)
        RECEIVED_TO_SUBMIT = {
            "doc_received": "preliminary",
            "supplement_1_received": "supplement_1",
            "supplement_2_received": "supplement_2",
            "supplement_3_received": "supplement_3",
            "supplement_4_received": "supplement_4",
            "supplement_5_received": "supplement_5",
        }
        target_phase = RECEIVED_TO_SUBMIT.get(phase, phase)

        validation = validate_review_file(
            file_path=tmp_path, filename=file.filename,
            expected_mgmt_no=mgmt_no, submitter_name=current_user.name,
            expected_phase=target_phase,
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
    _ensure_reviewer_can_access_building(building, current_user, db)

    # 임시 파일 저장
    with tempfile.NamedTemporaryFile(suffix=Path(file.filename).suffix, delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        # 1. PhaseType 변환 (접수 단계 → 검토서 제출 단계)
        RECEIVED_TO_SUBMIT = {
            "doc_received": "preliminary",
            "supplement_1_received": "supplement_1",
            "supplement_2_received": "supplement_2",
            "supplement_3_received": "supplement_3",
            "supplement_4_received": "supplement_4",
            "supplement_5_received": "supplement_5",
        }
        actual_phase = RECEIVED_TO_SUBMIT.get(phase, phase)

        # 2. 유효성 검증 (expected_phase 기준으로 차수 라벨 체크)
        validation = validate_review_file(
            file_path=tmp_path,
            filename=file.filename,
            expected_mgmt_no=mgmt_no,
            submitter_name=current_user.name,
            expected_phase=actual_phase,
        )

        if not validation.is_valid:
            return UploadResponse(
                success=False,
                message="유효성 검증 실패",
                errors=validation.errors,
            )

        # 3. 검토서 내용 추출
        extracted = extract_review_data(tmp_path)
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
            stage.report_submitted_at = date.today()
            stage.reviewer_name = current_user.name
            if extracted["result"]:
                stage.result = extracted["result"]
            if extracted["defect_type_1"]:
                stage.defect_type_1 = extracted["defect_type_1"]
            if extracted["defect_type_2"]:
                stage.defect_type_2 = extracted["defect_type_2"]
            if extracted["defect_type_3"]:
                stage.defect_type_3 = extracted["defect_type_3"]
            if extracted["review_opinion"]:
                stage.review_opinion = extracted["review_opinion"]
            stage.inappropriate_review_needed = inappropriate_review_needed
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
                report_submitted_at=date.today(),
                reviewer_name=current_user.name,
                result=extracted["result"],
                defect_type_1=extracted["defect_type_1"],
                defect_type_2=extracted["defect_type_2"],
                defect_type_3=extracted["defect_type_3"],
                review_opinion=extracted["review_opinion"],
                inappropriate_review_needed=inappropriate_review_needed,
                s3_file_key=upload_review_file(tmp_path, mgmt_no, actual_phase, file.filename),
            )
            db.add(stage)

        # 5. 건축물 현재 단계 업데이트
        building.current_phase = actual_phase

        # 6. 건축물 정보 변경 적용 — detect를 먼저 호출해야 변경 전 값과 비교 가능.
        # apply가 먼저 setattr하면 _detect_changes의 getattr이 new_val을 읽어 변경이 사라짐.
        changes = _detect_changes(building, validation.extracted_data)
        _apply_changes(building, validation.extracted_data)

        log_action(db, current_user.id, "upload", "review_stage", stage.id,
                   after_data={"mgmt_no": mgmt_no, "phase": phase})
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
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """업로드된 검토서 파일 목록 (총괄간사/팀장)"""
    prefix = "reviews/"
    if phase:
        from services.s3_storage import PHASE_FOLDER_MAP
        phase_folder = PHASE_FOLDER_MAP.get(phase, phase)
        prefix = f"reviews/{phase_folder}/"

    files = list_review_files(prefix)
    return files


@router.get("/files/download")
def download_file(
    key: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """검토서 파일 다운로드 URL 생성 (presigned URL 반환만).

    이전에는 `delete_after=True` 시 presigned URL을 만든 직후 S3 객체를 삭제했는데,
    이는 사용자가 URL을 클릭하기 전에 파일이 사라지는 race를 만들었다(404).
    파일 정리가 필요하면 별도 DELETE 엔드포인트로 분리해야 한다.
    """
    url = get_download_url(key)
    if not url:
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다")
    return {"download_url": url}


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


class InquiryCreateRequest(BaseModel):
    mgmt_no: str
    phase: str
    content: str


class InquiryUpdateRequest(BaseModel):
    reply: str | None = None
    status: str | None = None  # asking_agency / completed / next_phase


@router.post("/inquiry")
def create_inquiry(
    body: InquiryCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """문의사항 등록 — 해당 건물의 담당 검토자만 가능.

    담당 판정은 `Reviewer.user_id == current_user.id` 그리고
    `building.reviewer_id == reviewer.id`. 이름 기반 매칭은 동명이인 위험으로 제거.
    역할(role)은 무관 — REVIEWER가 아닌 사용자도 Reviewer 행이 있으면 문의 가능.
    """
    from models.inquiry import Inquiry
    from models.reviewer import Reviewer

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
        content=body.content,
    )
    db.add(inquiry)
    db.commit()
    return {"message": "문의가 등록되었습니다"}


@router.patch("/inquiry/{inquiry_id}")
def update_inquiry(
    inquiry_id: int,
    body: InquiryUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY, UserRole.SECRETARY)
    ),
):
    """문의사항 답변/상태 변경"""
    from models.inquiry import Inquiry, InquiryStatus

    inquiry = db.query(Inquiry).filter(Inquiry.id == inquiry_id).first()
    if not inquiry:
        raise HTTPException(status_code=404, detail="문의를 찾을 수 없습니다")

    if body.reply is not None:
        inquiry.reply = body.reply
    if body.status:
        inquiry.status = InquiryStatus(body.status)

    db.commit()
    return {"message": "업데이트 되었습니다"}


@router.get("/inquiries")
def list_inquiries(
    status_filter: str = "active",
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY, UserRole.SECRETARY)
    ),
):
    """문의사항 목록 조회"""
    from models.inquiry import Inquiry, InquiryStatus

    query = db.query(Inquiry)

    if status_filter == "active":
        query = query.filter(Inquiry.status.in_([InquiryStatus.OPEN, InquiryStatus.ASKING_AGENCY]))
    elif status_filter == "closed":
        query = query.filter(Inquiry.status.in_([InquiryStatus.COMPLETED, InquiryStatus.NEXT_PHASE]))

    total = query.count()
    items = query.order_by(Inquiry.created_at.desc()).offset((page - 1) * size).limit(size).all()

    result = []
    for inq in items:
        result.append({
            "id": inq.id,
            "mgmt_no": inq.mgmt_no,
            "phase": inq.phase,
            "submitter_name": inq.submitter_name,
            "content": inq.content,
            "reply": inq.reply,
            "status": inq.status.value,
            "created_at": str(inq.created_at),
            "updated_at": str(inq.updated_at),
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
    return {
        "items": [
            {
                "id": inq.id,
                "mgmt_no": inq.mgmt_no,
                "phase": inq.phase,
                "submitter_name": inq.submitter_name,
                "content": inq.content,
                "reply": inq.reply,
                "status": inq.status.value,
                "created_at": str(inq.created_at),
                "updated_at": str(inq.updated_at),
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
    """건물별 문의사항 이력 조회 (REVIEWER는 본인 담당 건물만)"""
    from models.inquiry import Inquiry

    building = db.query(Building).filter(Building.mgmt_no == mgmt_no).first()
    if not building:
        raise HTTPException(status_code=404, detail="건축물을 찾을 수 없습니다")
    _ensure_reviewer_can_access_building(building, current_user, db)

    items = (
        db.query(Inquiry)
        .filter(Inquiry.mgmt_no == mgmt_no)
        .order_by(Inquiry.created_at.desc())
        .all()
    )
    return [
        {
            "id": inq.id,
            "phase": inq.phase,
            "submitter_name": inq.submitter_name,
            "content": inq.content,
            "reply": inq.reply,
            "status": inq.status.value,
            "created_at": str(inq.created_at),
            "updated_at": str(inq.updated_at),
        }
        for inq in items
    ]


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

    # 보완 필요 시 다음 단계로 전환
    if can_advance(current_stage.result):
        next_phase = get_next_phase(current_phase_type)
        if not next_phase:
            raise HTTPException(status_code=400, detail="더 이상 진행할 단계가 없습니다")

        building.current_phase = next_phase.value
        db.commit()
        return {"message": f"다음 단계로 전환: {next_phase.value}", "next_phase": next_phase.value}

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
    _: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY, UserRole.SECRETARY)
    ),
):
    """부적합 검토 필요로 체크된 stage 목록 (간사 이상).

    decision: 'pending' | 'confirmed' | 'rejected' 필터링 (선택)
    """
    query = (
        db.query(ReviewStage, Building)
        .join(Building, ReviewStage.building_id == Building.id)
        .filter(ReviewStage.inappropriate_review_needed.is_(True))
    )

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
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY, UserRole.SECRETARY)
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
