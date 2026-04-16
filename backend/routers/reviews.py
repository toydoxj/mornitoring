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
            # TODO: S3 업로드 후 s3_file_key 저장
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
            )
            db.add(stage)

        # 5. 건축물 현재 단계 업데이트
        building.current_phase = phase

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
