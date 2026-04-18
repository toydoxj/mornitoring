"""건축물(관리대장) 라우터"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

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
    is_special_structure: bool | None = None
    is_high_rise: bool | None = None
    is_multi_use: bool | None = None
    architect_firm: str | None = None
    architect_name: str | None = None
    struct_eng_firm: str | None = None
    struct_eng_name: str | None = None
    drawing_creator_firm: str | None = None
    drawing_creator_name: str | None = None
    drawing_creator_qualification: str | None = None
    seismic_level: str | None = None
    current_phase: str | None = None
    final_result: str | None = None
    reviewer_id: int | None = None
    reviewer_name: str | None = None
    assigned_reviewer_name: str | None = None
    reviewer_registered: bool = False
    # 내 검토대상 테이블용 파생 필드
    full_address: str | None = None
    latest_result: str | None = None
    latest_inappropriate: bool = False

    model_config = {"from_attributes": True}


def _get_registered_names(db: Session) -> set[str]:
    """등록된 사용자 이름 목록 조회"""
    users = db.query(User.name).all()
    return {u[0] for u in users}


def _get_reviewer_for(current_user: User, db: Session) -> Reviewer:
    """REVIEWER 역할 사용자에 대응하는 Reviewer 행 조회. 없으면 403.

    검토위원 권한 필터링은 동명이인 위험을 피하기 위해 `reviewer_id`만 사용한다.
    Reviewer 행이 비어 있으면 데이터 정합성 문제이므로 명시적으로 거부한다.
    """
    reviewer = db.query(Reviewer).filter(Reviewer.user_id == current_user.id).first()
    if reviewer is None:
        raise HTTPException(
            status_code=403,
            detail="검토위원 등록이 되어 있지 않습니다. 관리자에게 문의해주세요",
        )
    return reviewer


def _build_full_address(b: Building) -> str | None:
    """시도 + 시군구 + 법정동 + (본번[-부번]) + 특수지번 을 공백으로 연결"""
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
    data["full_address"] = _build_full_address(building)
    # 최근 제출된 stage 판정/부적정 플래그 (호출부에서 셋업, 기본값 제공)
    data.setdefault("latest_result", None)
    data.setdefault("latest_inappropriate", False)
    return data


class BuildingListResponse(BaseModel):
    items: list[BuildingResponse]
    total: int


# --- 엔드포인트 ---

@router.get("/stats")
def get_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY, UserRole.SECRETARY)
    ),
):
    """대시보드 통계 (관리자 전용 — 전체 건물 통계 노출).

    DB 왕복 수를 줄이기 위해 4개 쿼리로 통합:
      1) 총 건수 + 최종 완료 건수
      2) phase별 건수 GROUP BY
      3) 위원별 집계 (총/단계/완료/면적/고위험)
      4) 위원별 doc_received 상태 중 예비검토서 제출/미제출 (LEFT JOIN + GROUP BY)
    """
    from sqlalchemy import and_, func as sa_func
    from models.inquiry import Inquiry, InquiryStatus
    from models.review_stage import ReviewStage, PhaseType

    # 1) 총 건수 + 최종 완료 건수 (단일 쿼리)
    totals_row = db.query(
        sa_func.count(Building.id).label("total"),
        sa_func.count(Building.id).filter(Building.final_result.isnot(None)).label("completed"),
    ).one()
    total = totals_row.total or 0
    completed = totals_row.completed or 0

    # 1-1) 최종 판정 5분류 — 전체 현황 카드용
    final_rows = (
        db.query(Building.final_result, sa_func.count(Building.id))
        .filter(Building.final_result.isnot(None))
        .group_by(Building.final_result)
        .all()
    )
    final_counts = {
        "pass": 0,
        "pass_supplement": 0,
        "fail": 0,
        "fail_no_response": 0,
        "excluded": 0,
    }
    for key, count in final_rows:
        if key in final_counts:
            final_counts[key] = count

    # 1-2) 문의사항 상태별 건수
    inquiry_rows = (
        db.query(Inquiry.status, sa_func.count(Inquiry.id))
        .group_by(Inquiry.status)
        .all()
    )
    inquiry_counts = {"open": 0, "asking_agency": 0, "completed": 0}
    for status, count in inquiry_rows:
        key = status.value if isinstance(status, InquiryStatus) else str(status)
        if key in inquiry_counts:
            inquiry_counts[key] = count

    # 1-3) 업로드된 검토서 수 (ReviewStage 누적) — 건물 phase 기반이 아니라
    # 제출 기록 자체를 센다. 건물이 보완 단계로 넘어가도 과거 예비 제출이 집계에 남는다.
    uploaded_rows = (
        db.query(ReviewStage.phase, sa_func.count(ReviewStage.id))
        .filter(ReviewStage.report_submitted_at.isnot(None))
        .group_by(ReviewStage.phase)
        .all()
    )
    uploaded_reports_preliminary = 0
    uploaded_reports_supplement = 0
    for phase, count in uploaded_rows:
        key = phase.value if hasattr(phase, "value") else str(phase)
        if key == "preliminary":
            uploaded_reports_preliminary += count
        elif key.startswith("supplement_"):
            uploaded_reports_supplement += count

    # 2) phase 별 건수
    phase_counts_raw = (
        db.query(Building.current_phase, sa_func.count(Building.id))
        .group_by(Building.current_phase)
        .all()
    )
    phase_counts = {phase or "none": count for phase, count in phase_counts_raw}

    # 전체 현황 요약 — 각 카드는 서로 겹치지 않는 단계군
    # (총 등록건 = unassigned + assigned + docs_waiting_review + review_in_progress + completed)
    unassigned = phase_counts.get("none", 0)
    assigned = phase_counts.get("assigned", 0)
    # 도서접수된 상태이지만 검토서 미제출 (예비 + 보완 1~5 received)
    received_phases = {
        "doc_received",
        "supplement_1_received", "supplement_2_received",
        "supplement_3_received", "supplement_4_received",
        "supplement_5_received",
    }
    docs_waiting_review = sum(v for k, v in phase_counts.items() if k in received_phases)
    # 검토서 미접수(= 도서만 접수된 상태) — 전체 현황 카드 예비/보완 구분용
    docs_waiting_preliminary = phase_counts.get("doc_received", 0)
    docs_waiting_supplement = sum(
        phase_counts.get(k, 0)
        for k in (
            "supplement_1_received", "supplement_2_received",
            "supplement_3_received", "supplement_4_received",
            "supplement_5_received",
        )
    )
    # 검토서 제출 완료 (보완 1~5 제출 포함, 예비 제출 포함)
    submission_phases = {
        "preliminary",
        "supplement_1", "supplement_2", "supplement_3",
        "supplement_4", "supplement_5",
    }
    review_in_progress = sum(v for k, v in phase_counts.items() if k in submission_phases)
    # 업로드된 검토서 — 전체 현황 카드 예비/보완 구분용
    review_in_progress_preliminary = phase_counts.get("preliminary", 0)
    review_in_progress_supplement = sum(
        phase_counts.get(k, 0)
        for k in ("supplement_1", "supplement_2", "supplement_3", "supplement_4", "supplement_5")
    )

    # 기존 필드 호환 (이미 사용 중인 명칭 유지)
    doc_received = phase_counts.get("doc_received", 0)
    not_submitted = docs_waiting_review  # 예비+보완 전체 미제출 (기존엔 예비만)
    preliminary = phase_counts.get("preliminary", 0)
    supplement = sum(v for k, v in phase_counts.items() if k.startswith("supplement"))

    # 3) 위원별 기본 집계
    reviewer_stats_raw = (
        db.query(
            Building.assigned_reviewer_name,
            sa_func.count(Building.id).label("total"),
            sa_func.count(Building.id).filter(Building.current_phase == "doc_received").label("doc_received"),
            sa_func.count(Building.id).filter(Building.final_result.isnot(None)).label("completed"),
            sa_func.sum(sa_func.coalesce(Building.gross_area, 0)).label("total_area"),
            sa_func.count(Building.id).filter(Building.gross_area >= 1000).label("area_over_1000"),
            sa_func.count(Building.id).filter(
                (Building.is_special_structure == True) |
                (Building.is_high_rise == True) |
                (Building.is_multi_use == True)
            ).label("high_risk"),
        )
        .filter(Building.assigned_reviewer_name.isnot(None))
        .group_by(Building.assigned_reviewer_name)
        .order_by(Building.assigned_reviewer_name)
        .all()
    )

    # 4) 위원별 doc_received 상태 건물 중 예비검토서 제출/미제출 수 (LEFT JOIN 1회)
    # - building당 (phase=PRELIMINARY, submitted_at NOT NULL) review_stage 최대 1건이라는 도메인
    #   전제 하에 COUNT(ReviewStage.id)로 제출 건수를 집계한다. 가정이 깨지면 DISTINCT 필요.
    received_stats_raw = (
        db.query(
            Building.assigned_reviewer_name,
            sa_func.count(Building.id).label("received"),
            sa_func.count(ReviewStage.id).label("received_submitted"),
        )
        .outerjoin(
            ReviewStage,
            and_(
                ReviewStage.building_id == Building.id,
                ReviewStage.phase == PhaseType.PRELIMINARY,
                ReviewStage.report_submitted_at.isnot(None),
            ),
        )
        .filter(
            Building.current_phase == "doc_received",
            Building.assigned_reviewer_name.isnot(None),
        )
        .group_by(Building.assigned_reviewer_name)
        .all()
    )
    received_by_reviewer: dict[str, tuple[int, int]] = {
        name: (received or 0, received_submitted or 0)
        for name, received, received_submitted in received_stats_raw
    }

    reviewer_stats = []
    for name, total_count, doc_count, comp_count, total_area, area_over_1000, high_risk in reviewer_stats_raw:
        received_total, submitted_count = received_by_reviewer.get(name, (0, 0))
        not_submitted_count = received_total - submitted_count

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
        # 전체 흐름 요약 (서로 겹치지 않고 합산하면 total)
        "unassigned": unassigned,
        "assigned": assigned,
        "docs_waiting_review": docs_waiting_review,
        "docs_waiting_review_preliminary": docs_waiting_preliminary,
        "docs_waiting_review_supplement": docs_waiting_supplement,
        "review_in_progress": review_in_progress,
        "review_in_progress_preliminary": review_in_progress_preliminary,
        "review_in_progress_supplement": review_in_progress_supplement,
        # 업로드된 검토서 누적 수 (대시보드 "업로드된 검토서" 카드용)
        "uploaded_reports_preliminary": uploaded_reports_preliminary,
        "uploaded_reports_supplement": uploaded_reports_supplement,
        "completed": completed,
        # 최종 판정 5분류 (적합/보완적합/부적합/부적합(미회신)/대상제외)
        "final_counts": final_counts,
        # 문의사항 상태별 건수 (전체)
        "inquiry_counts": inquiry_counts,
        # 기존 호환 필드 (프론트 기존 코드 참조)
        "doc_received": doc_received,
        "not_submitted": not_submitted,
        "preliminary": preliminary,
        "supplement": supplement,
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
    """건축물 목록 조회 (검색/필터/정렬/페이지네이션).

    검토위원(REVIEWER)은 본인이 배정된 건물만 조회 가능. `?reviewer=` 파라미터는
    REVIEWER가 보내도 무시되어 다른 위원 데이터에 접근할 수 없다.
    """
    query = db.query(Building)

    # REVIEWER는 본인 담당 건물만 강제 필터 (reviewer_id 매칭만 사용 — 동명이인 위험 회피)
    is_reviewer = current_user.role == UserRole.REVIEWER
    if is_reviewer:
        reviewer_record = _get_reviewer_for(current_user, db)
        query = query.filter(Building.reviewer_id == reviewer_record.id)

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
    # reviewer 필터는 관리자(REVIEWER 외)만 적용
    if reviewer and not is_reviewer:
        query = query.filter(Building.assigned_reviewer_name == reviewer)

    total = query.count()

    # 정렬
    sort_col = getattr(Building, sort_by, None) if sort_by else Building.mgmt_no
    if sort_col is None:
        sort_col = Building.mgmt_no
    if sort_order == "desc":
        sort_col = sort_col.desc()

    # N+1 제거: building.reviewer.user를 한 번에 eager load
    buildings = (
        query.options(selectinload(Building.reviewer).selectinload(Reviewer.user))
        .order_by(sort_col)
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    registered_names = _get_registered_names(db)
    items = [_to_response(b, registered_names) for b in buildings]
    return BuildingListResponse(items=items, total=total)


@router.get("/reviewer-names")
def get_reviewer_names(
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY, UserRole.SECRETARY)
    ),
):
    """배정된 검토위원 이름 목록 (관리자 전용 — 위원 enumeration 차단)"""
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


@router.get("/reviewer-schedule")
def reviewer_schedule(
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY, UserRole.SECRETARY)
    ),
):
    """검토위원별 일정관리 요약 — 대시보드 "검토위원별 일정관리" 테이블 데이터.

    활성 REVIEWER 사용자 전체를 행으로 노출하고, 각각에 대해
    `review_stages.report_submitted_at IS NULL AND report_due_date IS NOT NULL` 인 건을
    오늘 기준 D-3/D-2/D-1/D-day/초과 카운트로 집계한다. D+4 이상 예정이거나 일정이 없는
    건은 in_progress 에만 합산된다. 미제출이 없는 검토위원도 모든 카운트 0으로 표시.
    """
    from datetime import date
    from models.review_stage import ReviewStage
    from models.reviewer import Reviewer

    today = date.today()

    # 1) 활성 REVIEWER 전체를 0 초기화로 준비
    reviewer_users = (
        db.query(User)
        .filter(
            User.is_active.is_(True),
            User.role == UserRole.REVIEWER,
        )
        .order_by(User.name)
        .all()
    )
    by_user: dict[int, dict] = {
        u.id: {
            "reviewer_user_id": u.id,
            "reviewer_name": u.name,
            "kakao_matched": bool(u.kakao_uuid),
            "in_progress": 0,
            "d_minus_3": 0,
            "d_minus_2": 0,
            "d_minus_1": 0,
            "d_day": 0,
            "overdue": 0,
        }
        for u in reviewer_users
    }

    # 2) 미제출 stage 를 집계해 위 buckets 에 반영
    rows = (
        db.query(ReviewStage, Building, User)
        .join(Building, ReviewStage.building_id == Building.id)
        .join(Reviewer, Building.reviewer_id == Reviewer.id)
        .join(User, Reviewer.user_id == User.id)
        .filter(
            ReviewStage.report_submitted_at.is_(None),
            ReviewStage.report_due_date.isnot(None),
            User.is_active.is_(True),
        )
        .all()
    )
    for stage, _building, user in rows:
        # 간사/총괄간사가 Reviewer 행을 가진 경우에도 요약을 놓치지 않도록 setdefault
        info = by_user.setdefault(user.id, {
            "reviewer_user_id": user.id,
            "reviewer_name": user.name,
            "kakao_matched": bool(user.kakao_uuid),
            "in_progress": 0,
            "d_minus_3": 0,
            "d_minus_2": 0,
            "d_minus_1": 0,
            "d_day": 0,
            "overdue": 0,
        })
        info["in_progress"] += 1
        delta = (stage.report_due_date - today).days
        if delta == 3:
            info["d_minus_3"] += 1
        elif delta == 2:
            info["d_minus_2"] += 1
        elif delta == 1:
            info["d_minus_1"] += 1
        elif delta == 0:
            info["d_day"] += 1
        elif delta < 0:
            info["overdue"] += 1
        # delta > 3 은 in_progress 만 증가, 별도 열 없음

    return sorted(
        by_user.values(),
        key=lambda x: (
            -x["overdue"],
            -x["d_day"],
            -x["d_minus_1"],
            -x["d_minus_2"],
            -x["d_minus_3"],
            -x["in_progress"],
            x["reviewer_name"],
        ),
    )


@router.get("/my-stats")
def my_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(
            UserRole.REVIEWER, UserRole.SECRETARY, UserRole.CHIEF_SECRETARY, UserRole.TEAM_LEADER
        )
    ),
):
    """개인 대시보드 통계 (본인 담당 건물 기준).

    담당 매칭은 `reviewer_id`만 사용한다. 이름 기반 OR 매칭은 동명이인
    위험 + 권한 체크 일관성을 위해 제거됨. 관리자(SECRETARY/CHIEF/TEAM_LEADER)도
    Reviewer 행이 없으면 빈 결과를 반환한다(본인 담당이 없으면 자연스러운 결과).
    """
    from datetime import date as _date
    from models.review_stage import ReviewStage

    reviewer = db.query(Reviewer).filter(Reviewer.user_id == current_user.id).first()
    if reviewer is None:
        buildings: list[Building] = []
    else:
        buildings = (
            db.query(Building).filter(Building.reviewer_id == reviewer.id).all()
        )

    total = len(buildings)
    total_area = float(sum((float(b.gross_area) if b.gross_area else 0.0) for b in buildings))
    area_over_1000 = sum(1 for b in buildings if (b.gross_area or 0) >= 1000)
    high_risk = sum(
        1 for b in buildings
        if b.is_special_structure or b.is_high_rise or b.is_multi_use
    )

    # '_received' 상태 (도서 접수 후 검토서 미제출)
    RECEIVED_PHASES = {
        "doc_received",
        "supplement_1_received",
        "supplement_2_received",
        "supplement_3_received",
        "supplement_4_received",
        "supplement_5_received",
    }
    received_buildings = [b for b in buildings if b.current_phase in RECEIVED_PHASES]
    need_review = len(received_buildings)

    # 검토서 제출 건수 — 본인 담당 건물들에서 report_submitted_at 있는 stage 수 (예비/보완 분리)
    building_ids = [b.id for b in buildings]
    submitted_preliminary = 0
    submitted_supplement = 0
    if building_ids:
        submitted_preliminary = (
            db.query(ReviewStage)
            .filter(
                ReviewStage.building_id.in_(building_ids),
                ReviewStage.report_submitted_at.isnot(None),
                ReviewStage.phase == "preliminary",
            )
            .count()
        )
        submitted_supplement = (
            db.query(ReviewStage)
            .filter(
                ReviewStage.building_id.in_(building_ids),
                ReviewStage.report_submitted_at.isnot(None),
                ReviewStage.phase.in_([
                    "supplement_1", "supplement_2", "supplement_3",
                    "supplement_4", "supplement_5",
                ]),
            )
            .count()
        )
    submitted = submitted_preliminary + submitted_supplement

    # 접수 후 경과일수 버킷 — 현재 '_received' 단계의 doc_received_at 기준
    RECEIVED_TO_SUBMIT_PHASE = {
        "doc_received": "preliminary",
        "supplement_1_received": "supplement_1",
        "supplement_2_received": "supplement_2",
        "supplement_3_received": "supplement_3",
        "supplement_4_received": "supplement_4",
        "supplement_5_received": "supplement_5",
    }
    elapsed_buckets = {
        "1일": 0, "2일": 0, "3일": 0, "4일": 0, "5일": 0,
        "6일": 0, "7일": 0, "1주": 0, "2주이상": 0,
    }
    today = _date.today()
    if received_buildings:
        pairs = [(b.id, RECEIVED_TO_SUBMIT_PHASE[b.current_phase]) for b in received_buildings]
        stage_map: dict[tuple[int, str], ReviewStage] = {}
        stages = (
            db.query(ReviewStage)
            .filter(ReviewStage.building_id.in_([p[0] for p in pairs]))
            .all()
        )
        for s in stages:
            stage_map[(s.building_id, s.phase.value)] = s
        for bid, phase in pairs:
            s = stage_map.get((bid, phase))
            if not s or not s.doc_received_at:
                continue
            days = (today - s.doc_received_at).days
            if days < 1:
                elapsed_buckets["1일"] += 1  # 당일 접수는 1일로 합산
            elif 1 <= days <= 7:
                elapsed_buckets[f"{days}일"] += 1
            elif 8 <= days <= 13:
                elapsed_buckets["1주"] += 1
            else:  # 14+
                elapsed_buckets["2주이상"] += 1

    # 최종 완료 건수 (5분류) — 본인 담당 기준
    # final_result 값은 향후 '최종 판정용 별도 엑셀 업로드'에서 기입됨
    final_counts = {
        "pass": 0,               # 적합
        "pass_supplement": 0,    # 보완적합
        "fail": 0,               # 부적합
        "fail_no_response": 0,   # 부적합(미회신)
        "excluded": 0,           # 대상제외
    }
    for b in buildings:
        if b.final_result and b.final_result in final_counts:
            final_counts[b.final_result] += 1

    return {
        "total": total,
        "total_area": total_area,
        "area_over_1000": area_over_1000,
        "high_risk": high_risk,
        "need_review": need_review,
        "submitted": submitted,
        "submitted_preliminary": submitted_preliminary,
        "submitted_supplement": submitted_supplement,
        "elapsed_buckets": elapsed_buckets,
        "final_counts": final_counts,
    }


@router.get("/my-reviews", response_model=BuildingListResponse)
def my_review_buildings(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.REVIEWER, UserRole.SECRETARY, UserRole.CHIEF_SECRETARY)),
):
    """내가 배정된 검토 대상 건축물 목록 (검토위원/간사/총괄간사).

    담당 매칭은 `reviewer_id`만 사용한다. 이름 기반 매칭은 동명이인 위험으로 제거.
    Reviewer 행이 없는 사용자는 빈 결과.
    """
    from models.review_stage import ReviewStage

    reviewer = db.query(Reviewer).filter(Reviewer.user_id == current_user.id).first()
    if reviewer is None:
        return BuildingListResponse(items=[], total=0)

    query = db.query(Building).filter(Building.reviewer_id == reviewer.id)
    total = query.count()
    # N+1 제거: building.reviewer.user를 한 번에 eager load
    buildings = (
        query.options(selectinload(Building.reviewer).selectinload(Reviewer.user))
        .order_by(Building.mgmt_no)
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    registered_names = _get_registered_names(db)

    # 각 건물별 최근 제출 stage (phase_order 최대, 제출일 존재) 조회
    building_ids = [b.id for b in buildings]
    latest_by_building: dict[int, ReviewStage] = {}
    if building_ids:
        stages = (
            db.query(ReviewStage)
            .filter(
                ReviewStage.building_id.in_(building_ids),
                ReviewStage.report_submitted_at.isnot(None),
            )
            .order_by(ReviewStage.building_id, ReviewStage.phase_order.desc())
            .all()
        )
        for s in stages:
            if s.building_id not in latest_by_building:
                latest_by_building[s.building_id] = s

    items = []
    for b in buildings:
        data = _to_response(b, registered_names)
        latest = latest_by_building.get(b.id)
        if latest:
            data["latest_result"] = latest.result.value if latest.result else None
            data["latest_inappropriate"] = bool(latest.inappropriate_review_needed)
        items.append(data)
    return BuildingListResponse(items=items, total=total)


@router.get("/{building_id}", response_model=BuildingResponse)
def get_building(
    building_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """건축물 상세 조회.

    REVIEWER는 본인 담당이 아닌 건물에 대해 존재 여부도 노출하지 않도록 404 반환.
    """
    building = db.query(Building).filter(Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="건축물을 찾을 수 없습니다")

    if current_user.role == UserRole.REVIEWER:
        reviewer_record = _get_reviewer_for(current_user, db)
        if building.reviewer_id != reviewer_record.id:
            # 존재 자체를 노출하지 않기 위해 403이 아닌 404
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
