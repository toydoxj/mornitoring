"""검토서 업로드/조회 라우터"""

import tempfile
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models.building import Building
from models.review_stage import ReviewStage, PhaseType
from models.user import User, UserRole
from routers.auth import get_current_user, require_roles
from engines.review_validator import validate_review_file
from engines.review_extractor import extract_review_data
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

    model_config = {"from_attributes": True}


class FieldChange(BaseModel):
    field: str
    label: str
    old_value: str | None = None
    new_value: str | None = None


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

    with tempfile.NamedTemporaryFile(suffix=Path(file.filename).suffix, delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        validation = validate_review_file(
            file_path=tmp_path, filename=file.filename,
            expected_mgmt_no=mgmt_no, submitter_name=current_user.name,
        )

        if not validation.is_valid:
            return UploadResponse(success=False, message="유효성 검증 실패", errors=validation.errors)

        # 변경사항 감지
        extracted_data = validation.extracted_data
        changes = _detect_changes(building, extracted_data)

        return UploadResponse(
            success=True,
            message="검증 통과. 변경사항을 확인하고 업로드 버튼을 눌러주세요.",
            warnings=validation.warnings,
            changes=changes,
        )
    finally:
        tmp_path.unlink(missing_ok=True)


def _detect_changes(building: Building, extracted_data: dict) -> list[FieldChange]:
    """건축물 정보 변경사항 감지"""
    BUILDING_UPDATE_MAP = {
        "architect_firm": ("architect_firm", "건축사(소속)"),
        "architect_name": ("architect_name", "건축사(성명)"),
        "struct_eng_firm": ("struct_eng_firm", "책임구조기술자(소속)"),
        "struct_eng_name": ("struct_eng_name", "책임구조기술자(성명)"),
        "main_structure_type": ("main_structure", "주요 구조형식"),
        "high_risk_type": ("high_risk_type", "고위험유형"),
        "struct_drawing_qual": ("seismic_level", "내진등급"),
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

    for extract_key, (db_field, label) in {**BUILDING_UPDATE_MAP, **DETAIL_CATEGORY_MAP}.items():
        new_val = extracted_data.get(extract_key)
        if not new_val:
            continue
        old_val = getattr(building, db_field, None)
        if old_val and old_val != new_val:
            changes.append(FieldChange(field=db_field, label=label, old_value=str(old_val), new_value=new_val))
        elif not old_val:
            changes.append(FieldChange(field=db_field, label=f"{label} (신규)", old_value="-", new_value=new_val))

    if extracted_data.get("type_is_piloti") and not building.detail_category9:
        changes.append(FieldChange(field="detail_category9", label="필로티 (신규)", old_value="-", new_value="필로티"))

    return changes


def _apply_changes(building: Building, extracted_data: dict):
    """건축물 정보 변경 적용"""
    BUILDING_UPDATE_MAP = {
        "architect_firm": "architect_firm",
        "architect_name": "architect_name",
        "struct_eng_firm": "struct_eng_firm",
        "struct_eng_name": "struct_eng_name",
        "main_structure_type": "main_structure",
        "high_risk_type": "high_risk_type",
        "struct_drawing_qual": "seismic_level",
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

    # 임시 파일 저장
    with tempfile.NamedTemporaryFile(suffix=Path(file.filename).suffix, delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        # 1. 유효성 검증
        validation = validate_review_file(
            file_path=tmp_path,
            filename=file.filename,
            expected_mgmt_no=mgmt_no,
            submitter_name=current_user.name,
        )

        if not validation.is_valid:
            return UploadResponse(
                success=False,
                message="유효성 검증 실패",
                errors=validation.errors,
            )

        # 2. 검토서 내용 추출
        extracted = extract_review_data(tmp_path)

        # 3. PhaseType 변환 (접수 단계는 검토서 제출 단계로 매핑)
        RECEIVED_TO_SUBMIT = {
            "doc_received": "preliminary",
            "supplement_1_received": "supplement_1",
            "supplement_2_received": "supplement_2",
            "supplement_3_received": "supplement_3",
            "supplement_4_received": "supplement_4",
            "supplement_5_received": "supplement_5",
        }
        actual_phase = RECEIVED_TO_SUBMIT.get(phase, phase)
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
            # 기존 단계 업데이트
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
            stage.s3_file_key = upload_review_file(tmp_path, mgmt_no, actual_phase, file.filename)
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

        # 6. 건축물 정보 변경 적용
        _apply_changes(building, validation.extracted_data)
        changes = _detect_changes(building, validation.extracted_data)

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
    delete_after: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """검토서 파일 다운로드 URL 생성 (다운 후 삭제 옵션)"""
    url = get_download_url(key)
    if not url:
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다")

    if delete_after:
        delete_file(key)
        # DB에서도 s3_file_key 제거
        stage = db.query(ReviewStage).filter(ReviewStage.s3_file_key == key).first()
        if stage:
            stage.s3_file_key = None
            db.commit()

    return {"download_url": url, "deleted": delete_after}


@router.get("/stages/{building_id}", response_model=list[ReviewStageResponse])
def get_review_stages(
    building_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """건축물의 검토 단계 목록 조회"""
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

    담당 판정:
    - Building.reviewer_id 가 로그인 사용자의 Reviewer 레코드와 일치, 또는
    - Building.assigned_reviewer_name 이 로그인 사용자 이름과 일치

    역할(role)은 무관. 간사/총괄간사/팀장도 검토위원 역할로 배정되었으면 문의 가능.
    """
    from models.inquiry import Inquiry
    from models.reviewer import Reviewer

    building = db.query(Building).filter(Building.mgmt_no == body.mgmt_no).first()
    if not building:
        raise HTTPException(status_code=404, detail="관리번호를 찾을 수 없습니다")

    # 담당 여부 확인
    is_assigned = False
    reviewer = db.query(Reviewer).filter(Reviewer.user_id == current_user.id).first()
    if reviewer and building.reviewer_id == reviewer.id:
        is_assigned = True
    elif building.assigned_reviewer_name == current_user.name:
        is_assigned = True

    if not is_assigned:
        raise HTTPException(
            status_code=403,
            detail="담당 건물에만 문의를 등록할 수 있습니다",
        )

    inquiry = Inquiry(
        building_id=building.id,
        mgmt_no=body.mgmt_no,
        phase=body.phase,
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


@router.get("/building-inquiries/{mgmt_no}")
def get_building_inquiries(
    mgmt_no: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """건물별 문의사항 이력 조회"""
    from models.inquiry import Inquiry

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
    """검토서 파일 다운로드 (S3 presigned URL 반환)"""
    stage = db.query(ReviewStage).filter(ReviewStage.id == stage_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="검토 단계를 찾을 수 없습니다")
    if not stage.s3_file_key:
        raise HTTPException(status_code=404, detail="업로드된 검토서가 없습니다")

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
