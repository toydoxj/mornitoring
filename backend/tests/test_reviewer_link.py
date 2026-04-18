"""services.reviewer_link.ensure_reviewer_link 회귀 테스트.

신규 사용자가 등록될 때 Reviewer 행 자동 생성 + assigned_reviewer_name 이 일치하는
건물의 reviewer_id 백필이 자동 수행되는지 확인한다. 동명이인 방지도 검증.
"""

from models.building import Building
from models.reviewer import Reviewer
from models.user import UserRole
from services.reviewer_link import ensure_reviewer_link


def test_auto_links_buildings_when_unique_name(db_session, make_user):
    """신규 user + 같은 이름으로 배정된 건물 → 자동 연결됨."""
    # 이름 기반으로만 배정된 미연결 건물 두 건
    for mgmt in ("LINK-001", "LINK-002"):
        db_session.add(Building(
            mgmt_no=mgmt,
            assigned_reviewer_name="이공우",
            reviewer_id=None,
        ))
    # 다른 사람에게 배정된 건물은 건드리지 않아야 함
    db_session.add(Building(
        mgmt_no="OTHER-001",
        assigned_reviewer_name="김철수",
        reviewer_id=None,
    ))
    db_session.commit()

    user, _ = make_user(UserRole.REVIEWER, name="이공우")

    result = ensure_reviewer_link(db_session, user)
    db_session.commit()

    assert result.reviewer_created is True
    assert result.skipped_reason is None
    assert result.buildings_linked == 2

    linked = {
        b.mgmt_no: b.reviewer_id
        for b in db_session.query(Building).all()
    }
    assert linked["LINK-001"] == result.reviewer_id
    assert linked["LINK-002"] == result.reviewer_id
    assert linked["OTHER-001"] is None


def test_skips_linking_when_duplicate_active_user(db_session, make_user):
    """동명이인이 활성으로 존재하면 Reviewer 행만 생성되고 building 연결은 스킵."""
    # 기존 활성 "이공우"
    make_user(UserRole.REVIEWER, name="이공우")

    db_session.add(Building(
        mgmt_no="DUP-001",
        assigned_reviewer_name="이공우",
        reviewer_id=None,
    ))
    db_session.commit()

    # 같은 이름의 신규 "이공우" 등록
    new_user, _ = make_user(UserRole.REVIEWER, name="이공우")

    result = ensure_reviewer_link(db_session, new_user)
    db_session.commit()

    assert result.reviewer_created is True
    assert result.reviewer_id is not None
    assert result.buildings_linked == 0
    assert result.skipped_reason == "duplicate name"

    b = db_session.query(Building).filter(Building.mgmt_no == "DUP-001").first()
    assert b.reviewer_id is None


def test_does_not_duplicate_existing_reviewer(db_session, make_user):
    """이미 Reviewer 행이 있는 user는 중복 생성하지 않고 연결만 수행."""
    user, _ = make_user(UserRole.REVIEWER, name="이공우")
    existing = Reviewer(user_id=user.id, group_no="A")
    db_session.add(existing)
    db_session.add(Building(
        mgmt_no="EXIST-001",
        assigned_reviewer_name="이공우",
        reviewer_id=None,
    ))
    db_session.commit()

    result = ensure_reviewer_link(db_session, user)
    db_session.commit()

    assert result.reviewer_created is False
    assert result.reviewer_id == existing.id
    assert result.buildings_linked == 1

    total_reviewers = db_session.query(Reviewer).filter(Reviewer.user_id == user.id).count()
    assert total_reviewers == 1

    b = db_session.query(Building).filter(Building.mgmt_no == "EXIST-001").first()
    assert b.reviewer_id == existing.id
