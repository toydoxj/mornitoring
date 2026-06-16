"""간사 조 단위 데이터 가시성 회귀 테스트.

운영 정책:
- TEAM_LEADER / CHIEF_SECRETARY: 전체
- SECRETARY + group_no 있음: 같은 조 검토위원 담당 건물만
- SECRETARY + group_no 없음(미배정): 전체 (운영 안전성 우선)
- REVIEWER: 본인 reviewer_id (기존 정책 유지)
"""

from models.inquiry import Inquiry, InquiryStatus
from models.review_opinion_detail import ReviewOpinionDetail
from models.review_severity_summary import ReviewSeveritySummary
from models.review_stage import InappropriateDecision, PhaseType, ResultType, ReviewStage
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
    _, _, b1, _, _, b2 = _make_two_groups(
        make_user, make_reviewer, make_building, db_session
    )
    b1.sido = "서울특별시"
    b1.sigungu = "강남구"
    b1.gross_area = 100
    b2.sido = "부산광역시"
    b2.sigungu = "해운대구"
    b2.gross_area = 5000
    db_session.commit()

    res = client.get("/api/buildings/stats", headers=sec_h)
    assert res.status_code == 200
    body = res.json()
    # 같은 조 1건만 노출되어야 한다.
    assert body["total"] == 1
    area_total = body["regional_stats"]["area"][0]
    assert area_total["area_0_300"] == 1
    assert area_total["area_5000_over"] == 0
    area_regions = [row["region"] for row in body["regional_stats"]["area"]]
    assert "서울특별시" in area_regions
    assert "부산광역시" not in area_regions


def test_stats_returns_regional_building_stats_with_total_row(
    client, db_session, make_user, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    b1 = make_building(mgmt_no="REG-STATS-001")
    b1.sido = "서울특별시"
    b1.sigungu = "강남구"
    b1.gross_area = 299
    b1.floors_above = 5
    b1.is_special_structure = True
    b1.struct_eng_name = "홍길동"

    b2 = make_building(mgmt_no="REG-STATS-002")
    b2.sido = "서울특별시"
    b2.sigungu = "강남구"
    b2.gross_area = 300
    b2.floors_above = 6
    b2.is_multi_use = True

    b3 = make_building(mgmt_no="REG-STATS-003")
    b3.sido = "부산광역시"
    b3.sigungu = "해운대구"
    b3.gross_area = 5000
    b3.floors_above = 16
    b3.is_high_rise = True
    b3.is_quasi_multi_use = True
    b3.struct_eng_firm = "협력사"

    b4 = make_building(mgmt_no="REG-STATS-004")
    b4.gross_area = 800
    b4.floors_above = 3
    b4.detail_category9 = "필로티"
    db_session.commit()

    res = client.get("/api/buildings/stats", headers=headers)
    assert res.status_code == 200
    regional_stats = res.json()["regional_stats"]

    area_total = regional_stats["area"][0]
    assert area_total["region"] == "전체"
    assert area_total["area_0_300"] == 1
    assert area_total["area_300_600"] == 1
    assert area_total["area_600_1000"] == 1
    assert area_total["area_1000_5000"] == 0
    assert area_total["area_5000_over"] == 1

    floor_total = regional_stats["floors"][0]
    assert floor_total["floors_under_6"] == 2
    assert floor_total["floors_6_under_16"] == 1
    assert floor_total["floors_16_over"] == 1

    risk_total = regional_stats["risk"][0]
    assert risk_total["special"] == 1
    assert risk_total["multi_use"] == 1
    assert risk_total["high_rise"] == 1
    assert risk_total["quasi_multi_use"] == 1
    assert risk_total["related_tech_coop_target"] == 4
    assert risk_total["related_tech_coop"] == 1

    seoul = next(row for row in regional_stats["risk"] if row["region"] == "서울특별시")
    assert seoul["related_tech_coop_target"] == 2
    assert seoul["related_tech_coop"] == 1

    risk_regions = [row["region"] for row in regional_stats["risk"]]
    assert risk_regions[:3] == ["전체", "서울특별시", "부산광역시"]


def test_stats_returns_severity_summary_by_category_and_phase(
    client, db_session, make_user, make_reviewer, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    _, reviewer, _ = make_reviewer()
    building = make_building(reviewer_id=reviewer.id, mgmt_no="SEV-STATS-001")

    stage = ReviewStage(
        building_id=building.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
    )
    pass_stage = ReviewStage(
        building_id=building.id,
        phase=PhaseType.SUPPLEMENT_1,
        phase_order=1,
        result=ResultType.PASS,
    )
    db_session.add_all([stage, pass_stage])
    db_session.commit()
    db_session.refresh(stage)
    db_session.add_all([
        ReviewSeveritySummary(
            stage_id=stage.id,
            category="부재설계의 적정성 - 구조설계 요소",
            severity="L3",
            count=2,
        ),
        ReviewSeveritySummary(
            stage_id=stage.id,
            category="기타의견",
            severity="L0",
            count=1,
        ),
    ])
    db_session.commit()

    res = client.get("/api/buildings/stats", headers=headers)
    assert res.status_code == 200
    severity_stats = res.json()["severity_stats"]

    assert severity_stats["total"] == 3
    assert severity_stats["totals"]["L0"] == 1
    assert severity_stats["totals"]["L3"] == 2
    assert {
        (row["category"], row["counts"]["L3"], row["total"])
        for row in severity_stats["by_category"]
    } == {
        ("부재설계의 적정성 - 구조설계 요소", 2, 2),
        ("기타의견", 0, 1),
    }
    assert severity_stats["by_phase"] == [{
        "phase": "preliminary",
        "counts": {"L0": 1, "L1": 0, "L2": 0, "L3": 2, "L4": 0},
        "total": 3,
    }]
    assert severity_stats["by_report_max"] == {
        "total": 2,
        "totals": {"pass": 1, "L0": 0, "L1": 0, "L2": 0, "L3": 1, "L4": 0},
        "by_phase": [
            {
                "phase": "preliminary",
                "counts": {"pass": 0, "L0": 0, "L1": 0, "L2": 0, "L3": 1, "L4": 0},
                "total": 1,
            },
            {
                "phase": "supplement_1",
                "counts": {"pass": 1, "L0": 0, "L1": 0, "L2": 0, "L3": 0, "L4": 0},
                "total": 1,
            },
        ],
    }


def test_stats_returns_keyword_summary_from_opinion_details(
    client, db_session, make_user, make_reviewer, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    _, reviewer, _ = make_reviewer()
    building = make_building(reviewer_id=reviewer.id, mgmt_no="KEY-STATS-001")

    preliminary = ReviewStage(
        building_id=building.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
    )
    supplement = ReviewStage(
        building_id=building.id,
        phase=PhaseType.SUPPLEMENT_1,
        phase_order=1,
    )
    db_session.add_all([preliminary, supplement])
    db_session.commit()
    db_session.refresh(preliminary)
    db_session.refresh(supplement)
    db_session.add_all([
        ReviewOpinionDetail(
            stage_id=preliminary.id,
            phase="preliminary",
            phase_group="preliminary",
            row_number=33,
            category="부재설계의 적정성 - 구조설계 요소",
            severity="L3",
            content="전이보 스트럽 간격 보완할 것.",
        ),
        ReviewOpinionDetail(
            stage_id=supplement.id,
            phase="supplement_1",
            phase_group="supplement",
            row_number=34,
            category="기타의견",
            severity="L0",
            content="지반조사서 누락",
        ),
    ])
    db_session.commit()

    res = client.get("/api/buildings/stats", headers=headers)
    assert res.status_code == 200
    keyword_stats = res.json()["keyword_stats"]
    by_keyword = {row["keyword"]: row for row in keyword_stats["by_keyword"]}

    assert keyword_stats["total_details"] == 2
    assert keyword_stats["detail_counts"] == {"preliminary": 1, "supplement": 1}
    assert by_keyword["전이보"]["preliminary"] == 1
    assert by_keyword["스트럽"]["preliminary"] == 1
    assert by_keyword["보완"]["preliminary"] == 1
    assert by_keyword["지반조사서"]["supplement"] == 1
    assert by_keyword["누락"]["supplement"] == 1


def test_secretary_stats_severity_excludes_other_group(
    client, db_session, make_user, make_reviewer, make_building
):
    sec, sec_h = make_user(UserRole.SECRETARY)
    sec.group_no = 1
    db_session.commit()
    _, _, b1, _, _, b2 = _make_two_groups(
        make_user, make_reviewer, make_building, db_session
    )

    stage1 = ReviewStage(
        building_id=b1.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
    )
    stage2 = ReviewStage(
        building_id=b2.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
    )
    db_session.add_all([stage1, stage2])
    db_session.commit()
    db_session.refresh(stage1)
    db_session.refresh(stage2)
    db_session.add_all([
        ReviewSeveritySummary(
            stage_id=stage1.id,
            category="기타의견",
            severity="L0",
            count=1,
        ),
        ReviewSeveritySummary(
            stage_id=stage2.id,
            category="기타의견",
            severity="L4",
            count=5,
        ),
    ])
    db_session.commit()

    res = client.get("/api/buildings/stats", headers=sec_h)
    assert res.status_code == 200
    severity_stats = res.json()["severity_stats"]
    assert severity_stats["total"] == 1
    assert severity_stats["totals"]["L0"] == 1
    assert severity_stats["totals"]["L4"] == 0
    assert severity_stats["by_report_max"]["total"] == 1
    assert severity_stats["by_report_max"]["totals"]["L0"] == 1
    assert severity_stats["by_report_max"]["totals"]["L4"] == 0


def test_secretary_stats_keyword_excludes_other_group(
    client, db_session, make_user, make_reviewer, make_building
):
    sec, sec_h = make_user(UserRole.SECRETARY)
    sec.group_no = 1
    db_session.commit()
    _, _, b1, _, _, b2 = _make_two_groups(
        make_user, make_reviewer, make_building, db_session
    )

    stage1 = ReviewStage(
        building_id=b1.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
    )
    stage2 = ReviewStage(
        building_id=b2.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
    )
    db_session.add_all([stage1, stage2])
    db_session.commit()
    db_session.refresh(stage1)
    db_session.refresh(stage2)
    db_session.add_all([
        ReviewOpinionDetail(
            stage_id=stage1.id,
            phase="preliminary",
            phase_group="preliminary",
            row_number=33,
            category="기타의견",
            severity="L0",
            content="지반조사서 누락",
        ),
        ReviewOpinionDetail(
            stage_id=stage2.id,
            phase="preliminary",
            phase_group="preliminary",
            row_number=33,
            category="기타의견",
            severity="L4",
            content="전이보 스트럽 보완",
        ),
    ])
    db_session.commit()

    res = client.get("/api/buildings/stats", headers=sec_h)
    assert res.status_code == 200
    keyword_stats = res.json()["keyword_stats"]
    keywords = {row["keyword"] for row in keyword_stats["by_keyword"]}
    assert keyword_stats["total_details"] == 1
    assert "지반조사서" in keywords
    assert "전이보" not in keywords


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
