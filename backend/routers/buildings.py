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

# 등록된 사용자 이름 캐시 (요청마다 갱신)
_registered_names_cache: set[str] | None = None

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


def _get_registered_names(db: Session) -> set[str]:
    """등록된 사용자 이름 목록 조회"""
    users = db.query(User.name).all()
    return {u[0] for u in users}


def _to_response(building: Building, registered_names: set[str]) -> dict:
    """Building 모델을 응답 dict로 변환 (검토위원 이름 + 등록 여부 포함)"""
    data = {c.name: getattr(building, c.name) for c in Building.__table__.columns}
    data["reviewer_name"] = None
    data["reviewer_registered"] = False
    if building.reviewer and building.reviewer.user:
        data["reviewer_name"] = building.reviewer.user.name
        data["reviewer_registered"] = True
    elif building.assigned_reviewer_name:
        data["reviewer_name"] = building.assigned_reviewer_name
        data["reviewer_registered"] = building.assigned_reviewer_name in registered_names
    return data


class BuildingListResponse(BaseModel):
    items: list[BuildingResponse]
    total: int


# --- 엔드포인트 ---

@router.get("/stats")
def get_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """대시보드 통계"""
    from models.review_stage import ReviewStage, PhaseType

    total = db.query(Building).count()

    # 예비도서 접수(배포) 건수
    doc_received = db.query(Building).filter(Building.current_phase == "doc_received").count()

    # 예비검토 중 (검토서 미접수) — doc_received인데 review_stage에 report_submitted_at이 없는 건
    doc_received_ids = db.query(Building.id).filter(Building.current_phase == "doc_received").subquery()
    submitted_ids = (
        db.query(ReviewStage.building_id)
        .filter(
            ReviewStage.phase == PhaseType.PRELIMINARY,
            ReviewStage.report_submitted_at.isnot(None),
        )
        .subquery()
    )
    not_submitted = (
        db.query(Building)
        .filter(Building.id.in_(doc_received_ids))
        .filter(~Building.id.in_(submitted_ids))
        .count()
    )

    # 단계별 건수
    from sqlalchemy import func as sa_func2
    phase_counts_raw = (
        db.query(Building.current_phase, sa_func2.count(Building.id))
        .group_by(Building.current_phase)
        .all()
    )
    phase_counts = {phase or "none": count for phase, count in phase_counts_raw}

    # 예비검토서 제출
    preliminary = phase_counts.get("preliminary", 0)

    # 보완 진행
    supplement = sum(v for k, v in phase_counts.items() if k.startswith("supplement"))

    # 최종 완료
    completed = db.query(Building).filter(Building.final_result.isnot(None)).count()

    # 위원별 현황
    from sqlalchemy import func as sa_func
    reviewer_stats_raw = (
        db.query(
            Building.assigned_reviewer_name,
            sa_func.count(Building.id).label("total"),
            sa_func.count(Building.id).filter(Building.current_phase == "doc_received").label("doc_received"),
            sa_func.count(Building.id).filter(Building.final_result.isnot(None)).label("completed"),
            sa_func.sum(sa_func.coalesce(Building.gross_area, 0)).label("total_area"),
            sa_func.count(Building.id).filter(Building.gross_area >= 1000).label("area_over_1000"),
            sa_func.count(Building.id).filter(Building.high_risk_type.isnot(None)).label("high_risk"),
        )
        .filter(Building.assigned_reviewer_name.isnot(None))
        .group_by(Building.assigned_reviewer_name)
        .order_by(Building.assigned_reviewer_name)
        .all()
    )

    # 위원별 검토서 제출 건수 조회
    submitted_by_reviewer = {}
    submitted_rows = (
        db.query(ReviewStage.building_id)
        .filter(
            ReviewStage.phase == PhaseType.PRELIMINARY,
            ReviewStage.report_submitted_at.isnot(None),
        )
        .all()
    )
    submitted_building_ids = {r[0] for r in submitted_rows}

    reviewer_stats = []
    for name, total_count, doc_count, comp_count, total_area, area_over_1000, high_risk in reviewer_stats_raw:
        # 해당 위원의 building id 조회
        reviewer_building_ids = [
            b.id for b in db.query(Building.id)
            .filter(Building.assigned_reviewer_name == name, Building.current_phase == "doc_received")
            .all()
        ]
        submitted_count = len([bid for bid in reviewer_building_ids if bid in submitted_building_ids])
        not_submitted_count = len(reviewer_building_ids) - submitted_count

        reviewer_stats.append({
            "name": name,
            "total": total_count,
            "total_area": float(total_area or 0),
            "area_over_1000": area_over_1000 or 0,
            "high_risk": high_risk or 0,
            "doc_received": doc_count,
            "submitted": submitted_count,
            "not_submitted": not_submitted_count,
            "completed": comp_count,
        })

    return {
        "total": total,
        "doc_received": doc_received,
        "not_submitted": not_submitted,
        "preliminary": preliminary,
        "supplement": supplement,
        "completed": completed,
        "phase_counts": phase_counts,
        "reviewer_stats": reviewer_stats,
    }


@router.get("", response_model=BuildingListResponse)
def list_buildings(
    search: str | None = None,
    sido: str | None = None,
    phase: str | None = None,
    reviewer: str | None = None,
    sort_by: str | None = None,
    sort_order: str = "asc",
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """건축물 목록 조회 (검색/필터/정렬/페이지네이션)"""
    query = db.query(Building)

    if search:
        query = query.filter(
            Building.mgmt_no.ilike(f"%{search}%")
            | Building.building_name.ilike(f"%{search}%")
        )
    if sido:
        query = query.filter(Building.sido == sido)
    if phase:
        if phase == "none":
            query = query.filter(Building.current_phase.is_(None))
        else:
            query = query.filter(Building.current_phase == phase)
    if reviewer:
        query = query.filter(Building.assigned_reviewer_name == reviewer)

    total = query.count()

    # 정렬
    sort_col = getattr(Building, sort_by, None) if sort_by else Building.mgmt_no
    if sort_col is None:
        sort_col = Building.mgmt_no
    if sort_order == "desc":
        sort_col = sort_col.desc()

    buildings = query.order_by(sort_col).offset((page - 1) * size).limit(size).all()
    registered_names = _get_registered_names(db)
    items = [_to_response(b, registered_names) for b in buildings]
    return BuildingListResponse(items=items, total=total)


@router.get("/reviewer-names")
def get_reviewer_names(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """배정된 검토위원 이름 목록 (필터용)"""
    names = (
        db.query(Building.assigned_reviewer_name)
        .filter(Building.assigned_reviewer_name.isnot(None))
        .distinct()
        .order_by(Building.assigned_reviewer_name)
        .all()
    )
    return [n[0] for n in names]


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
    registered_names = _get_registered_names(db)
    items = [_to_response(b, registered_names) for b in buildings]
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
