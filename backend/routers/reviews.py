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
from services.s3_storage import upload_review_file, get_download_url
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


class UploadResponse(BaseModel):
    success: bool
    message: str
    errors: list[str] = []
    stage_id: int | None = None


PHASE_ORDER_MAP = {
    "preliminary": 0,
    "supplement_1": 1,
    "supplement_2": 2,
    "supplement_3": 3,
    "supplement_4": 4,
    "supplement_5": 5,
}


@router.post("/upload", response_model=UploadResponse)
async def upload_review(
    file: UploadFile = File(...),
    mgmt_no: str = Query(..., description="관리번호"),
    phase: str = Query(..., description="검토 단계"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.REVIEWER)),
):
    """검토서 업로드 + 유효성 검증 + DB 반영"""

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

        # 3. PhaseType 변환
        try:
            phase_type = PhaseType(phase)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"잘못된 검토 단계: {phase}")

        phase_order = PHASE_ORDER_MAP.get(phase, 0)

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
            stage.s3_file_key = upload_review_file(tmp_path, mgmt_no, phase, file.filename)
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
                s3_file_key=upload_review_file(tmp_path, mgmt_no, phase, file.filename),
            )
            db.add(stage)

        # 5. 건축물 현재 단계 업데이트
        building.current_phase = phase

        log_action(db, current_user.id, "upload", "review_stage", stage.id,
                   after_data={"mgmt_no": mgmt_no, "phase": phase})
        db.commit()
        db.refresh(stage)

        return UploadResponse(
            success=True,
            message=f"검토서가 제출되었습니다 (관리번호: {mgmt_no}, 단계: {phase})",
            stage_id=stage.id,
        )

    finally:
        tmp_path.unlink(missing_ok=True)


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


class NotSubmittedReasonRequest(BaseModel):
    mgmt_no: str
    phase: str
    reason: str


@router.post("/not-submitted-reason")
def save_not_submitted_reason(
    body: NotSubmittedReasonRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """검토서 미제출 사유 저장"""
    building = db.query(Building).filter(Building.mgmt_no == body.mgmt_no).first()
    if not building:
        raise HTTPException(status_code=404, detail="관리번호를 찾을 수 없습니다")

    try:
        phase_type = PhaseType(body.phase)
    except ValueError:
        phase_type = PhaseType.PRELIMINARY

    phase_order = PHASE_ORDER_MAP.get(body.phase, 0)

    stage = (
        db.query(ReviewStage)
        .filter(ReviewStage.building_id == building.id, ReviewStage.phase == phase_type)
        .first()
    )

    if stage:
        stage.stage_remarks = body.reason
    else:
        stage = ReviewStage(
            building_id=building.id,
            phase=phase_type,
            phase_order=phase_order,
            stage_remarks=body.reason,
            reviewer_name=current_user.name,
        )
        db.add(stage)

    db.commit()
    return {"message": "미제출 사유가 저장되었습니다"}


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
