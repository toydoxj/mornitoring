"""사용자 역할/조 기반 데이터 가시성 헬퍼.

운영 정책:
- 팀장/총괄간사/관리원: 모든 데이터 (필터 미적용)
- 간사 + group_no 있음: 같은 조 검토위원이 담당하는 건물/관련 데이터만
- 간사 + group_no 없음(미배정): 모든 데이터 (운영 안전성 우선 — 사용자 결정)
- 검토위원: 본인 reviewer_id 매칭만 (별도 헬퍼/엔드포인트에서 처리)

각 헬퍼는 SQLAlchemy 쿼리에 합칠 수 있는 필터(`ColumnElement[bool]` | None)를
반환하거나, IN 비교용 subquery 를 반환한다. None 은 "필터 불필요(전체 노출)".
"""

from __future__ import annotations

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from models.building import Building
from models.reviewer import Reviewer
from models.user import User, UserRole


SECRETARY_HIDDEN_REVIEWER_NAMES = frozenset({"조미정"})


def _hidden_reviewer_user_filter() -> ColumnElement[bool]:
    """조별간사 화면/대상 목록에서 숨길 사용자 필터."""
    return User.name.not_in(SECRETARY_HIDDEN_REVIEWER_NAMES)


def _secretary_building_exclusion_filter() -> ColumnElement[bool]:
    """조별간사에게 노출하지 않을 검토위원 배정 건물을 제외한다."""
    hidden_reviewer_ids = (
        select(Reviewer.id)
        .join(User, Reviewer.user_id == User.id)
        .where(User.name.in_(SECRETARY_HIDDEN_REVIEWER_NAMES))
    )
    return and_(
        or_(
            Building.reviewer_id.is_(None),
            Building.reviewer_id.not_in(hidden_reviewer_ids),
        ),
        or_(
            Building.assigned_reviewer_name.is_(None),
            Building.assigned_reviewer_name.not_in(SECRETARY_HIDDEN_REVIEWER_NAMES),
        ),
    )


def _reviewer_is_hidden_from_secretary(reviewer: Reviewer | None) -> bool:
    return bool(
        reviewer
        and reviewer.user
        and reviewer.user.name in SECRETARY_HIDDEN_REVIEWER_NAMES
    )


def _is_unrestricted(user: User) -> bool:
    """전체 노출 권한이 있는 사용자 여부.

    - 팀장/총괄간사/관리원: 항상 전체
    - 간사 + group_no NULL: 운영진/총괄급 가정 → 전체
    """
    if user.role in (
        UserRole.TEAM_LEADER,
        UserRole.CHIEF_SECRETARY,
        UserRole.MANAGER,
    ):
        return True
    if user.role == UserRole.SECRETARY and user.group_no is None:
        return True
    return False


def building_visibility_filter(user: User) -> ColumnElement[bool] | None:
    """`Building` 쿼리에 합칠 가시성 필터.

    리턴값이 None 이면 호출자는 필터를 건너뛴다. 그 외엔
    `query.filter(building_visibility_filter(user))` 식으로 사용.
    """
    if user.role == UserRole.SECRETARY:
        exclusion = _secretary_building_exclusion_filter()
        if user.group_no is None:
            return exclusion
        # 같은 조 검토위원이 담당하는 건물 (Reviewer.group_no 기준).
        same_group_reviewer_ids = (
            select(Reviewer.id).where(Reviewer.group_no == user.group_no)
        )
        return and_(Building.reviewer_id.in_(same_group_reviewer_ids), exclusion)
    if _is_unrestricted(user):
        return None
    if user.role == UserRole.REVIEWER:
        # 검토위원은 본인 reviewer 행 매칭. Reviewer 행 미존재 사용자는 빈 결과.
        own_reviewer_id = (
            select(Reviewer.id).where(Reviewer.user_id == user.id)
        )
        return Building.reviewer_id.in_(own_reviewer_id)
    # 미정의 역할은 보수적으로 빈 결과.
    return Building.id.is_(None)


def is_building_visible_to(user: User, building: Building, db: Session) -> bool:
    """단건 가시성 검사 (404 매핑용)."""
    if user.role == UserRole.SECRETARY:
        if building.assigned_reviewer_name in SECRETARY_HIDDEN_REVIEWER_NAMES:
            return False
        reviewer = (
            db.query(Reviewer).filter(Reviewer.id == building.reviewer_id).first()
            if building.reviewer_id is not None else None
        )
        if _reviewer_is_hidden_from_secretary(reviewer):
            return False
        if user.group_no is None:
            return True
        if reviewer is None:
            return False
        return bool(reviewer and reviewer.group_no == user.group_no)
    if _is_unrestricted(user):
        return True
    if user.role == UserRole.REVIEWER:
        reviewer = (
            db.query(Reviewer).filter(Reviewer.user_id == user.id).first()
        )
        return bool(reviewer and building.reviewer_id == reviewer.id)
    return False


def visible_building_ids_subquery(user: User):
    """`Building.id` 의 가시 셋을 SELECT 서브쿼리로. 전체 노출 시 None.

    `query.filter(SomeModel.building_id.in_(visible_building_ids_subquery(user)))`
    형태로 ReviewStage/Inquiry/NotificationLog 등에 합치는 데 사용.
    """
    visibility = building_visibility_filter(user)
    if visibility is None:
        return None
    return select(Building.id).where(visibility)


def secretary_hidden_user_ids_subquery(user: User):
    """조별간사에게 사용자명 자체를 숨겨야 하는 user_id 셋."""
    if user.role != UserRole.SECRETARY:
        return None
    return select(User.id).where(User.name.in_(SECRETARY_HIDDEN_REVIEWER_NAMES))


def visible_reviewer_user_ids(user: User) -> ColumnElement[bool] | None:
    """`User` 쿼리(검토위원 대상 알림/리마인드 등)에 합칠 가시성 필터.

    리턴 None = 전체. 간사는 같은 조 검토위원의 user_id 만 노출.
    """
    if user.role == UserRole.SECRETARY:
        visible_user_filter = _hidden_reviewer_user_filter()
        if user.group_no is None:
            return visible_user_filter
        # 같은 조 검토위원의 user_id
        same_group_user_ids = (
            select(Reviewer.user_id).where(Reviewer.group_no == user.group_no)
        )
        return and_(User.id.in_(same_group_user_ids), visible_user_filter)
    if _is_unrestricted(user):
        return None
    if user.role == UserRole.REVIEWER:
        # 검토위원은 본인만
        return User.id == user.id
    return User.id.is_(None)
