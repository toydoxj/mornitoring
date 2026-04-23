"""간사 조 단위 데이터 가시성 회귀 테스트.

운영 정책:
- TEAM_LEADER / CHIEF_SECRETARY: 전체
- SECRETARY + group_no 있음: 같은 조 검토위원 담당 건물만
- SECRETARY + group_no 없음(미배정): 전체 (운영 안전성 우선)
- REVIEWER: 본인 reviewer_id (기존 정책 유지)
"""

from models.inquiry import Inquiry, InquiryStatus
from models.review_stage import InappropriateDecision, PhaseType, ReviewStage
from models.user import UserRole


def _make_two_groups(make_user, make_reviewer, make_building, db_session):
    """두 조 + 각 조 검토위원 + 각 조 건물 1개씩."""
    rev1_user, rev1, _ = make_reviewer()
    rev1.group_no = 1
    rev2_user, rev2, _ = make_reviewer()
    rev2.group_no = 2
    db_session.commit()

    b1 = make_building(mgmt_no="VIS-G1", reviewer_id=rev1.id)
    b2 = make_building(mgmt_no="VIS-G2", reviewer_id=rev2.id)
    return rev1_user, rev1, b1, rev2_user, rev2, b2


# ===== 통합관리대장 (/api/buildings) =====

def test_secretary_in_group1_sees_only_group1_buildings(
    client, db_session, make_user, make_reviewer, make_building
):
    sec, sec_h = make_user(UserRole.SECRETARY)
    sec.group_no = 1
    db_session.commit()
    _make_two_groups(make_user, make_reviewer, make_building, db_session)

    res = client.get("/api/buildings", headers=sec_h)
    assert res.status_code == 200
    mgmt_nos = [b["mgmt_no"] for b in res.json()["items"]]
    assert "VIS-G1" in mgmt_nos
    assert "VIS-G2" not in mgmt_nos


def test_secretary_without_group_sees_all_buildings(
    client, db_session, make_user, make_reviewer, make_building
):
    sec, sec_h = make_user(UserRole.SECRETARY)
    sec.group_no = None
    db_session.commit()
    _make_two_groups(make_user, make_reviewer, make_building, db_session)

    res = client.get("/api/buildings", headers=sec_h)
    assert res.status_code == 200
    mgmt_nos = [b["mgmt_no"] for b in res.json()["items"]]
    assert {"VIS-G1", "VIS-G2"}.issubset(set(mgmt_nos))


def test_chief_secretary_sees_all_buildings(
    client, db_session, make_user, make_reviewer, make_building
):
    _, h = make_user(UserRole.CHIEF_SECRETARY)
    _make_two_groups(make_user, make_reviewer, make_building, db_session)

    res = client.get("/api/buildings", headers=h)
    assert res.status_code == 200
    mgmt_nos = [b["mgmt_no"] for b in res.json()["items"]]
    assert {"VIS-G1", "VIS-G2"}.issubset(set(mgmt_nos))


def test_secretary_other_group_building_get_returns_404(
    client, db_session, make_user, make_reviewer, make_building
):
    sec, sec_h = make_user(UserRole.SECRETARY)
    sec.group_no = 1
    db_session.commit()
    _, _, b1, _, _, b2 = _make_two_groups(
        make_user, make_reviewer, make_building, db_session
    )

    assert client.get(f"/api/buildings/{b1.id}", headers=sec_h).status_code == 200
    assert client.get(f"/api/buildings/{b2.id}", headers=sec_h).status_code == 404


# ===== 문의사항 (/api/reviews/inquiries) =====

def test_secretary_inquiry_list_filters_by_group(
    client, db_session, make_user, make_reviewer, make_building
):
    sec, sec_h = make_user(UserRole.SECRETARY)
    sec.group_no = 1
    db_session.commit()
    _, _, b1, _, _, b2 = _make_two_groups(
        make_user, make_reviewer, make_building, db_session
    )

    db_session.add(Inquiry(
        building_id=b1.id, mgmt_no=b1.mgmt_no, phase="preliminary",
        submitter_id=sec.id, submitter_name=sec.name, content="g1 inquiry",
        status=InquiryStatus.OPEN,
    ))
    db_session.add(Inquiry(
        building_id=b2.id, mgmt_no=b2.mgmt_no, phase="preliminary",
        submitter_id=sec.id, submitter_name=sec.name, content="g2 inquiry",
        status=InquiryStatus.OPEN,
    ))
    db_session.commit()

    res = client.get("/api/reviews/inquiries", headers=sec_h)
    assert res.status_code == 200
    contents = [i["content"] for i in res.json()["items"]]
    assert "g1 inquiry" in contents
    assert "g2 inquiry" not in contents


# ===== 대시보드 통계 (/api/buildings/stats) =====

def test_secretary_stats_total_excludes_other_group(
    client, db_session, make_user, make_reviewer, make_building
):
    sec, sec_h = make_user(UserRole.SECRETARY)
    sec.group_no = 1
    db_session.commit()
    _make_two_groups(make_user, make_reviewer, make_building, db_session)

    res = client.get("/api/buildings/stats", headers=sec_h)
    assert res.status_code == 200
    body = res.json()
    # 같은 조 1건만 노출되어야 한다.
    assert body["total"] == 1


# ===== 부적합 검토 (/api/reviews/inappropriate) =====

def test_secretary_inappropriate_filters_by_group(
    client, db_session, make_user, make_reviewer, make_building
):
    sec, sec_h = make_user(UserRole.SECRETARY)
    sec.group_no = 1
    db_session.commit()
    _, rev1, b1, _, rev2, b2 = _make_two_groups(
        make_user, make_reviewer, make_building, db_session
    )

    for b in (b1, b2):
        db_session.add(ReviewStage(
            building_id=b.id, phase=PhaseType.PRELIMINARY, phase_order=0,
            inappropriate_review_needed=True,
            inappropriate_decision=InappropriateDecision.PENDING,
        ))
    db_session.commit()

    res = client.get("/api/reviews/inappropriate", headers=sec_h)
    assert res.status_code == 200
    mgmts = {item["mgmt_no"] for item in res.json()["items"]}
    assert b1.mgmt_no in mgmts
    assert b2.mgmt_no not in mgmts


# ===== reviewer-names enumeration 차단 =====

def test_secretary_reviewer_names_filtered_by_group(
    client, db_session, make_user, make_reviewer, make_building
):
    sec, sec_h = make_user(UserRole.SECRETARY)
    sec.group_no = 1
    db_session.commit()
    _, rev1, b1, _, rev2, b2 = _make_two_groups(
        make_user, make_reviewer, make_building, db_session
    )
    b1.assigned_reviewer_name = "조1위원"
    b2.assigned_reviewer_name = "조2위원"
    db_session.commit()

    res = client.get("/api/buildings/reviewer-names", headers=sec_h)
    assert res.status_code == 200
    names = res.json()
    assert "조1위원" in names
    assert "조2위원" not in names
