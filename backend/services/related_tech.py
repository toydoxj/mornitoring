"""관계기술자 협력 대상/여부 판정 유틸리티."""

from sqlalchemy import and_, func, or_

from models.building import Building

_MISSING_NAME_MARKERS = ("", "-")


def related_tech_target_filter():
    """관계기술자 협력 대상 건축물 SQL 필터."""
    return or_(
        Building.floors_above >= 6,
        Building.is_special_structure.is_(True),
        Building.is_multi_use.is_(True),
        Building.is_quasi_multi_use.is_(True),
        and_(
            Building.floors_above >= 3,
            Building.detail_category9.ilike("%필로티%"),
        ),
    )


def related_tech_coop_filter():
    """관계기술자 성명이 입력된 건축물 SQL 필터."""
    normalized_name = func.trim(func.coalesce(Building.struct_eng_name, ""))
    return normalized_name.notin_(_MISSING_NAME_MARKERS)


def is_related_tech_target(building: Building) -> bool:
    """단일 건축물이 관계기술자 협력 대상인지 판정."""
    floors_above = building.floors_above or 0
    detail_category9 = building.detail_category9 or ""
    return (
        floors_above >= 6
        or building.is_special_structure is True
        or building.is_multi_use is True
        or building.is_quasi_multi_use is True
        or (floors_above >= 3 and "필로티" in detail_category9)
    )


def has_related_tech_cooperation(building: Building) -> bool:
    """관계기술자 성명이 실제로 입력됐는지 판정."""
    name = (building.struct_eng_name or "").strip()
    return name not in _MISSING_NAME_MARKERS
