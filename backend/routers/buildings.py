"""건축물(관리대장) 라우터"""

from datetime import date
from time import monotonic

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased, load_only, selectinload

from config import settings
from database import get_db
from models.building import Building
from models.reviewer import Reviewer
from models.user import User, UserRole
from routers.auth import get_current_user, require_roles
from services.audit import log_action
from services.business_date import business_today
from services.related_tech import related_tech_coop_filter, related_tech_target_filter
from services.scope import (
    building_visibility_filter,
    is_building_visible_to,
    visible_building_ids_subquery,
    visible_reviewer_user_ids,
)

router = APIRouter()

_STATS_CACHE: dict[tuple[str, str], tuple[float, dict[str, object]]] = {}


RECEIVED_TO_SUBMIT_PHASE = {
    "doc_received": "preliminary",
    "supplement_1_received": "supplement_1",
    "supplement_2_received": "supplement_2",
    "supplement_3_received": "supplement_3",
    "supplement_4_received": "supplement_4",
    "supplement_5_received": "supplement_5",
}
RECEIVED_PHASES = set(RECEIVED_TO_SUBMIT_PHASE)


def _stage_phase_value(stage) -> str:
    return stage.phase.value if hasattr(stage.phase, "value") else str(stage.phase)


def _is_current_pending_stage(building: Building, stage) -> bool:
    """건물의 현재 접수 단계와 짝이 맞는 미제출 검토서 stage인지 확인."""
    expected_phase = RECEIVED_TO_SUBMIT_PHASE.get(building.current_phase or "")
    return expected_phase is not None and _stage_phase_value(stage) == expected_phase


def _my_assignment_filter(db: Session, current_user: User):
    """내 검토대상용 담당 필터.

    검토위원은 동명이인 위험 때문에 reviewer_id만 사용한다. 총괄간사는
    실무상 직접 검토를 맡을 수 있으므로 이름 배정 건도 함께 포함한다.
    """
    reviewer = db.query(Reviewer).filter(Reviewer.user_id == current_user.id).first()
    if current_user.role == UserRole.REVIEWER:
        if reviewer is None:
            return Building.id.is_(None)
        return Building.reviewer_id == reviewer.id

    filters = []
    if reviewer is not None:
        filters.append(Building.reviewer_id == reviewer.id)
    if current_user.role == UserRole.CHIEF_SECRETARY:
        filters.append(Building.assigned_reviewer_name == current_user.name)
    if not filters:
        return Building.id.is_(None)
    if len(filters) == 1:
        return filters[0]
    return or_(*filters)


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
    is_quasi_multi_use: bool | None = None
    remarks: str | None = None
    architect_firm: str | None = None
    architect_name: str | None = None
    struct_eng_firm: str | None = None
    struct_eng_name: str | None = None
    high_risk_type: str | None = None


class BuildingUpdate(BaseModel):
    """건축물 일반 정보 수정.

    `current_phase` 는 의도적으로 포함하지 않는다. phase 전환은 도메인 정책상
    8개 매트릭스 외에 발생해선 안 되며, 별도 엔드포인트
    `POST /buildings/{id}/phase` 로 분리되어 있다.

    extra='forbid' 로 알 수 없는 필드(특히 `current_phase`)가 들어오면
    422 로 명시적으로 거부 — 클라이언트 버그를 조용히 무시하지 않기 위함.
    """
    model_config = {"extra": "forbid"}

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
    final_result: str | None = None
    remarks: str | None = None


class ReviewerDetailResponse(BaseModel):
    name: str
    group_no: int | None = None
    email: str | None = None
    phone: str | None = None


class ReviewerOptionResponse(BaseModel):
    reviewer_id: int
    user_id: int
    name: str
    group_no: int | None = None
    email: str | None = None
    phone: str | None = None


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
    is_quasi_multi_use: bool | None = None
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
    reviewer_detail: ReviewerDetailResponse | None = None
    # 내 검토대상 테이블용 파생 필드
    full_address: str | None = None
    latest_result: str | None = None
    latest_inappropriate: bool = False
    # 접수 상태(_received)일 때 미제출 stage의 검토서 요청 예정일
    report_due_date: str | None = None

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


def _build_reviewer_detail(building: Building) -> dict[str, str | int | None] | None:
    if not building.reviewer or not building.reviewer.user:
        return None
    user = building.reviewer.user
    return {
        "name": user.name,
        "group_no": building.reviewer.group_no,
        "email": user.email,
        "phone": user.phone,
    }


def _to_my_review_response(
    building: Building,
    *,
    reviewer_name: str,
    latest_stage: "ReviewStage | None",
    pending_stage: "ReviewStage | None",
) -> dict:
    """내 검토 대상 목록에 필요한 필드만 응답 dict로 변환."""
    return {
        "id": building.id,
        "mgmt_no": building.mgmt_no,
        "building_name": building.building_name,
        "sido": building.sido,
        "sigungu": building.sigungu,
        "beopjeongdong": building.beopjeongdong,
        "main_lot_no": building.main_lot_no,
        "sub_lot_no": building.sub_lot_no,
        "special_lot_no": building.special_lot_no,
        "gross_area": building.gross_area,
        "floors_above": building.floors_above,
        "floors_below": building.floors_below,
        "high_risk_type": building.high_risk_type,
        "is_special_structure": building.is_special_structure,
        "is_high_rise": building.is_high_rise,
        "is_multi_use": building.is_multi_use,
        "is_quasi_multi_use": building.is_quasi_multi_use,
        "current_phase": building.current_phase,
        "final_result": building.final_result,
        "reviewer_id": building.reviewer_id,
        "reviewer_name": reviewer_name,
        "assigned_reviewer_name": building.assigned_reviewer_name,
        "reviewer_registered": True,
        "full_address": _build_full_address(building),
        "latest_result": (
            latest_stage.result.value if latest_stage and latest_stage.result else None
        ),
        "latest_inappropriate": (
            bool(latest_stage.inappropriate_review_needed) if latest_stage else False
        ),
        "report_due_date": (
            pending_stage.report_due_date.isoformat()
            if (
                building.current_phase
                and building.current_phase.endswith("_received")
                and pending_stage
                and pending_stage.report_due_date
            )
            else None
        ),
    }


def _to_response(building: Building, registered_names: set[str]) -> dict:
    """Building 모델을 응답 dict로 변환 (검토위원 이름 + 등록 여부 포함)"""
    data = {c.name: getattr(building, c.name) for c in Building.__table__.columns}
    data["reviewer_name"] = None
    data["reviewer_registered"] = False
    data["reviewer_detail"] = None
    if building.reviewer and building.reviewer.user:
        data["reviewer_name"] = building.reviewer.user.name
        data["reviewer_registered"] = True
        data["reviewer_detail"] = _build_reviewer_detail(building)
    elif building.assigned_reviewer_name:
        data["reviewer_name"] = building.assigned_reviewer_name
        data["reviewer_registered"] = building.assigned_reviewer_name in registered_names
    data["full_address"] = _build_full_address(building)
    # 최근 제출된 stage 판정/부적정 플래그 (호출부에서 셋업, 기본값 제공)
    data.setdefault("latest_result", None)
    data.setdefault("latest_inappropriate", False)
    data.setdefault("report_due_date", None)
    return data


def _validate_assignable_reviewer(
    reviewer_id: int,
    current_user: User,
    db: Session,
) -> Reviewer:
    reviewer = (
        db.query(Reviewer)
        .join(User, Reviewer.user_id == User.id)
        .filter(
            Reviewer.id == reviewer_id,
            User.role == UserRole.REVIEWER,
            User.is_active.is_(True),
        )
        .first()
    )
    if reviewer is None:
        raise HTTPException(status_code=404, detail="등록된 검토자를 찾을 수 없습니다")

    user_visibility = visible_reviewer_user_ids(current_user)
    if (
        user_visibility is not None
        and not db.query(User.id)
        .filter(User.id == reviewer.user_id, user_visibility)
        .first()
    ):
        raise HTTPException(status_code=403, detail="선택할 수 없는 검토자입니다")
    return reviewer


SEVERITY_LABELS = ("L0", "L1", "L2", "L3", "L4")
REPORT_MAX_LABELS = ("pass", *SEVERITY_LABELS)
REGION_TOTAL_LABEL = "전체"
UNKNOWN_REGION_LABEL = "지역 미상"
REGION_ORDER = (
    "경기도",
    "경상북도",
    "경상남도",
    "충청남도",
    "충청북도",
    "전북특별자치도",
    "전라남도",
    "강원특별자치도",
    "제주특별자치도",
    "인천광역시",
    "서울특별시",
    "울산광역시",
    "부산광역시",
    "대구광역시",
    "대전광역시",
    "광주광역시",
    "세종특별자치시",
)
REGION_SORT_ORDER = {region: index for index, region in enumerate(REGION_ORDER)}
REGION_ALIASES = {
    "전라북도": "전북특별자치도",
    "강원도": "강원특별자치도",
    "제주도": "제주특별자치도",
}
AREA_STAT_KEYS = (
    "area_0_300",
    "area_300_600",
    "area_600_1000",
    "area_1000_5000",
    "area_5000_over",
)
FLOOR_STAT_KEYS = (
    "floors_under_6",
    "floors_6_under_16",
    "floors_16_over",
)
RISK_STAT_KEYS = (
    "total",
    "special",
    "multi_use",
    "high_rise",
    "quasi_multi_use",
    "related_tech_coop_target",
    "related_tech_coop",
    "related_tech_coop_missing",
)
DRAWING_CREATOR_STAT_KEYS = (
    "drawing_creator_architect",
    "drawing_creator_structural_engineer",
    "drawing_creator_unknown",
)


def _empty_severity_counts() -> dict[str, int]:
    return {label: 0 for label in SEVERITY_LABELS}


def _empty_report_max_counts() -> dict[str, int]:
    return {label: 0 for label in REPORT_MAX_LABELS}


def _region_label(sido: str | None) -> str:
    if not sido or not sido.strip():
        return UNKNOWN_REGION_LABEL
    region = sido.strip()
    return REGION_ALIASES.get(region, region)


def _merge_regional_rows(raw_rows, count_keys: tuple[str, ...]) -> list[dict[str, int | str]]:
    by_region: dict[str, dict[str, int | str]] = {}
    for row in raw_rows:
        region = _region_label(row.sido)
        item = by_region.setdefault(
            region,
            {"region": region, **{key: 0 for key in count_keys}},
        )
        for key in count_keys:
            item[key] = int(item.get(key, 0)) + int(getattr(row, key) or 0)

    total_row: dict[str, int | str] = {
        "region": REGION_TOTAL_LABEL,
        **{key: 0 for key in count_keys},
    }
    for item in by_region.values():
        for key in count_keys:
            total_row[key] = int(total_row.get(key, 0)) + int(item.get(key, 0))

    region_rows = sorted(
        by_region.values(),
        key=lambda item: (
            REGION_SORT_ORDER.get(str(item["region"]), len(REGION_ORDER)),
            item["region"] == UNKNOWN_REGION_LABEL,
            str(item["region"]),
        ),
    )
    return [total_row, *region_rows]


def _stats_cache_key(current_user: User, scope: str | None = None) -> tuple[str, str]:
    # scope=all 은 조 구분 없는 전체 집계이므로 팀장/총괄과 동일한 캐시를 쓴다.
    if scope == "all":
        return ("all", "all")
    if current_user.role == UserRole.SECRETARY:
        group_key = str(current_user.group_no) if current_user.group_no is not None else "all"
        return (current_user.role.value, group_key)
    return ("all", "all")


def _stats_cache_get(db: Session, key: tuple[str, str]) -> dict[str, object] | None:
    ttl = settings.stats_cache_ttl_seconds
    # 테스트 SQLite에서는 데이터 변경 직후 검증이 많으므로 캐시를 끈다.
    if ttl <= 0 or db.get_bind().dialect.name == "sqlite":
        return None
    cached = _STATS_CACHE.get(key)
    if cached is None:
        return None
    cached_at, payload = cached
    if monotonic() - cached_at >= ttl:
        _STATS_CACHE.pop(key, None)
        return None
    return payload


def _stats_cache_set(db: Session, key: tuple[str, str], payload: dict[str, object]) -> None:
    ttl = settings.stats_cache_ttl_seconds
    if ttl <= 0 or db.get_bind().dialect.name == "sqlite":
        return
    _STATS_CACHE[key] = (monotonic(), payload)


def clear_stats_cache() -> None:
    _STATS_CACHE.clear()


def _release_read_connection(db: Session) -> None:
    """읽기 전용 후처리 동안 DB 커넥션을 오래 점유하지 않도록 반환한다."""
    db.rollback()


class BuildingListResponse(BaseModel):
    items: list[BuildingResponse]
    total: int


class GroupReviewerSummary(BaseModel):
    """건물이 속한 조의 검토위원 명단 항목."""

    reviewer_id: int
    user_id: int
    name: str
    specialty: str | None = None
    phone: str | None = None
    is_assigned: bool = False       # 이 건물의 담당 위원인지
    assigned_count: int = 0         # 해당 위원이 담당 중인 건물 수


class BuildingStageSummary(BaseModel):
    """요약 팝업용 검토 단계 정보."""

    id: int
    phase: str
    phase_order: int
    doc_received_at: date | None = None
    doc_distributed_at: date | None = None
    report_submitted_at: date | None = None
    reviewer_name: str | None = None
    result: str | None = None
    severity_l0_count: int = 0
    severity_l1_count: int = 0
    severity_l2_count: int = 0
    severity_l3_count: int = 0
    severity_l4_count: int = 0
    inappropriate_review_needed: bool = False
    inappropriate_decision: str | None = None


class BuildingSummaryResponse(BaseModel):
    building: BuildingResponse
    group_no: int | None = None
    reviewer_name: str | None = None
    group_reviewers: list[GroupReviewerSummary] = []
    stages: list[BuildingStageSummary] = []


# --- 엔드포인트 ---

@router.get("/stats")
def get_stats(
    scope: str | None = Query(
        None,
        description="all이면 조 구분 없이 전체 집계 (통계자료 화면 전용)",
    ),
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
    """대시보드 통계 (관리자 전용 — 전체 건물 통계 노출).

    DB 왕복 수를 줄이기 위해 4개 쿼리로 통합:
      1) 총 건수 + 최종 완료 건수
      2) phase별 건수 GROUP BY
      3) 위원별 집계 (총/단계/완료/면적/고위험)
      4) 위원별 doc_received 상태 중 예비검토서 제출/미제출 (LEFT JOIN + GROUP BY)

    scope='all' 은 통계자료 화면 전용으로, 간사도 조 구분 없이 전체를 집계한다.
    대시보드는 scope 를 넘기지 않으므로 기존대로 조별 집계를 유지한다.
    """
    if scope not in (None, "", "all"):
        raise HTTPException(status_code=400, detail="허용되지 않는 집계 범위입니다")
    from sqlalchemy import and_, case, func as sa_func, or_
    from engines.opinion_quality_analyzer import match_opinion_quality
    from engines.review_keyword_analyzer import match_keywords
    from models.inquiry import Inquiry, InquiryStatus
    from models.review_opinion_detail import ReviewOpinionDetail
    from models.review_severity_summary import ReviewSeveritySummary
    from models.review_stage import ReviewStage, PhaseType, ResultType

    cache_key = _stats_cache_key(current_user, scope)
    cached_stats = _stats_cache_get(db, cache_key)
    if cached_stats is not None:
        _release_read_connection(db)
        return cached_stats

    # 가시성 필터: 간사가 자기 조 데이터만 보도록.
    # visibility=None 이면 무필터(팀장/총괄/조 미배정 간사/scope=all).
    unrestricted = scope == "all"
    visibility = None if unrestricted else building_visibility_filter(current_user)
    visible_ids_select = None if unrestricted else visible_building_ids_subquery(current_user)

    def _scoped(q):
        return q.filter(visibility) if visibility is not None else q

    def _scoped_by_building_id(q, building_id_col):
        if visible_ids_select is None:
            return q
        return q.filter(building_id_col.in_(visible_ids_select))

    # 1) 총 건수 + 최종 완료 건수 (단일 쿼리)
    totals_row = _scoped(db.query(
        sa_func.count(Building.id).label("total"),
        sa_func.count(Building.id).filter(Building.final_result.isnot(None)).label("completed"),
    )).one()
    total = totals_row.total or 0
    completed = totals_row.completed or 0

    # 1-1) 최종 판정 6분류(+레거시) — 전체 현황 카드용
    final_rows = (
        _scoped(
            db.query(Building.final_result, sa_func.count(Building.id))
            .filter(Building.final_result.isnot(None))
        )
        .group_by(Building.final_result)
        .all()
    )
    final_counts = {
        "pass": 0,               # 적합
        "pass_supplement": 0,    # 보완적합
        "fail_simple_error": 0,  # 부적합(단순오류)
        "fail_recalculate": 0,   # 부적합(재계산)
        "fail_no_response": 0,   # 부적합(미회신)
        "excluded": 0,           # 대상제외
        "fail": 0,               # 레거시 부적합 (신규 기입 없음, 기존 데이터 집계용)
    }
    for key, count in final_rows:
        if key in final_counts:
            final_counts[key] = count

    # 1-2) 문의사항 상태별 건수
    inquiry_rows = (
        _scoped_by_building_id(
            db.query(Inquiry.status, sa_func.count(Inquiry.id)),
            Inquiry.building_id,
        )
        .group_by(Inquiry.status)
        .all()
    )
    inquiry_counts = {"open": 0, "asking_agency": 0, "completed": 0}
    for status, count in inquiry_rows:
        key = status.value if isinstance(status, InquiryStatus) else str(status)
        if key in inquiry_counts:
            inquiry_counts[key] = count

    # 1-3) 검토서 제출/업로드 수 (ReviewStage 누적) — 건물 phase 기반이 아니라
    # 제출 기록 자체를 센다. 파일 삭제로 s3_file_key가 비어도 제출 이력은 별도 집계한다.
    has_uploaded_file = and_(
        ReviewStage.s3_file_key.isnot(None),
        ReviewStage.s3_file_key != "",
    )
    missing_uploaded_file = or_(
        ReviewStage.s3_file_key.is_(None),
        ReviewStage.s3_file_key == "",
    )
    uploaded_rows = (
        _scoped_by_building_id(
            db.query(
                ReviewStage.phase,
                sa_func.count(ReviewStage.id).filter(has_uploaded_file).label("uploaded"),
                sa_func.count(ReviewStage.id).filter(missing_uploaded_file).label("deleted_submitted"),
            )
            .filter(ReviewStage.report_submitted_at.isnot(None)),
            ReviewStage.building_id,
        )
        .group_by(ReviewStage.phase)
        .all()
    )
    uploaded_reports_preliminary = 0
    uploaded_reports_supplement = 0
    deleted_submitted_reports_preliminary = 0
    deleted_submitted_reports_supplement = 0
    for phase, uploaded_count, deleted_submitted_count in uploaded_rows:
        key = phase.value if hasattr(phase, "value") else str(phase)
        if key == "preliminary":
            uploaded_reports_preliminary += uploaded_count
            deleted_submitted_reports_preliminary += deleted_submitted_count
        elif key.startswith("supplement_"):
            uploaded_reports_supplement += uploaded_count
            deleted_submitted_reports_supplement += deleted_submitted_count

    pending_due_filter = or_(
        and_(
            Building.current_phase == "doc_received",
            ReviewStage.phase == PhaseType.PRELIMINARY,
        ),
        and_(
            Building.current_phase == "supplement_1_received",
            ReviewStage.phase == PhaseType.SUPPLEMENT_1,
        ),
        and_(
            Building.current_phase == "supplement_2_received",
            ReviewStage.phase == PhaseType.SUPPLEMENT_2,
        ),
        and_(
            Building.current_phase == "supplement_3_received",
            ReviewStage.phase == PhaseType.SUPPLEMENT_3,
        ),
        and_(
            Building.current_phase == "supplement_4_received",
            ReviewStage.phase == PhaseType.SUPPLEMENT_4,
        ),
        and_(
            Building.current_phase == "supplement_5_received",
            ReviewStage.phase == PhaseType.SUPPLEMENT_5,
        ),
    )
    phase_group_expr = case(
        (ReviewStage.phase == PhaseType.PRELIMINARY, "preliminary"),
        else_="supplement",
    )
    due_date_rows = (
        _scoped_by_building_id(
            db.query(
                ReviewStage.doc_received_at.label("doc_received_at"),
                ReviewStage.report_due_date.label("report_due_date"),
                phase_group_expr.label("phase_group"),
                sa_func.count(ReviewStage.id)
                .filter(ReviewStage.report_submitted_at.isnot(None))
                .label("submitted"),
                sa_func.count(ReviewStage.id)
                .filter(
                    and_(
                        ReviewStage.report_submitted_at.is_(None),
                        pending_due_filter,
                    )
                )
                .label("not_submitted"),
            )
            .join(Building, ReviewStage.building_id == Building.id)
            .filter(
                ReviewStage.report_due_date.isnot(None),
                or_(
                    ReviewStage.report_submitted_at.isnot(None),
                    and_(
                        ReviewStage.report_submitted_at.is_(None),
                        pending_due_filter,
                    ),
                ),
            ),
            ReviewStage.building_id,
        )
        .group_by(
            ReviewStage.doc_received_at,
            ReviewStage.report_due_date,
            phase_group_expr,
        )
        .order_by(
            ReviewStage.report_due_date,
            ReviewStage.doc_received_at,
            phase_group_expr,
        )
        .all()
    )
    due_date_submission_stats = [
        {
            "doc_received_at": (
                row.doc_received_at.isoformat()
                if row.doc_received_at is not None
                else None
            ),
            "report_due_date": row.report_due_date.isoformat(),
            "phase_group": row.phase_group,
            "submitted": row.submitted or 0,
            "not_submitted": row.not_submitted or 0,
            "total": (row.submitted or 0) + (row.not_submitted or 0),
        }
        for row in due_date_rows
        if (row.not_submitted or 0) > 0
    ]

    # 2) phase 별 건수
    phase_counts_raw = (
        _scoped(db.query(Building.current_phase, sa_func.count(Building.id)))
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

    reviewer_name_expr = sa_func.coalesce(User.name, Building.assigned_reviewer_name)
    reviewer_assigned_filter = or_(
        Building.reviewer_id.isnot(None),
        Building.assigned_reviewer_name.isnot(None),
    )

    # 3) 위원별 기본 집계
    reviewer_stats_raw = (
        _scoped(
            db.query(
                reviewer_name_expr.label("name"),
                sa_func.min(Reviewer.group_no).label("group_no"),
                sa_func.count(Building.id).label("total"),
                sa_func.count(Building.id).filter(Building.current_phase == "doc_received").label("doc_received"),
                sa_func.count(Building.id).filter(Building.final_result.isnot(None)).label("completed"),
                sa_func.sum(sa_func.coalesce(Building.gross_area, 0)).label("total_area"),
                sa_func.count(Building.id).filter(Building.gross_area >= 1000).label("area_over_1000"),
                sa_func.count(Building.id).filter(
                    (Building.is_special_structure == True) |
                    (Building.is_high_rise == True) |
                    (Building.is_multi_use == True) |
                    (Building.is_quasi_multi_use == True)
                ).label("high_risk"),
            )
            .outerjoin(Reviewer, Building.reviewer_id == Reviewer.id)
            .outerjoin(User, Reviewer.user_id == User.id)
            .filter(reviewer_assigned_filter)
        )
        .group_by(reviewer_name_expr)
        .all()
    )

    supplement_phases = (
        PhaseType.SUPPLEMENT_1,
        PhaseType.SUPPLEMENT_2,
        PhaseType.SUPPLEMENT_3,
        PhaseType.SUPPLEMENT_4,
        PhaseType.SUPPLEMENT_5,
    )
    preliminary_phase_filter = ReviewStage.phase == PhaseType.PRELIMINARY
    supplement_phase_filter = ReviewStage.phase.in_(supplement_phases)
    submitted_filter = ReviewStage.report_submitted_at.isnot(None)
    reviewer_stage_stats_raw = (
        _scoped_by_building_id(
            db.query(
                reviewer_name_expr.label("name"),
                sa_func.count(ReviewStage.id).filter(
                    and_(
                        preliminary_phase_filter,
                        ReviewStage.doc_received_at.isnot(None),
                    )
                ).label("preliminary_doc_received"),
                sa_func.count(ReviewStage.id).filter(
                    and_(preliminary_phase_filter, submitted_filter)
                ).label("preliminary_report_submitted"),
                sa_func.count(ReviewStage.id).filter(
                    and_(
                        preliminary_phase_filter,
                        submitted_filter,
                        ReviewStage.result == ResultType.PASS,
                    )
                ).label("preliminary_pass"),
                sa_func.count(ReviewStage.id).filter(
                    and_(
                        preliminary_phase_filter,
                        submitted_filter,
                        ReviewStage.result == ResultType.SIMPLE_ERROR,
                    )
                ).label("preliminary_simple_error"),
                sa_func.count(ReviewStage.id).filter(
                    and_(
                        preliminary_phase_filter,
                        submitted_filter,
                        ReviewStage.result == ResultType.RECALCULATE,
                    )
                ).label("preliminary_recalculate"),
                sa_func.count(ReviewStage.id).filter(
                    and_(
                        supplement_phase_filter,
                        ReviewStage.doc_received_at.isnot(None),
                    )
                ).label("supplement_doc_received"),
                sa_func.count(ReviewStage.id).filter(
                    and_(supplement_phase_filter, submitted_filter)
                ).label("supplement_report_submitted"),
                sa_func.count(ReviewStage.id).filter(
                    and_(
                        supplement_phase_filter,
                        submitted_filter,
                        ReviewStage.result == ResultType.PASS,
                    )
                ).label("supplement_pass"),
                sa_func.count(ReviewStage.id).filter(
                    and_(
                        supplement_phase_filter,
                        submitted_filter,
                        ReviewStage.result == ResultType.SIMPLE_ERROR,
                    )
                ).label("supplement_simple_error"),
                sa_func.count(ReviewStage.id).filter(
                    and_(
                        supplement_phase_filter,
                        submitted_filter,
                        ReviewStage.result == ResultType.RECALCULATE,
                    )
                ).label("supplement_recalculate"),
            )
            .join(Building, ReviewStage.building_id == Building.id)
            .outerjoin(Reviewer, Building.reviewer_id == Reviewer.id)
            .outerjoin(User, Reviewer.user_id == User.id)
            .filter(reviewer_assigned_filter),
            ReviewStage.building_id,
        )
        .group_by(reviewer_name_expr)
        .all()
    )
    reviewer_stage_stats_by_name: dict[str, dict[str, object]] = {}
    for row in reviewer_stage_stats_raw:
        if not row.name:
            continue
        reviewer_stage_stats_by_name[row.name] = {
            "preliminary": {
                "doc_received": row.preliminary_doc_received or 0,
                "report_submitted": row.preliminary_report_submitted or 0,
                "results": {
                    "pass": row.preliminary_pass or 0,
                    "simple_error": row.preliminary_simple_error or 0,
                    "recalculate": row.preliminary_recalculate or 0,
                },
            },
            "supplement": {
                "doc_received": row.supplement_doc_received or 0,
                "report_submitted": row.supplement_report_submitted or 0,
                "results": {
                    "pass": row.supplement_pass or 0,
                    "simple_error": row.supplement_simple_error or 0,
                    "recalculate": row.supplement_recalculate or 0,
                },
            },
        }

    # 4) 위원별 doc_received 상태 건물 중 예비검토서 제출/미제출 수 (LEFT JOIN 1회)
    # - building당 (phase=PRELIMINARY, submitted_at NOT NULL) review_stage 최대 1건이라는 도메인
    #   전제 하에 COUNT(ReviewStage.id)로 제출 건수를 집계한다. 가정이 깨지면 DISTINCT 필요.
    received_stats_raw = (
        _scoped(
            db.query(
                reviewer_name_expr.label("name"),
                sa_func.count(Building.id).label("received"),
                sa_func.count(ReviewStage.id).label("received_submitted"),
            )
            .outerjoin(Reviewer, Building.reviewer_id == Reviewer.id)
            .outerjoin(User, Reviewer.user_id == User.id)
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
                reviewer_assigned_filter,
            )
        )
        .group_by(reviewer_name_expr)
        .all()
    )
    received_by_reviewer: dict[str, tuple[int, int]] = {
        name: (received or 0, received_submitted or 0)
        for name, received, received_submitted in received_stats_raw
    }

    reviewer_stats = []
    empty_reviewer_stage_stats = {
        "preliminary": {
            "doc_received": 0,
            "report_submitted": 0,
            "results": {"pass": 0, "simple_error": 0, "recalculate": 0},
        },
        "supplement": {
            "doc_received": 0,
            "report_submitted": 0,
            "results": {"pass": 0, "simple_error": 0, "recalculate": 0},
        },
    }
    for row in reviewer_stats_raw:
        if not row.name:
            continue
        name = row.name
        received_total, submitted_count = received_by_reviewer.get(name, (0, 0))
        not_submitted_count = received_total - submitted_count
        stage_stats = reviewer_stage_stats_by_name.get(name, empty_reviewer_stage_stats)

        reviewer_stats.append({
            "name": name,
            "group_no": row.group_no,
            "total": row.total or 0,
            "total_area": float(row.total_area or 0),
            "area_over_1000": row.area_over_1000 or 0,
            "high_risk": row.high_risk or 0,
            "doc_received": row.doc_received or 0,
            "submitted": submitted_count,
            "not_submitted": not_submitted_count,
            "completed": row.completed or 0,
            "preliminary": stage_stats["preliminary"],
            "supplement": stage_stats["supplement"],
        })
    reviewer_stats.sort(
        key=lambda row: (
            row["group_no"] is None,
            row["group_no"] or 0,
            str(row["name"]),
        )
    )

    related_tech_coop_target_filter = related_tech_target_filter()
    related_tech_coop_input_filter = related_tech_coop_filter()
    related_tech_coop_missing_filter = and_(
        related_tech_coop_target_filter,
        ~related_tech_coop_input_filter,
    )

    gross_area_for_stats = sa_func.coalesce(Building.gross_area, 0)
    floors_above_for_stats = sa_func.coalesce(Building.floors_above, 0)
    drawing_creator_qualification = sa_func.trim(
        sa_func.coalesce(Building.drawing_creator_qualification, "")
    )

    area_stats_raw = (
        _scoped(
            db.query(
                Building.sido.label("sido"),
                Building.sigungu.label("sigungu"),
                sa_func.count(Building.id).filter(
                    and_(gross_area_for_stats >= 0, gross_area_for_stats < 300)
                ).label("area_0_300"),
                sa_func.count(Building.id).filter(
                    and_(gross_area_for_stats >= 300, gross_area_for_stats < 600)
                ).label("area_300_600"),
                sa_func.count(Building.id).filter(
                    and_(gross_area_for_stats >= 600, gross_area_for_stats < 1000)
                ).label("area_600_1000"),
                sa_func.count(Building.id).filter(
                    and_(gross_area_for_stats >= 1000, gross_area_for_stats < 5000)
                ).label("area_1000_5000"),
                sa_func.count(Building.id).filter(
                    gross_area_for_stats >= 5000
                ).label("area_5000_over"),
            )
        )
        .group_by(Building.sido, Building.sigungu)
        .all()
    )
    floor_stats_raw = (
        _scoped(
            db.query(
                Building.sido.label("sido"),
                Building.sigungu.label("sigungu"),
                sa_func.count(Building.id).filter(
                    floors_above_for_stats < 6
                ).label("floors_under_6"),
                sa_func.count(Building.id).filter(
                    and_(floors_above_for_stats >= 6, floors_above_for_stats < 16)
                ).label("floors_6_under_16"),
                sa_func.count(Building.id).filter(
                    floors_above_for_stats >= 16
                ).label("floors_16_over"),
            )
        )
        .group_by(Building.sido, Building.sigungu)
        .all()
    )
    risk_stats_raw = (
        _scoped(
            db.query(
                Building.sido.label("sido"),
                Building.sigungu.label("sigungu"),
                sa_func.count(Building.id).label("total"),
                sa_func.count(Building.id).filter(
                    Building.is_special_structure.is_(True)
                ).label("special"),
                sa_func.count(Building.id).filter(
                    Building.is_multi_use.is_(True)
                ).label("multi_use"),
                sa_func.count(Building.id).filter(
                    Building.is_high_rise.is_(True)
                ).label("high_rise"),
                sa_func.count(Building.id).filter(
                    Building.is_quasi_multi_use.is_(True)
                ).label("quasi_multi_use"),
                sa_func.count(Building.id).filter(
                    related_tech_coop_target_filter
                ).label("related_tech_coop_target"),
                sa_func.count(Building.id).filter(
                    related_tech_coop_input_filter
                ).label("related_tech_coop"),
                sa_func.count(Building.id).filter(
                    related_tech_coop_missing_filter
                ).label("related_tech_coop_missing"),
            )
        )
        .group_by(Building.sido, Building.sigungu)
        .all()
    )
    drawing_creator_stats_raw = (
        _scoped(
            db.query(
                Building.sido.label("sido"),
                Building.sigungu.label("sigungu"),
                sa_func.count(Building.id).filter(
                    drawing_creator_qualification == "건축사"
                ).label("drawing_creator_architect"),
                sa_func.count(Building.id).filter(
                    drawing_creator_qualification == "건축구조기술사"
                ).label("drawing_creator_structural_engineer"),
                sa_func.count(Building.id).filter(
                    drawing_creator_qualification.notin_(("건축사", "건축구조기술사"))
                ).label("drawing_creator_unknown"),
            )
        )
        .group_by(Building.sido, Building.sigungu)
        .all()
    )
    regional_stats = {
        "area": _merge_regional_rows(area_stats_raw, AREA_STAT_KEYS),
        "floors": _merge_regional_rows(floor_stats_raw, FLOOR_STAT_KEYS),
        "risk": _merge_regional_rows(risk_stats_raw, RISK_STAT_KEYS),
        "drawing_creator": _merge_regional_rows(
            drawing_creator_stats_raw,
            DRAWING_CREATOR_STAT_KEYS,
        ),
    }

    # 5) 심각도 통계 — 상세의견 분류별 집계 테이블을 기준으로 전체/분류/단계별 피벗 생성
    severity_total_rows = (
        _scoped_by_building_id(
            db.query(
                ReviewSeveritySummary.severity,
                sa_func.sum(ReviewSeveritySummary.count),
            )
            .join(ReviewStage, ReviewSeveritySummary.stage_id == ReviewStage.id),
            ReviewStage.building_id,
        )
        .group_by(ReviewSeveritySummary.severity)
        .all()
    )
    severity_totals = _empty_severity_counts()
    for severity, count in severity_total_rows:
        if severity in severity_totals:
            severity_totals[severity] = int(count or 0)

    severity_category_rows = (
        _scoped_by_building_id(
            db.query(
                ReviewSeveritySummary.category,
                ReviewSeveritySummary.severity,
                sa_func.sum(ReviewSeveritySummary.count),
            )
            .join(ReviewStage, ReviewSeveritySummary.stage_id == ReviewStage.id),
            ReviewStage.building_id,
        )
        .group_by(ReviewSeveritySummary.category, ReviewSeveritySummary.severity)
        .all()
    )
    category_map: dict[str, dict[str, int]] = {}
    for category, severity, count in severity_category_rows:
        if severity not in SEVERITY_LABELS:
            continue
        counts = category_map.setdefault(category, _empty_severity_counts())
        counts[severity] = int(count or 0)
    severity_by_category = [
        {"category": category, "counts": counts, "total": sum(counts.values())}
        for category, counts in category_map.items()
    ]
    severity_by_category.sort(key=lambda row: (-row["total"], row["category"]))

    severity_phase_rows = (
        _scoped_by_building_id(
            db.query(
                ReviewStage.phase,
                ReviewSeveritySummary.severity,
                sa_func.sum(ReviewSeveritySummary.count),
            )
            .join(ReviewStage, ReviewSeveritySummary.stage_id == ReviewStage.id),
            ReviewStage.building_id,
        )
        .group_by(ReviewStage.phase, ReviewSeveritySummary.severity)
        .all()
    )
    phase_order = {
        "preliminary": 0,
        "supplement_1": 1,
        "supplement_2": 2,
        "supplement_3": 3,
        "supplement_4": 4,
        "supplement_5": 5,
    }
    phase_map: dict[str, dict[str, int]] = {}
    for phase, severity, count in severity_phase_rows:
        if severity not in SEVERITY_LABELS:
            continue
        phase_key = phase.value if hasattr(phase, "value") else str(phase)
        counts = phase_map.setdefault(phase_key, _empty_severity_counts())
        counts[severity] = int(count or 0)
    severity_by_phase = [
        {"phase": phase, "counts": counts, "total": sum(counts.values())}
        for phase, counts in phase_map.items()
    ]
    severity_by_phase.sort(key=lambda row: phase_order.get(row["phase"], 999))

    related_tech_coop_status_expr = case(
        (related_tech_coop_input_filter, "cooperated"),
        else_="not_cooperated",
    )
    severity_related_tech_coop_rows = (
        _scoped_by_building_id(
            db.query(
                related_tech_coop_status_expr.label("status"),
                ReviewSeveritySummary.severity,
                sa_func.sum(ReviewSeveritySummary.count),
            )
            .join(ReviewStage, ReviewSeveritySummary.stage_id == ReviewStage.id)
            .join(Building, ReviewStage.building_id == Building.id),
            ReviewStage.building_id,
        )
        .group_by(related_tech_coop_status_expr, ReviewSeveritySummary.severity)
        .all()
    )
    related_tech_coop_map = {
        "cooperated": _empty_severity_counts(),
        "not_cooperated": _empty_severity_counts(),
    }
    for status, severity, count in severity_related_tech_coop_rows:
        if status not in related_tech_coop_map or severity not in SEVERITY_LABELS:
            continue
        related_tech_coop_map[status][severity] = int(count or 0)
    severity_by_related_tech_coop = [
        {"status": status, "counts": counts, "total": sum(counts.values())}
        for status, counts in related_tech_coop_map.items()
    ]

    # 5-1) 검토서 1건당 최고 심각도 기준 집계
    # 한 검토서 안에 여러 상세의견이 있어도 가장 높은 L값 하나만 1건으로 센다.
    severity_rank = case(
        (ReviewSeveritySummary.severity == "L0", 0),
        (ReviewSeveritySummary.severity == "L1", 1),
        (ReviewSeveritySummary.severity == "L2", 2),
        (ReviewSeveritySummary.severity == "L3", 3),
        (ReviewSeveritySummary.severity == "L4", 4),
        else_=-1,
    )
    severity_report_max_rows = (
        _scoped_by_building_id(
            db.query(
                ReviewStage.id,
                ReviewStage.phase,
                ReviewStage.result,
                sa_func.max(severity_rank),
            )
            .outerjoin(
                ReviewSeveritySummary,
                ReviewSeveritySummary.stage_id == ReviewStage.id,
            )
            .filter(
                or_(
                    ReviewSeveritySummary.id.isnot(None),
                    ReviewStage.result == ResultType.PASS,
                )
            ),
            ReviewStage.building_id,
        )
        .group_by(ReviewStage.id, ReviewStage.phase, ReviewStage.result)
        .all()
    )
    severity_report_max_totals = _empty_report_max_counts()
    severity_report_max_phase_map: dict[str, dict[str, int]] = {}
    for _, phase, result, max_rank in severity_report_max_rows:
        if max_rank is None or int(max_rank) < 0:
            result_key = result.value if hasattr(result, "value") else str(result)
            if result_key != ResultType.PASS.value:
                continue
            max_label = "pass"
        elif int(max_rank) >= len(SEVERITY_LABELS):
            continue
        else:
            max_label = SEVERITY_LABELS[int(max_rank)]
        severity_report_max_totals[max_label] += 1
        phase_key = phase.value if hasattr(phase, "value") else str(phase)
        counts = severity_report_max_phase_map.setdefault(phase_key, _empty_report_max_counts())
        counts[max_label] += 1
    severity_report_max_by_phase = [
        {"phase": phase, "counts": counts, "total": sum(counts.values())}
        for phase, counts in severity_report_max_phase_map.items()
    ]
    severity_report_max_by_phase.sort(key=lambda row: phase_order.get(row["phase"], 999))

    # 6) 키워드/표현 품질 분석 — 저장된 상세검토 원문을 예비/보완 구분으로 집계
    actual_reviewer = aliased(Reviewer)
    actual_reviewer_user = aliased(User)
    actual_reviewer_group_no = (
        select(actual_reviewer.group_no)
        .join(actual_reviewer_user, actual_reviewer.user_id == actual_reviewer_user.id)
        .where(
            actual_reviewer_user.role == UserRole.REVIEWER,
            actual_reviewer_user.name == ReviewStage.reviewer_name,
        )
        .limit(1)
        .scalar_subquery()
    )
    opinion_detail_rows = (
        _scoped_by_building_id(
            db.query(
                ReviewOpinionDetail.id.label("detail_id"),
                ReviewOpinionDetail.phase_group,
                ReviewOpinionDetail.severity,
                ReviewOpinionDetail.content,
                ReviewOpinionDetail.row_number,
                ReviewOpinionDetail.quality_decision,
                ReviewStage.reviewer_name.label("actual_reviewer_name"),
                actual_reviewer_group_no.label("actual_reviewer_group_no"),
                Building.mgmt_no,
                Building.assigned_reviewer_name,
                Reviewer.group_no,
                User.name.label("reviewer_user_name"),
            )
            .join(ReviewStage, ReviewOpinionDetail.stage_id == ReviewStage.id)
            .join(Building, ReviewStage.building_id == Building.id)
            .outerjoin(Reviewer, Building.reviewer_id == Reviewer.id)
            .outerjoin(User, Reviewer.user_id == User.id),
            ReviewStage.building_id,
        )
        .order_by(
            Building.mgmt_no,
            ReviewStage.phase_order,
            ReviewOpinionDetail.row_number,
            ReviewOpinionDetail.id,
        )
        .all()
    )
    _release_read_connection(db)
    detail_counts = {"preliminary": 0, "supplement": 0}
    keyword_map: dict[str, dict[str, int | str]] = {}
    quality_term_map: dict[str, dict[str, int | str]] = {}
    quality_category_map: dict[str, dict[str, int | str]] = {}
    quality_tag_map: dict[str, dict[str, int | str]] = {}
    quality_level_map: dict[str, dict[str, int | str]] = {}
    quality_items: list[dict[str, object]] = []
    quality_total_details = 0
    for row in opinion_detail_rows:
        phase_group = row.phase_group
        severity = row.severity
        content = row.content or ""
        if phase_group in detail_counts:
            detail_counts[phase_group] += 1
        for keyword in match_keywords(content):
            item = keyword_map.setdefault(keyword, {
                "keyword": keyword,
                "total": 0,
                "preliminary": 0,
                "supplement": 0,
                "L0": 0,
                "L1": 0,
                "L2": 0,
                "L3": 0,
                "L4": 0,
            })
            item["total"] = int(item["total"]) + 1
            if phase_group in ("preliminary", "supplement"):
                item[phase_group] = int(item[phase_group]) + 1
            if severity in SEVERITY_LABELS:
                item[severity] = int(item[severity]) + 1

        if row.quality_decision == "suitable":
            continue

        quality_total_details += 1
        quality_matches = match_opinion_quality(content)
        if not quality_matches:
            continue

        matched_terms = sorted({match.term for match in quality_matches})
        matched_categories = sorted({match.category for match in quality_matches})
        matched_tags = sorted({match.tag for match in quality_matches})
        matched_levels = sorted({match.level for match in quality_matches})
        recommended_replacements = sorted({
            match.replacement
            for match in quality_matches
            if match.replacement
        })
        for term in matched_terms:
            term_item = quality_term_map.setdefault(term, {"term": term, "count": 0})
            term_item["count"] = int(term_item["count"]) + 1
        for category in matched_categories:
            category_item = quality_category_map.setdefault(
                category,
                {"category": category, "count": 0},
            )
            category_item["count"] = int(category_item["count"]) + 1
        for tag in matched_tags:
            tag_item = quality_tag_map.setdefault(tag, {"tag": tag, "count": 0})
            tag_item["count"] = int(tag_item["count"]) + 1
        for level in matched_levels:
            level_item = quality_level_map.setdefault(level, {"level": level, "count": 0})
            level_item["count"] = int(level_item["count"]) + 1
        actual_reviewer_name = (row.actual_reviewer_name or "").strip()
        assigned_reviewer_name = row.reviewer_user_name or row.assigned_reviewer_name
        group_no = row.actual_reviewer_group_no if actual_reviewer_name else row.group_no
        quality_items.append({
            "id": int(row.detail_id),
            "mgmt_no": row.mgmt_no,
            "group_no": group_no,
            "reviewer_name": actual_reviewer_name or assigned_reviewer_name,
            "opinion": content,
            "matched_terms": matched_terms,
            "matched_categories": matched_categories,
            "matched_tags": matched_tags,
            "matched_levels": matched_levels,
            "recommended_replacements": recommended_replacements,
            "quality_decision": row.quality_decision or "unsuitable",
        })
    keyword_rows = sorted(
        keyword_map.values(),
        key=lambda row: (-int(row["total"]), str(row["keyword"])),
    )
    quality_term_rows = sorted(
        quality_term_map.values(),
        key=lambda row: (-int(row["count"]), str(row["term"])),
    )
    quality_category_rows = sorted(
        quality_category_map.values(),
        key=lambda row: (-int(row["count"]), str(row["category"])),
    )
    quality_tag_rows = sorted(
        quality_tag_map.values(),
        key=lambda row: (-int(row["count"]), str(row["tag"])),
    )
    quality_level_rows = sorted(
        quality_level_map.values(),
        key=lambda row: (-int(row["count"]), str(row["level"])),
    )

    result: dict[str, object] = {
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
        "deleted_submitted_reports_preliminary": deleted_submitted_reports_preliminary,
        "deleted_submitted_reports_supplement": deleted_submitted_reports_supplement,
        "due_date_submission_stats": due_date_submission_stats,
        "completed": completed,
        # 최종 판정 6분류(+레거시)
        # (적합/보완적합/부적합(단순오류)/부적합(재계산)/부적합(미회신)/대상제외 + 레거시 부적합)
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
        "regional_stats": regional_stats,
        "severity_stats": {
            "total": sum(severity_totals.values()),
            "totals": severity_totals,
            "by_category": severity_by_category,
            "by_phase": severity_by_phase,
            "by_related_tech_coop": severity_by_related_tech_coop,
            "by_report_max": {
                "total": sum(severity_report_max_totals.values()),
                "totals": severity_report_max_totals,
                "by_phase": severity_report_max_by_phase,
            },
        },
        "keyword_stats": {
            "total_details": len(opinion_detail_rows),
            "detail_counts": detail_counts,
            "by_keyword": keyword_rows,
        },
        "opinion_quality_stats": {
            "total_details": quality_total_details,
            "flagged_details": len(quality_items),
            "clean_details": quality_total_details - len(quality_items),
            "by_category": quality_category_rows,
            "by_tag": quality_tag_rows,
            "by_level": quality_level_rows,
            "by_term": quality_term_rows,
            "items": quality_items,
        },
    }
    _stats_cache_set(db, cache_key, result)
    return result


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
    from models.review_stage import PhaseType, ReviewStage

    query = db.query(Building)

    # 가시성 필터: REVIEWER → 본인 reviewer_id, SECRETARY(조 배정) → 같은 조 검토위원,
    # 그 외(팀장/총괄간사/조 미배정 간사) → 전체. 헬퍼가 None 이면 무필터.
    visibility = building_visibility_filter(current_user)
    if visibility is not None:
        query = query.filter(visibility)
    is_reviewer = current_user.role == UserRole.REVIEWER

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

    # 정렬: 통합관리대장 헤더 클릭에서 사용하는 조합 컬럼도 서버에서 정렬한다.
    sort_key = sort_by or "mgmt_no"
    sort_desc = sort_order == "desc"
    if sort_key == "latest_result":
        latest_phase_subq = (
            db.query(
                ReviewStage.building_id.label("building_id"),
                func.max(ReviewStage.phase_order).label("latest_phase_order"),
            )
            .filter(ReviewStage.result.isnot(None))
            .group_by(ReviewStage.building_id)
            .subquery()
        )
        latest_result_subq = (
            db.query(
                ReviewStage.building_id.label("building_id"),
                ReviewStage.result.label("latest_result"),
            )
            .join(
                latest_phase_subq,
                (latest_phase_subq.c.building_id == ReviewStage.building_id)
                & (latest_phase_subq.c.latest_phase_order == ReviewStage.phase_order),
            )
            .subquery()
        )
        query = query.outerjoin(
            latest_result_subq,
            latest_result_subq.c.building_id == Building.id,
        )
        order_cols = [latest_result_subq.c.latest_result]
    elif sort_key == "report_due_date":
        BuildingForDue = aliased(Building)
        pending_due_conditions = [
            (BuildingForDue.current_phase == received_phase)
            & (ReviewStage.phase == submit_phase)
            for received_phase, submit_phase in (
                ("doc_received", PhaseType.PRELIMINARY),
                ("supplement_1_received", PhaseType.SUPPLEMENT_1),
                ("supplement_2_received", PhaseType.SUPPLEMENT_2),
                ("supplement_3_received", PhaseType.SUPPLEMENT_3),
                ("supplement_4_received", PhaseType.SUPPLEMENT_4),
                ("supplement_5_received", PhaseType.SUPPLEMENT_5),
            )
        ]
        pending_due_subq = (
            db.query(
                ReviewStage.building_id.label("building_id"),
                func.max(ReviewStage.report_due_date).label("report_due_date"),
            )
            .join(BuildingForDue, BuildingForDue.id == ReviewStage.building_id)
            .filter(
                ReviewStage.report_submitted_at.is_(None),
                ReviewStage.report_due_date.isnot(None),
                or_(*pending_due_conditions),
            )
            .group_by(ReviewStage.building_id)
            .subquery()
        )
        query = query.outerjoin(
            pending_due_subq,
            pending_due_subq.c.building_id == Building.id,
        )
        order_cols = [pending_due_subq.c.report_due_date]
    else:
        sort_map = {
            "mgmt_no": [Building.mgmt_no],
            "assigned_reviewer_name": [Building.assigned_reviewer_name],
            "reviewer_name": [Building.assigned_reviewer_name],
            "address": [
                Building.sido,
                Building.sigungu,
                Building.beopjeongdong,
                Building.main_lot_no,
                Building.sub_lot_no,
            ],
            "building_name": [Building.building_name],
            "main_structure": [Building.main_structure],
            "high_risk_type": [Building.high_risk_type],
            "current_phase": [Building.current_phase],
            "final_result": [Building.final_result],
        }
        order_cols = sort_map.get(sort_key, [Building.mgmt_no])
    order_by = []
    for col in order_cols:
        ordered_col = col.desc() if sort_desc else col.asc()
        if sort_key == "report_due_date":
            ordered_col = ordered_col.nulls_last()
        order_by.append(ordered_col)
    if sort_key != "mgmt_no":
        order_by.append(Building.mgmt_no.asc())

    # N+1 제거: building.reviewer.user를 한 번에 eager load
    buildings = (
        query.options(selectinload(Building.reviewer).selectinload(Reviewer.user))
        .order_by(*order_by)
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    registered_names = _get_registered_names(db)
    building_ids = [building.id for building in buildings]
    latest_by_building: dict[int, ReviewStage] = {}
    pending_by_building: dict[int, ReviewStage] = {}
    if building_ids:
        latest_stages = (
            db.query(ReviewStage)
            .filter(
                ReviewStage.building_id.in_(building_ids),
                ReviewStage.result.isnot(None),
            )
            .order_by(ReviewStage.building_id, ReviewStage.phase_order.desc())
            .all()
        )
        for stage in latest_stages:
            if stage.building_id not in latest_by_building:
                latest_by_building[stage.building_id] = stage
        pending_stages = (
            db.query(ReviewStage)
            .filter(
                ReviewStage.building_id.in_(building_ids),
                ReviewStage.report_submitted_at.is_(None),
                ReviewStage.report_due_date.isnot(None),
            )
            .order_by(ReviewStage.building_id, ReviewStage.phase_order.desc())
            .all()
        )
        buildings_by_id = {building.id: building for building in buildings}
        for stage in pending_stages:
            building = buildings_by_id.get(stage.building_id)
            if (
                building
                and stage.building_id not in pending_by_building
                and _is_current_pending_stage(building, stage)
            ):
                pending_by_building[stage.building_id] = stage

    items = []
    for building in buildings:
        item = _to_response(building, registered_names)
        latest_stage = latest_by_building.get(building.id)
        if latest_stage and latest_stage.result:
            item["latest_result"] = latest_stage.result.value
            item["latest_inappropriate"] = bool(latest_stage.inappropriate_review_needed)
        pending_stage = pending_by_building.get(building.id)
        if pending_stage and pending_stage.report_due_date:
            item["report_due_date"] = pending_stage.report_due_date.isoformat()
        items.append(item)
    return BuildingListResponse(items=items, total=total)


@router.get("/reviewer-names")
def get_reviewer_names(
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
    """배정된 검토위원 이름 목록 (관리자 전용 — 위원 enumeration 차단).

    간사(조 배정)는 같은 조 검토위원이 담당하는 건물의 이름만 노출.
    """
    visibility = building_visibility_filter(current_user)
    q = db.query(Building.assigned_reviewer_name).filter(
        Building.assigned_reviewer_name.isnot(None)
    )
    if visibility is not None:
        q = q.filter(visibility)
    names = q.distinct().order_by(Building.assigned_reviewer_name).all()
    return [n[0] for n in names]


@router.get("/reviewer-options", response_model=list[ReviewerOptionResponse])
def get_reviewer_options(
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(
            UserRole.TEAM_LEADER,
            UserRole.CHIEF_SECRETARY,
            UserRole.SECRETARY,
        )
    ),
):
    """상세 화면에서 검토자 변경 시 선택할 수 있는 등록 검토위원 목록."""
    user_visibility = visible_reviewer_user_ids(current_user)
    query = (
        db.query(Reviewer)
        .join(User, Reviewer.user_id == User.id)
        .filter(User.role == UserRole.REVIEWER, User.is_active.is_(True))
    )
    if user_visibility is not None:
        query = query.filter(user_visibility)
    reviewers = (
        query
        .order_by(Reviewer.group_no.asc().nulls_last(), User.name.asc(), Reviewer.id.asc())
        .all()
    )
    return [
        ReviewerOptionResponse(
            reviewer_id=reviewer.id,
            user_id=reviewer.user.id,
            name=reviewer.user.name,
            group_no=reviewer.group_no,
            email=reviewer.user.email,
            phone=reviewer.user.phone,
        )
        for reviewer in reviewers
        if reviewer.user is not None
    ]


@router.post("", response_model=BuildingResponse, status_code=201)
def create_building(
    body: BuildingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(
            UserRole.TEAM_LEADER,
            UserRole.CHIEF_SECRETARY,
            UserRole.SECRETARY,
        )
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
    registered_names = _get_registered_names(db)
    return _to_response(building, registered_names)


@router.get("/reviewer-schedule")
def reviewer_schedule(
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
    """검토위원별 일정관리 요약 — 대시보드 "검토위원별 일정관리" 테이블 데이터.

    활성 REVIEWER 사용자 전체를 행으로 노출하고, 각각에 대해
    현재 단계가 도서 접수 상태이고, 해당 단계의
    `review_stages.report_submitted_at IS NULL AND report_due_date IS NOT NULL` 인 건을
    오늘 기준 D-3/D-2/D-1/D-day/초과 카운트로 집계한다. D+4 이상 예정이거나 일정이 없는
    건은 in_progress 에만 합산된다. 미제출이 없는 검토위원도 모든 카운트 0으로 표시.
    """
    from models.review_stage import ReviewStage
    from models.reviewer import Reviewer

    today = business_today()

    # 1) 활성 사용자 전체(팀장·총괄간사·간사·검토위원)를 0 초기화로 준비.
    #    간사(조 배정)는 같은 조 검토위원만 보도록 visibility 필터.
    user_visibility = visible_reviewer_user_ids(current_user)
    reviewer_users_q = db.query(User).filter(User.is_active.is_(True))
    if user_visibility is not None:
        reviewer_users_q = reviewer_users_q.filter(user_visibility)
    reviewer_users = reviewer_users_q.order_by(User.name).all()
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
            "on_time_rate": None,
            "_due_total": 0,
            "_due_on_time": 0,
        }
        for u in reviewer_users
    }

    # 2) 미제출 stage 를 집계해 위 buckets 에 반영
    #    간사는 같은 조 건물의 stage 만 집계 (visibility).
    visibility = building_visibility_filter(current_user)
    rows_q = (
        db.query(ReviewStage, Building, User)
        .join(Building, ReviewStage.building_id == Building.id)
        .join(Reviewer, Building.reviewer_id == Reviewer.id)
        .join(User, Reviewer.user_id == User.id)
        .filter(
            ReviewStage.report_submitted_at.is_(None),
            ReviewStage.report_due_date.isnot(None),
            Building.current_phase.in_(list(RECEIVED_PHASES)),
            User.is_active.is_(True),
        )
    )
    if visibility is not None:
        rows_q = rows_q.filter(visibility)
    rows = rows_q.all()
    for stage, building, user in rows:
        if not _is_current_pending_stage(building, stage):
            continue
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
            "on_time_rate": None,
            "_due_total": 0,
            "_due_on_time": 0,
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

    # 3) 일정 준수율 집계 — 마감 경과(제출 or 초과 미제출) 건 중 정시 제출 비율
    closure_q = (
        db.query(ReviewStage, Building, User)
        .join(Building, ReviewStage.building_id == Building.id)
        .join(Reviewer, Building.reviewer_id == Reviewer.id)
        .join(User, Reviewer.user_id == User.id)
        .filter(
            ReviewStage.report_due_date.isnot(None),
            User.is_active.is_(True),
        )
    )
    if visibility is not None:
        closure_q = closure_q.filter(visibility)
    closure_rows = closure_q.all()
    for stage, building, user in closure_rows:
        # 마감 경과 여부: 제출됐거나 예정일이 이미 지났음
        is_submitted = stage.report_submitted_at is not None
        if not is_submitted and not _is_current_pending_stage(building, stage):
            continue
        is_past_due = stage.report_due_date < today
        if not is_submitted and not is_past_due:
            continue
        info = by_user.get(user.id)
        if info is None:
            continue
        info["_due_total"] += 1
        if is_submitted and stage.report_submitted_at <= stage.report_due_date:
            info["_due_on_time"] += 1

    # 백분율 환산 + 임시 필드 제거
    for info in by_user.values():
        total = info.pop("_due_total", 0)
        on_time = info.pop("_due_on_time", 0)
        info["on_time_rate"] = (
            round(on_time / total * 100) if total > 0 else None
        )

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
            UserRole.REVIEWER,
            UserRole.SECRETARY,
            UserRole.CHIEF_SECRETARY,
            UserRole.TEAM_LEADER,
            UserRole.MANAGER,
        )
    ),
):
    """개인 대시보드 통계 (본인 담당 건물 기준).

    검토위원은 `reviewer_id`만 사용한다. 총괄간사는 실무상 직접 검토자로
    배정될 수 있으므로 자기 이름 배정 건도 포함한다.
    """
    from sqlalchemy import and_, func as sa_func, or_
    from models.review_stage import ReviewStage

    final_counts = {
        "pass": 0,               # 적합
        "pass_supplement": 0,    # 보완적합
        "fail_simple_error": 0,  # 부적합(단순오류)
        "fail_recalculate": 0,   # 부적합(재계산)
        "fail_no_response": 0,   # 부적합(미회신)
        "excluded": 0,           # 대상제외
        "fail": 0,               # 레거시 부적합 (신규 기입 없음, 기존 데이터 집계용)
    }
    reviewer_filter = _my_assignment_filter(db, current_user)
    summary = (
        db.query(
            sa_func.count(Building.id).label("total"),
            sa_func.coalesce(sa_func.sum(Building.gross_area), 0).label("total_area"),
            sa_func.count(Building.id).filter(Building.gross_area >= 1000).label("area_over_1000"),
            sa_func.count(Building.id).filter(
                (Building.is_special_structure == True)
                | (Building.is_high_rise == True)
                | (Building.is_multi_use == True)
                | (Building.is_quasi_multi_use == True)
            ).label("high_risk"),
            sa_func.count(Building.id).filter(
                Building.current_phase.in_(list(RECEIVED_PHASES))
            ).label("need_review"),
        )
        .filter(reviewer_filter)
        .one()
    )
    total = int(summary.total or 0)
    total_area = float(summary.total_area or 0)
    area_over_1000 = int(summary.area_over_1000 or 0)
    high_risk = int(summary.high_risk or 0)
    need_review = int(summary.need_review or 0)

    # 검토서 제출 건수 — 본인 담당 건물들에서 report_submitted_at 있는 stage 수 (예비/보완 분리)
    submitted_preliminary = 0
    submitted_supplement = 0
    submitted_rows = (
        db.query(ReviewStage.phase, sa_func.count(ReviewStage.id))
        .join(Building, ReviewStage.building_id == Building.id)
        .filter(
            reviewer_filter,
            ReviewStage.report_submitted_at.isnot(None),
        )
        .group_by(ReviewStage.phase)
        .all()
    )
    for phase, count in submitted_rows:
        phase_key = phase.value if hasattr(phase, "value") else str(phase)
        if phase_key == "preliminary":
            submitted_preliminary += int(count or 0)
        elif phase_key.startswith("supplement_"):
            submitted_supplement += int(count or 0)
    submitted = submitted_preliminary + submitted_supplement

    # 접수 후 경과일수 버킷 — 현재 '_received' 단계의 doc_received_at 기준
    elapsed_buckets = {
        "1일": 0, "2일": 0, "3일": 0, "4일": 0, "5일": 0,
        "6일": 0, "7일": 0, "1주": 0, "2주이상": 0,
    }
    today = business_today()
    current_stage_match = or_(*[
        and_(Building.current_phase == received_phase, ReviewStage.phase == submit_phase)
        for received_phase, submit_phase in RECEIVED_TO_SUBMIT_PHASE.items()
    ])
    elapsed_rows = (
        db.query(ReviewStage.doc_received_at)
        .join(Building, ReviewStage.building_id == Building.id)
        .filter(
            reviewer_filter,
            Building.current_phase.in_(list(RECEIVED_PHASES)),
            current_stage_match,
            ReviewStage.doc_received_at.isnot(None),
        )
        .all()
    )
    _release_read_connection(db)
    for (doc_received_at,) in elapsed_rows:
        days = (today - doc_received_at).days
        if days < 1:
            elapsed_buckets["1일"] += 1  # 당일 접수는 1일로 합산
        elif 1 <= days <= 7:
            elapsed_buckets[f"{days}일"] += 1
        elif 8 <= days <= 13:
            elapsed_buckets["1주"] += 1
        else:  # 14+
            elapsed_buckets["2주이상"] += 1

    # 검토서 요청 예정일 기준 미제출 건 분류 (D-3 ~ 초과)
    schedule_counts = {
        "in_progress": 0,
        "d_minus_3": 0,
        "d_minus_2": 0,
        "d_minus_1": 0,
        "d_day": 0,
        "overdue": 0,
    }
    unsubmitted_rows = (
        db.query(ReviewStage.report_due_date)
        .join(Building, ReviewStage.building_id == Building.id)
        .filter(
            reviewer_filter,
            Building.current_phase.in_(list(RECEIVED_PHASES)),
            current_stage_match,
            ReviewStage.report_submitted_at.is_(None),
            ReviewStage.report_due_date.isnot(None),
        )
        .all()
    )
    _release_read_connection(db)
    for (report_due_date,) in unsubmitted_rows:
        schedule_counts["in_progress"] += 1
        delta = (report_due_date - today).days
        if delta == 3:
            schedule_counts["d_minus_3"] += 1
        elif delta == 2:
            schedule_counts["d_minus_2"] += 1
        elif delta == 1:
            schedule_counts["d_minus_1"] += 1
        elif delta == 0:
            schedule_counts["d_day"] += 1
        elif delta < 0:
            schedule_counts["overdue"] += 1

    # 최종 완료 건수 (5분류) — 본인 담당 기준
    # final_result 값은 향후 '최종 판정용 별도 엑셀 업로드'에서 기입됨
    final_rows = (
        db.query(Building.final_result, sa_func.count(Building.id))
        .filter(
            reviewer_filter,
            Building.final_result.isnot(None),
        )
        .group_by(Building.final_result)
        .all()
    )
    _release_read_connection(db)
    for final_result, count in final_rows:
        if final_result in final_counts:
            final_counts[final_result] = int(count or 0)

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
        "schedule_counts": schedule_counts,
        "final_counts": final_counts,
    }


@router.get("/my-reviews", response_model=BuildingListResponse)
def my_review_buildings(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    sort_by: str = Query("mgmt_no"),
    sort_order: str = Query("asc"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.REVIEWER, UserRole.SECRETARY, UserRole.CHIEF_SECRETARY)),
):
    """내가 배정된 검토 대상 건축물 목록 (검토위원/간사/총괄간사).

    검토위원은 `reviewer_id`만 사용한다. 총괄간사는 실무상 직접 검토자로
    배정될 수 있으므로 자기 이름 배정 건도 포함한다.
    """
    from models.review_stage import ReviewStage

    query = db.query(Building).filter(_my_assignment_filter(db, current_user))
    pending_due_subq = None
    if sort_by == "report_due_date":
        pending_due_subq = (
            db.query(
                ReviewStage.building_id.label("building_id"),
                func.max(ReviewStage.report_due_date).label("report_due_date"),
            )
            .filter(
                ReviewStage.report_submitted_at.is_(None),
                ReviewStage.report_due_date.isnot(None),
            )
            .group_by(ReviewStage.building_id)
            .subquery()
        )
        query = query.outerjoin(
            pending_due_subq,
            pending_due_subq.c.building_id == Building.id,
        )

    total = query.count()
    sort_desc = sort_order == "desc"
    address_cols = [
        Building.sido,
        Building.sigungu,
        Building.beopjeongdong,
        Building.main_lot_no,
        Building.sub_lot_no,
        Building.special_lot_no,
    ]
    sort_map = {
        "mgmt_no": [Building.mgmt_no],
        "address": address_cols,
        "gross_area": [Building.gross_area],
        "floors_above": [Building.floors_above],
        "current_phase": [Building.current_phase],
    }
    if pending_due_subq is not None:
        sort_map["report_due_date"] = [pending_due_subq.c.report_due_date]
    order_cols = sort_map.get(sort_by, [Building.mgmt_no])
    order_by = [
        (col.desc() if sort_desc else col.asc()).nulls_last()
        for col in order_cols
    ]
    order_by.append(Building.mgmt_no.asc())
    buildings = (
        query.options(
            load_only(
                Building.id,
                Building.mgmt_no,
                Building.building_name,
                Building.sido,
                Building.sigungu,
                Building.beopjeongdong,
                Building.main_lot_no,
                Building.sub_lot_no,
                Building.special_lot_no,
                Building.gross_area,
                Building.floors_above,
                Building.floors_below,
                Building.high_risk_type,
                Building.is_special_structure,
                Building.is_high_rise,
                Building.is_multi_use,
                Building.is_quasi_multi_use,
                Building.current_phase,
                Building.final_result,
                Building.reviewer_id,
                Building.assigned_reviewer_name,
            )
        )
        .order_by(*order_by)
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )

    # 각 건물별 최근 제출 stage (phase_order 최대, 제출일 존재) 조회
    building_ids = [b.id for b in buildings]
    latest_by_building: dict[int, ReviewStage] = {}
    # 접수 상태(미제출 + due_date 보유)에서 phase_order 최대 stage
    pending_by_building: dict[int, ReviewStage] = {}
    if building_ids:
        stages = (
            db.query(ReviewStage)
            .filter(
                ReviewStage.building_id.in_(building_ids),
                ReviewStage.result.isnot(None),
            )
            .order_by(ReviewStage.building_id, ReviewStage.phase_order.desc())
            .all()
        )
        for s in stages:
            if s.building_id not in latest_by_building:
                latest_by_building[s.building_id] = s

        pending_stages = (
            db.query(ReviewStage)
            .filter(
                ReviewStage.building_id.in_(building_ids),
                ReviewStage.report_submitted_at.is_(None),
                ReviewStage.report_due_date.isnot(None),
            )
            .order_by(ReviewStage.building_id, ReviewStage.phase_order.desc())
            .all()
        )
        for s in pending_stages:
            if s.building_id not in pending_by_building:
                pending_by_building[s.building_id] = s

    items = []
    for b in buildings:
        items.append(
            _to_my_review_response(
                b,
                reviewer_name=current_user.name,
                latest_stage=latest_by_building.get(b.id),
                pending_stage=pending_by_building.get(b.id),
            )
        )
    return BuildingListResponse(items=items, total=total)


@router.get("/{building_id}", response_model=BuildingResponse)
def get_building(
    building_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """건축물 상세 조회.

    가시성 정책:
    - REVIEWER: 본인 reviewer_id 매칭 건물만
    - SECRETARY(조 배정): 같은 조 검토위원이 담당하는 건물만
    - 팀장/총괄간사/조 미배정 간사: 전체
    가시성 위반 시 존재 자체를 노출하지 않기 위해 404 반환.
    """
    building = (
        db.query(Building)
        .options(selectinload(Building.reviewer).selectinload(Reviewer.user))
        .filter(Building.id == building_id)
        .first()
    )
    if not building:
        raise HTTPException(status_code=404, detail="건축물을 찾을 수 없습니다")

    if not is_building_visible_to(current_user, building, db):
        raise HTTPException(status_code=404, detail="건축물을 찾을 수 없습니다")

    registered_names = _get_registered_names(db)
    return _to_response(building, registered_names)


@router.get("/{building_id}/summary", response_model=BuildingSummaryResponse)
def get_building_summary(
    building_id: int,
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
    """통계자료 팝업용 건축물 요약 (건물 정보 + 조 검토위원 명단 + 단계 이력).

    통계자료 화면은 조 구분 없이 전체를 열람하므로 간사도 조 제한 없이 조회한다.
    """
    from models.review_stage import ReviewStage

    building = (
        db.query(Building)
        .options(selectinload(Building.reviewer).selectinload(Reviewer.user))
        .filter(Building.id == building_id)
        .first()
    )
    if not building:
        raise HTTPException(status_code=404, detail="건축물을 찾을 수 없습니다")

    registered_names = _get_registered_names(db)
    building_data = _to_response(building, registered_names)

    group_no = building.reviewer.group_no if building.reviewer else None
    reviewer_name = building_data.get("reviewer_name")

    group_reviewers: list[GroupReviewerSummary] = []
    if group_no is not None:
        rows = (
            db.query(
                Reviewer.id,
                Reviewer.user_id,
                User.name,
                Reviewer.specialty,
                User.phone,
                func.count(Building.id).label("assigned_count"),
            )
            .join(User, Reviewer.user_id == User.id)
            .outerjoin(Building, Building.reviewer_id == Reviewer.id)
            .filter(Reviewer.group_no == group_no)
            .group_by(Reviewer.id, Reviewer.user_id, User.name, Reviewer.specialty, User.phone)
            .order_by(User.name)
            .all()
        )
        group_reviewers = [
            GroupReviewerSummary(
                reviewer_id=row.id,
                user_id=row.user_id,
                name=row.name,
                specialty=row.specialty,
                phone=row.phone,
                is_assigned=row.id == building.reviewer_id,
                assigned_count=int(row.assigned_count or 0),
            )
            for row in rows
        ]

    stages = (
        db.query(ReviewStage)
        .filter(ReviewStage.building_id == building_id)
        .order_by(ReviewStage.phase_order)
        .all()
    )
    stage_items = [
        BuildingStageSummary(
            id=stage.id,
            phase=_stage_phase_value(stage),
            phase_order=stage.phase_order,
            doc_received_at=stage.doc_received_at,
            doc_distributed_at=stage.doc_distributed_at,
            report_submitted_at=stage.report_submitted_at,
            reviewer_name=stage.reviewer_name,
            result=stage.result.value if stage.result else None,
            severity_l0_count=stage.severity_l0_count,
            severity_l1_count=stage.severity_l1_count,
            severity_l2_count=stage.severity_l2_count,
            severity_l3_count=stage.severity_l3_count,
            severity_l4_count=stage.severity_l4_count,
            inappropriate_review_needed=bool(stage.inappropriate_review_needed),
            inappropriate_decision=(
                stage.inappropriate_decision.value
                if stage.inappropriate_decision
                else None
            ),
        )
        for stage in stages
    ]

    return BuildingSummaryResponse(
        building=BuildingResponse(**building_data),
        group_no=group_no,
        reviewer_name=reviewer_name,
        group_reviewers=group_reviewers,
        stages=stage_items,
    )


@router.patch("/{building_id}", response_model=BuildingResponse)
def update_building(
    building_id: int,
    body: BuildingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY, UserRole.SECRETARY)
    ),
):
    """건축물 정보 수정 (current_phase 제외 — 별도 엔드포인트 사용)"""
    building = db.query(Building).filter(Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="건축물을 찾을 수 없습니다")
    if current_user.role == UserRole.SECRETARY and not is_building_visible_to(
        current_user, building, db
    ):
        raise HTTPException(status_code=404, detail="건축물을 찾을 수 없습니다")

    update_data = body.model_dump(exclude_unset=True)
    reviewer_id_provided = "reviewer_id" in update_data
    new_reviewer: Reviewer | None = None
    if reviewer_id_provided:
        new_reviewer_id = update_data.pop("reviewer_id")
        if new_reviewer_id is None:
            building.reviewer_id = None
            building.assigned_reviewer_name = None
        else:
            new_reviewer = _validate_assignable_reviewer(
                new_reviewer_id,
                current_user,
                db,
            )
            building.reviewer_id = new_reviewer.id
            building.assigned_reviewer_name = new_reviewer.user.name

    for key, value in update_data.items():
        setattr(building, key, value)

    if reviewer_id_provided and not building.current_phase and building.reviewer_id:
        from services.phase_transition import transition_phase

        transition_phase(
            db,
            building,
            to_phase="assigned",
            trigger="initial",
            actor_user_id=current_user.id,
        )

    if reviewer_id_provided:
        clear_stats_cache()
        log_action(
            db,
            current_user.id,
            "change_reviewer",
            "building",
            building.id,
            after_data={
                "mgmt_no": building.mgmt_no,
                "reviewer_id": building.reviewer_id,
                "reviewer_name": new_reviewer.user.name if new_reviewer else None,
            },
        )

    db.commit()
    db.refresh(building)
    registered_names = _get_registered_names(db)
    return _to_response(building, registered_names)


class PhaseChangeRequest(BaseModel):
    to_phase: str
    reason: str | None = None  # 운영 사유(권장)


class BulkFinalizePassRequest(BaseModel):
    building_ids: list[int]


class BulkFinalizePassItem(BaseModel):
    id: int
    mgmt_no: str | None = None
    status: str
    final_result: str | None = None
    detail: str | None = None


class BulkFinalizePassResponse(BaseModel):
    applied: int
    skipped: int
    items: list[BulkFinalizePassItem]


@router.post("/finalize-pass/bulk", response_model=BulkFinalizePassResponse)
def bulk_finalize_pass_buildings(
    body: BulkFinalizePassRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.CHIEF_SECRETARY)),
):
    """최근 판정이 적합인 선택 건을 총괄간사가 일괄 최종완료 처리한다."""
    from models.phase_transition_log import PhaseTransitionLog
    from models.review_stage import PhaseType, ResultType, ReviewStage

    seen: set[int] = set()
    building_ids = []
    for building_id in body.building_ids:
        if building_id in seen:
            continue
        seen.add(building_id)
        building_ids.append(building_id)

    if not building_ids:
        raise HTTPException(status_code=400, detail="처리할 건축물을 선택해 주세요")
    if len(building_ids) > 500:
        raise HTTPException(status_code=400, detail="한 번에 500건까지만 처리할 수 있습니다")

    ip = request.client.host if request.client and request.client.host else None
    items: list[BulkFinalizePassItem] = []
    applied = 0

    for building_id in building_ids:
        building = db.query(Building).filter(Building.id == building_id).first()
        if not building:
            items.append(BulkFinalizePassItem(
                id=building_id,
                status="skipped",
                detail="건축물을 찾을 수 없습니다",
            ))
            continue

        if building.final_result or building.current_phase == "completed":
            items.append(BulkFinalizePassItem(
                id=building.id,
                mgmt_no=building.mgmt_no,
                status="skipped",
                detail="이미 최종완료 처리된 건입니다",
            ))
            continue

        latest_stage = (
            db.query(ReviewStage)
            .filter(
                ReviewStage.building_id == building.id,
                ReviewStage.result.isnot(None),
            )
            .order_by(ReviewStage.phase_order.desc())
            .first()
        )
        if latest_stage is None:
            items.append(BulkFinalizePassItem(
                id=building.id,
                mgmt_no=building.mgmt_no,
                status="skipped",
                detail="판정된 검토 단계가 없습니다",
            ))
            continue
        if latest_stage.result != ResultType.PASS:
            items.append(BulkFinalizePassItem(
                id=building.id,
                mgmt_no=building.mgmt_no,
                status="skipped",
                detail="최근 판정이 적합이 아닙니다",
            ))
            continue

        final_result = (
            "pass"
            if latest_stage.phase == PhaseType.PRELIMINARY
            else "pass_supplement"
        )
        previous_phase = building.current_phase
        building.final_result = final_result
        building.current_phase = "completed"
        db.add(PhaseTransitionLog(
            building_id=building.id,
            mgmt_no=building.mgmt_no,
            from_phase=previous_phase,
            to_phase="completed",
            trigger="manual",
            actor_user_id=current_user.id,
            ip_address=ip,
            reason=f"bulk_finalize_pass:{final_result}",
        ))
        log_action(
            db,
            current_user.id,
            "bulk_finalize_pass",
            "building",
            building.id,
            after_data={
                "mgmt_no": building.mgmt_no,
                "latest_phase": latest_stage.phase.value,
                "final_result": final_result,
            },
        )
        applied += 1
        items.append(BulkFinalizePassItem(
            id=building.id,
            mgmt_no=building.mgmt_no,
            status="applied",
            final_result=final_result,
        ))

    if applied:
        clear_stats_cache()
    db.commit()
    return BulkFinalizePassResponse(
        applied=applied,
        skipped=len(items) - applied,
        items=items,
    )


@router.post("/{building_id}/phase", response_model=BuildingResponse)
def change_building_phase(
    building_id: int,
    body: PhaseChangeRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """간사 수동 단계 변경 (MANUAL 트리거).

    현재 단계 기준 전후 1단계만 허용. 임의 점프 시 400.
    모든 변경은 phase_transition_logs 에 영구 기록.
    """
    from services.phase_transition import (
        InvalidPhaseTransition,
        transition_phase,
    )

    building = db.query(Building).filter(Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="건축물을 찾을 수 없습니다")

    ip = None
    if request.client and request.client.host:
        ip = request.client.host

    try:
        log = transition_phase(
            db, building, to_phase=body.to_phase.strip(), trigger="manual",
            actor_user_id=current_user.id, ip_address=ip,
            reason=body.reason or "manual_change",
        )
    except InvalidPhaseTransition as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    db.commit()
    db.refresh(building)
    if log is None:
        # from == to 인 경우 — 사용자에게 알리되 200으로 반환 (멱등 처리)
        pass
    registered_names = _get_registered_names(db)
    return _to_response(building, registered_names)


@router.post("/{building_id}/finalize-pass", response_model=BuildingResponse)
def finalize_pass_building(
    building_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.CHIEF_SECRETARY)),
):
    """최신 판정이 적합인 건을 총괄간사가 수동으로 최종 완료 처리한다."""
    from models.phase_transition_log import PhaseTransitionLog
    from models.review_stage import PhaseType, ResultType, ReviewStage

    building = db.query(Building).filter(Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="건축물을 찾을 수 없습니다")

    latest_stage = (
        db.query(ReviewStage)
        .filter(
            ReviewStage.building_id == building.id,
            ReviewStage.result.isnot(None),
        )
        .order_by(ReviewStage.phase_order.desc())
        .first()
    )
    if latest_stage is None:
        raise HTTPException(status_code=400, detail="판정된 검토 단계가 없습니다")
    if latest_stage.result != ResultType.PASS:
        raise HTTPException(status_code=400, detail="최근 판정이 적합인 경우만 최종완료 처리할 수 있습니다")

    final_result = (
        "pass"
        if latest_stage.phase == PhaseType.PRELIMINARY
        else "pass_supplement"
    )
    previous_phase = building.current_phase
    building.final_result = final_result
    building.current_phase = "completed"

    ip = request.client.host if request.client and request.client.host else None
    db.add(PhaseTransitionLog(
        building_id=building.id,
        mgmt_no=building.mgmt_no,
        from_phase=previous_phase,
        to_phase="completed",
        trigger="manual",
        actor_user_id=current_user.id,
        ip_address=ip,
        reason=f"finalize_pass:{final_result}",
    ))
    log_action(
        db,
        current_user.id,
        "finalize_pass",
        "building",
        building.id,
        after_data={
            "mgmt_no": building.mgmt_no,
            "latest_phase": latest_stage.phase.value,
            "final_result": final_result,
        },
    )
    clear_stats_cache()
    db.commit()
    db.refresh(building)
    registered_names = _get_registered_names(db)
    return _to_response(building, registered_names)


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
