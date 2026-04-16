"""건축물(관리대장) 라우터"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models.building import Building
from models.reviewer import Reviewer
from models.user import User, UserRole
from routers.auth import get_current_user, require_roles
from services.audit import log_action

router = APIRouter()


# --- Pydantic 스키마 ---

class BuildingCreate(BaseModel):
    mgmt_no: str
    building_type: str | None = None
    sido: str | None = None
    sigungu: str | None = None
    beopjeongdong: str | None = None
    building_name: str | None = None
    main_structure: str | None = None
    main_usage: str | None = None
    gross_area: float | None = None
    height: float | None = None
    floors_above: int | None = None
    floors_below: int | None = None
    is_special_structure: bool | None = None
    is_high_rise: bool | None = None
    is_multi_use: bool | None = None
    remarks: str | None = None
    architect_firm: str | None = None
    architect_name: str | None = None
    struct_eng_firm: str | None = None
    struct_eng_name: str | None = None
    high_risk_type: str | None = None


class BuildingUpdate(BaseModel):
    building_name: str | None = None
    sido: str | None = None
    sigungu: str | None = None
    beopjeongdong: str | None = None
    main_structure: str | None = None
    main_usage: str | None = None
    gross_area: float | None = None
    floors_above: int | None = None
    floors_below: int | None = None
    high_risk_type: str | None = None
    reviewer_id: int | None = None
    current_phase: str | None = None
    final_result: str | None = None
    remarks: str | None = None


class BuildingResponse(BaseModel):
    id: int
    mgmt_no: str
    building_name: str | None = None
    sido: str | None = None
    sigungu: str | None = None
    beopjeongdong: str | None = None
    main_lot_no: str | None = None
    sub_lot_no: str | None = None
    special_lot_no: str | None = None
    main_structure: str | None = None
    main_usage: str | None = None
    gross_area: float | None = None
    floors_above: int | None = None
    floors_below: int | None = None
    high_risk_type: str | None = None
    current_phase: str | None = None
    final_result: str | None = None
    reviewer_id: int | None = None
    reviewer_name: str | None = None
    assigned_reviewer_name: str | None = None
    reviewer_registered: bool = False

    model_config = {"from_attributes": True}


def _to_response(building: Building) -> dict:
    """Building 모델을 응답 dict로 변환 (검토위원 이름 + 등록 여부 포함)"""
    data = {c.name: getattr(building, c.name) for c in Building.__table__.columns}
    data["reviewer_name"] = None
    data["reviewer_registered"] = False
    if building.reviewer and building.reviewer.user:
        data["reviewer_name"] = building.reviewer.user.name
        data["reviewer_registered"] = True
    elif building.assigned_reviewer_name:
        data["reviewer_name"] = building.assigned_reviewer_name
        data["reviewer_registered"] = False
    return data


class BuildingListResponse(BaseModel):
    items: list[BuildingResponse]
    total: int


# --- 엔드포인트 ---

@router.get("", response_model=BuildingListResponse)
def list_buildings(
    search: str | None = None,
    sido: str | None = None,
    phase: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """건축물 목록 조회 (검색/필터/페이지네이션)"""
    query = db.query(Building)

    if search:
        query = query.filter(
            Building.mgmt_no.ilike(f"%{search}%")
            | Building.building_name.ilike(f"%{search}%")
        )
    if sido:
        query = query.filter(Building.sido == sido)
    if phase:
        query = query.filter(Building.current_phase == phase)

    total = query.count()
    buildings = query.order_by(Building.mgmt_no).offset((page - 1) * size).limit(size).all()
    items = [_to_response(b) for b in buildings]
    return BuildingListResponse(items=items, total=total)


@router.post("", response_model=BuildingResponse, status_code=201)
def create_building(
    body: BuildingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY, UserRole.SECRETARY)
    ),
):
    """건축물 등록"""
    if db.query(Building).filter(Building.mgmt_no == body.mgmt_no).first():
        raise HTTPException(status_code=409, detail="이미 등록된 관리번호입니다")

    building = Building(**body.model_dump())
    db.add(building)
    db.flush()
    log_action(db, current_user.id, "create", "building", building.id,
               after_data={"mgmt_no": building.mgmt_no})
    db.commit()
    db.refresh(building)
    return building


@router.get("/my-reviews", response_model=BuildingListResponse)
def my_review_buildings(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.REVIEWER, UserRole.SECRETARY, UserRole.CHIEF_SECRETARY)),
):
    """내가 배정된 검토 대상 건축물 목록 (검토위원/간사/총괄간사)"""
    # reviewer_id 또는 assigned_reviewer_name으로 매칭
    reviewer = db.query(Reviewer).filter(Reviewer.user_id == current_user.id).first()

    if reviewer:
        query = db.query(Building).filter(
            (Building.reviewer_id == reviewer.id) | (Building.assigned_reviewer_name == current_user.name)
        )
    else:
        query = db.query(Building).filter(Building.assigned_reviewer_name == current_user.name)
    total = query.count()
    buildings = query.order_by(Building.mgmt_no).offset((page - 1) * size).limit(size).all()
    items = [_to_response(b) for b in buildings]
    return BuildingListResponse(items=items, total=total)


@router.get("/{building_id}", response_model=BuildingResponse)
def get_building(
    building_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """건축물 상세 조회"""
    building = db.query(Building).filter(Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="건축물을 찾을 수 없습니다")
    return building


@router.patch("/{building_id}", response_model=BuildingResponse)
def update_building(
    building_id: int,
    body: BuildingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY, UserRole.SECRETARY)
    ),
):
    """건축물 정보 수정"""
    building = db.query(Building).filter(Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="건축물을 찾을 수 없습니다")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(building, key, value)

    db.commit()
    db.refresh(building)
    return building


@router.delete("/{building_id}", status_code=204)
def delete_building(
    building_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.TEAM_LEADER)),
):
    """건축물 삭제 (팀장만)"""
    building = db.query(Building).filter(Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="건축물을 찾을 수 없습니다")

    db.delete(building)
    db.commit()
