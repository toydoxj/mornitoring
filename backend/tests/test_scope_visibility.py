"""간사 조 단위 데이터 가시성 회귀 테스트.

운영 정책:
- TEAM_LEADER / CHIEF_SECRETARY: 전체
- SECRETARY + group_no 있음: 같은 조 검토위원 담당 건물만
- SECRETARY + group_no 없음(미배정): 전체 (운영 안전성 우선)
- REVIEWER: 본인 reviewer_id (기존 정책 유지)
"""

from datetime import date

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


def test_building_list_returns_latest_result(
    client, db_session, make_user, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    building = make_building(mgmt_no="LATEST-RESULT-001")
    db_session.add_all([
        ReviewStage(
            building_id=building.id,
            phase=PhaseType.PRELIMINARY,
            phase_order=0,
            result=ResultType.SIMPLE_ERROR,
        ),
        ReviewStage(
            building_id=building.id,
            phase=PhaseType.SUPPLEMENT_1,
            phase_order=1,
            result=ResultType.RECALCULATE,
        ),
    ])
    db_session.commit()

    res = client.get("/api/buildings", headers=headers)
    assert res.status_code == 200
    item = next(
        b for b in res.json()["items"] if b["mgmt_no"] == "LATEST-RESULT-001"
    )
    assert item["latest_result"] == "recalculate"


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


def test_secretary_inquiry_list_includes_same_group_submitter(
    client, db_session, make_user, make_reviewer, make_building
):
    sec, sec_h = make_user(UserRole.SECRETARY, group_no=1)
    reviewer_user, _same_group_reviewer, _ = make_reviewer(group_no=1)
    _other_user, other_group_reviewer, _ = make_reviewer(group_no=2)
    building = make_building(
        reviewer_id=other_group_reviewer.id,
        mgmt_no="INQ-SUBMITTER-GROUP-001",
    )

    db_session.add(Inquiry(
        building_id=building.id, mgmt_no=building.mgmt_no, phase="preliminary",
        submitter_id=reviewer_user.id, submitter_name=reviewer_user.name,
        content="same group submitter inquiry", status=InquiryStatus.OPEN,
    ))
    db_session.commit()

    res = client.get("/api/reviews/inquiries", headers=sec_h)
    assert res.status_code == 200
    contents = [i["content"] for i in res.json()["items"]]
    assert "same group submitter inquiry" in contents


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


def test_stats_counts_missing_area_and_floor_as_zero(
    client, db_session, make_user, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    building = make_building(mgmt_no="REG-STATS-NULL-001")
    building.gross_area = None
    building.floors_above = None
    db_session.commit()

    res = client.get("/api/buildings/stats", headers=headers)
    assert res.status_code == 200
    regional_stats = res.json()["regional_stats"]

    area_total = regional_stats["area"][0]
    assert area_total["area_0_300"] == 1
    assert area_total["area_300_600"] == 0
    assert area_total["area_600_1000"] == 0
    assert area_total["area_1000_5000"] == 0
    assert area_total["area_5000_over"] == 0

    floor_total = regional_stats["floors"][0]
    assert floor_total["floors_under_6"] == 1
    assert floor_total["floors_6_under_16"] == 0
    assert floor_total["floors_16_over"] == 0


def test_stats_splits_uploaded_reports_and_deleted_submissions(
    client, db_session, make_user, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    uploaded_preliminary = make_building(mgmt_no="STAT-UP-PRE")
    deleted_preliminary = make_building(mgmt_no="STAT-DEL-PRE")
    uploaded_supplement = make_building(mgmt_no="STAT-UP-SUP")
    deleted_supplement = make_building(mgmt_no="STAT-DEL-SUP")
    pending = make_building(mgmt_no="STAT-PENDING")

    submitted_at = date(2026, 6, 22)
    db_session.add_all([
        ReviewStage(
            building_id=uploaded_preliminary.id,
            phase=PhaseType.PRELIMINARY,
            phase_order=0,
            report_submitted_at=submitted_at,
            s3_file_key="reviews/preliminary/2026-06-22/STAT-UP-PRE.xlsm",
        ),
        ReviewStage(
            building_id=deleted_preliminary.id,
            phase=PhaseType.PRELIMINARY,
            phase_order=0,
            report_submitted_at=submitted_at,
            s3_file_key=None,
        ),
        ReviewStage(
            building_id=uploaded_supplement.id,
            phase=PhaseType.SUPPLEMENT_1,
            phase_order=1,
            report_submitted_at=submitted_at,
            s3_file_key="reviews/supplement_1/2026-06-22/STAT-UP-SUP.xlsm",
        ),
        ReviewStage(
            building_id=deleted_supplement.id,
            phase=PhaseType.SUPPLEMENT_2,
            phase_order=2,
            report_submitted_at=submitted_at,
            s3_file_key=None,
        ),
        ReviewStage(
            building_id=pending.id,
            phase=PhaseType.SUPPLEMENT_3,
            phase_order=3,
            report_submitted_at=None,
            s3_file_key="reviews/supplement_3/2026-06-22/STAT-PENDING.xlsm",
        ),
    ])
    db_session.commit()

    res = client.get("/api/buildings/stats", headers=headers)

    assert res.status_code == 200
    body = res.json()
    assert body["uploaded_reports_preliminary"] == 1
    assert body["uploaded_reports_supplement"] == 1
    assert body["deleted_submitted_reports_preliminary"] == 1
    assert body["deleted_submitted_reports_supplement"] == 1


def test_stats_reviewer_status_counts_documents_reports_and_results(
    client, db_session, make_user, make_reviewer, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    reviewer_user, reviewer, _ = make_reviewer(group_no=3)
    first = make_building(mgmt_no="REV-STAT-001", reviewer_id=reviewer.id)
    second = make_building(mgmt_no="REV-STAT-002", reviewer_id=reviewer.id)
    first.assigned_reviewer_name = reviewer_user.name
    second.assigned_reviewer_name = reviewer_user.name

    db_session.add_all([
        ReviewStage(
            building_id=first.id,
            phase=PhaseType.PRELIMINARY,
            phase_order=0,
            doc_received_at=date(2026, 6, 1),
            report_submitted_at=date(2026, 6, 3),
            result=ResultType.PASS,
        ),
        ReviewStage(
            building_id=second.id,
            phase=PhaseType.PRELIMINARY,
            phase_order=0,
            doc_received_at=date(2026, 6, 2),
        ),
        ReviewStage(
            building_id=first.id,
            phase=PhaseType.SUPPLEMENT_1,
            phase_order=1,
            doc_received_at=date(2026, 6, 10),
            report_submitted_at=date(2026, 6, 12),
            result=ResultType.SIMPLE_ERROR,
        ),
        ReviewStage(
            building_id=second.id,
            phase=PhaseType.SUPPLEMENT_1,
            phase_order=1,
            doc_received_at=date(2026, 6, 11),
            report_submitted_at=date(2026, 6, 13),
            result=ResultType.RECALCULATE,
        ),
        ReviewStage(
            building_id=second.id,
            phase=PhaseType.SUPPLEMENT_2,
            phase_order=2,
            doc_received_at=date(2026, 6, 14),
            result=ResultType.PASS,
        ),
    ])
    db_session.commit()

    res = client.get("/api/buildings/stats", headers=headers)

    assert res.status_code == 200
    reviewer_stats = res.json()["reviewer_stats"]
    row = next(item for item in reviewer_stats if item["name"] == reviewer_user.name)
    assert row["group_no"] == 3
    assert row["preliminary"] == {
        "doc_received": 2,
        "report_submitted": 1,
        "results": {"pass": 1, "simple_error": 0, "recalculate": 0},
    }
    assert row["supplement"] == {
        "doc_received": 3,
        "report_submitted": 2,
        "results": {"pass": 0, "simple_error": 1, "recalculate": 1},
    }


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
    b1.drawing_creator_qualification = "건축사"

    b2 = make_building(mgmt_no="REG-STATS-002")
    b2.sido = "서울특별시"
    b2.sigungu = "강남구"
    b2.gross_area = 300
    b2.floors_above = 6
    b2.is_multi_use = True
    b2.drawing_creator_qualification = "건축구조기술사"

    b3 = make_building(mgmt_no="REG-STATS-003")
    b3.sido = "부산광역시"
    b3.sigungu = "해운대구"
    b3.gross_area = 5000
    b3.floors_above = 16
    b3.is_high_rise = True
    b3.is_quasi_multi_use = True
    b3.struct_eng_firm = "협력사"
    b3.drawing_creator_qualification = "기타"

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
    assert risk_total["total"] == 4
    assert risk_total["special"] == 1
    assert risk_total["multi_use"] == 1
    assert risk_total["high_rise"] == 1
    assert risk_total["quasi_multi_use"] == 1
    assert risk_total["related_tech_coop_target"] == 4
    assert risk_total["related_tech_coop"] == 1
    assert risk_total["related_tech_coop_missing"] == 3

    seoul = next(row for row in regional_stats["risk"] if row["region"] == "서울특별시")
    assert seoul["total"] == 2
    assert seoul["related_tech_coop_target"] == 2
    assert seoul["related_tech_coop"] == 1
    assert seoul["related_tech_coop_missing"] == 1

    risk_regions = [row["region"] for row in regional_stats["risk"]]
    assert risk_regions[:3] == ["전체", "서울특별시", "부산광역시"]

    drawing_creator_total = regional_stats["drawing_creator"][0]
    assert drawing_creator_total["region"] == "전체"
    assert drawing_creator_total["drawing_creator_architect"] == 1
    assert drawing_creator_total["drawing_creator_structural_engineer"] == 1
    assert drawing_creator_total["drawing_creator_unknown"] == 2

    drawing_creator_seoul = next(
        row for row in regional_stats["drawing_creator"] if row["region"] == "서울특별시"
    )
    assert drawing_creator_seoul["drawing_creator_architect"] == 1
    assert drawing_creator_seoul["drawing_creator_structural_engineer"] == 1
    assert drawing_creator_seoul["drawing_creator_unknown"] == 0


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


def test_stats_returns_opinion_quality_summary_and_details(
    client, db_session, make_user, make_reviewer, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    assigned_user, assigned_reviewer, _ = make_reviewer()
    assigned_user.name = "배정위원"
    assigned_reviewer.group_no = 3
    actual_user, actual_reviewer, _ = make_reviewer()
    actual_user.name = "실제검토자"
    actual_reviewer.group_no = 5
    building = make_building(
        reviewer_id=assigned_reviewer.id,
        mgmt_no="QUAL-STATS-001",
    )
    db_session.commit()

    stage = ReviewStage(
        building_id=building.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
        reviewer_name="실제검토자",
    )
    db_session.add(stage)
    db_session.commit()
    db_session.refresh(stage)
    db_session.add_all([
        ReviewOpinionDetail(
            stage_id=stage.id,
            phase="preliminary",
            phase_group="preliminary",
            row_number=33,
            category="기타의견",
            severity="L0",
            content="너무 황당한 구조계산서입니다.",
        ),
        ReviewOpinionDetail(
            stage_id=stage.id,
            phase="preliminary",
            phase_group="preliminary",
            row_number=34,
            category="기타의견",
            severity="L0",
            content="전이보 간격 확인 필요.",
        ),
    ])
    db_session.commit()

    res = client.get("/api/buildings/stats", headers=headers)
    assert res.status_code == 200
    quality_stats = res.json()["opinion_quality_stats"]
    by_term = {row["term"]: row["count"] for row in quality_stats["by_term"]}
    by_category = {
        row["category"]: row["count"]
        for row in quality_stats["by_category"]
    }

    assert quality_stats["total_details"] == 2
    assert quality_stats["flagged_details"] == 1
    assert quality_stats["clean_details"] == 1
    assert by_term["너무"] == 1
    assert by_term["황당함"] == 1
    assert by_category["감정적·비난성 표현"] == 1
    assert by_category["과장 표현"] == 1
    assert quality_stats["by_tag"] == [{"tag": "ASSERTIVE", "count": 1}, {"tag": "EMOTION", "count": 1}]

    item = quality_stats["items"][0]
    assert item["mgmt_no"] == "QUAL-STATS-001"
    assert item["group_no"] == 5
    assert item["reviewer_name"] == "실제검토자"
    assert item["opinion"] == "너무 황당한 구조계산서입니다."
    assert item["matched_tags"] == ["ASSERTIVE", "EMOTION"]
    assert "설계 의도 확인 필요" in item["recommended_replacements"]
    assert item["quality_decision"] == "unsuitable"


def test_stats_opinion_quality_suitable_decision_excluded(
    client, db_session, make_user, make_reviewer, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    reviewer_user, reviewer, _ = make_reviewer()
    reviewer_user.name = "판정위원"
    reviewer.group_no = 2
    building = make_building(
        reviewer_id=reviewer.id,
        mgmt_no="QUAL-DECISION-001",
    )
    db_session.commit()

    stage = ReviewStage(
        building_id=building.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
        reviewer_name="판정위원",
    )
    db_session.add(stage)
    db_session.commit()
    db_session.refresh(stage)
    detail = ReviewOpinionDetail(
        stage_id=stage.id,
        phase="preliminary",
        phase_group="preliminary",
        row_number=33,
        category="기타의견",
        severity="L0",
        content="황당한 구조계산서입니다.",
    )
    db_session.add(detail)
    db_session.commit()
    db_session.refresh(detail)

    before_res = client.get("/api/buildings/stats", headers=headers)
    assert before_res.status_code == 200
    before_quality = before_res.json()["opinion_quality_stats"]
    assert before_quality["total_details"] == 1
    assert before_quality["flagged_details"] == 1
    assert before_quality["items"][0]["quality_decision"] == "unsuitable"

    patch_res = client.patch(
        f"/api/reviews/opinion-details/{detail.id}/quality-decision",
        headers=headers,
        json={"quality_decision": "suitable"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["quality_decision"] == "suitable"

    db_session.refresh(detail)
    assert detail.quality_decision == "suitable"

    after_res = client.get("/api/buildings/stats", headers=headers)
    assert after_res.status_code == 200
    after_quality = after_res.json()["opinion_quality_stats"]
    assert after_quality["total_details"] == 0
    assert after_quality["flagged_details"] == 0
    assert after_quality["clean_details"] == 0
    assert after_quality["by_term"] == []
    assert after_quality["items"] == []


def test_stats_opinion_quality_group_uses_actual_reviewer_only(
    client, db_session, make_user, make_reviewer, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    assigned_user, assigned_reviewer, _ = make_reviewer()
    assigned_user.name = "배정위원"
    assigned_reviewer.group_no = 3
    building = make_building(
        reviewer_id=assigned_reviewer.id,
        mgmt_no="QUAL-STATS-GROUP",
    )
    db_session.commit()

    stage = ReviewStage(
        building_id=building.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
        reviewer_name="외부검토자",
    )
    db_session.add(stage)
    db_session.commit()
    db_session.refresh(stage)
    db_session.add(ReviewOpinionDetail(
        stage_id=stage.id,
        phase="preliminary",
        phase_group="preliminary",
        row_number=33,
        category="기타의견",
        severity="L0",
        content="황당한 구조계산서입니다.",
    ))
    db_session.commit()

    res = client.get("/api/buildings/stats", headers=headers)
    assert res.status_code == 200
    item = next(
        row
        for row in res.json()["opinion_quality_stats"]["items"]
        if row["mgmt_no"] == "QUAL-STATS-GROUP"
    )
    assert item["reviewer_name"] == "외부검토자"
    assert item["group_no"] is None


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
            content="너무 지반조사서 누락",
        ),
        ReviewOpinionDetail(
            stage_id=stage2.id,
            phase="preliminary",
            phase_group="preliminary",
            row_number=33,
            category="기타의견",
            severity="L4",
            content="황당한 전이보 스트럽 보완",
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

    quality_stats = res.json()["opinion_quality_stats"]
    terms = {row["term"] for row in quality_stats["by_term"]}
    assert quality_stats["total_details"] == 1
    assert quality_stats["flagged_details"] == 1
    assert "너무" in terms
    assert "황당함" not in terms


def test_quality_checks_lists_only_flagged_l3_l4_targets(
    client, db_session, make_user, make_reviewer, make_building
):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    reviewer_user, reviewer, _ = make_reviewer()
    reviewer_user.name = "품질검토자"
    reviewer.group_no = 4
    building = make_building(
        reviewer_id=reviewer.id,
        mgmt_no="QUAL-CHECK-001",
    )
    building.sido = "서울특별시"
    building.sigungu = "강남구"
    building.beopjeongdong = "역삼동"
    building.main_lot_no = "10"
    building.sub_lot_no = "2"
    db_session.commit()

    stage = ReviewStage(
        building_id=building.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
        reviewer_name="품질검토자",
    )
    db_session.add(stage)
    db_session.commit()
    db_session.refresh(stage)
    db_session.add_all([
        ReviewOpinionDetail(
            stage_id=stage.id,
            phase="preliminary",
            phase_group="preliminary",
            row_number=31,
            category="기타의견",
            severity="L3",
            content="너무 황당한 구조계산서입니다.",
        ),
        ReviewOpinionDetail(
            stage_id=stage.id,
            phase="preliminary",
            phase_group="preliminary",
            row_number=32,
            category="기타의견",
            severity="L2",
            content="너무 황당한 표현이지만 L3/L4가 아닙니다.",
        ),
        ReviewOpinionDetail(
            stage_id=stage.id,
            phase="preliminary",
            phase_group="preliminary",
            row_number=33,
            category="기타의견",
            severity="L4",
            content="전이보 간격 확인 필요.",
        ),
        ReviewOpinionDetail(
            stage_id=stage.id,
            phase="preliminary",
            phase_group="preliminary",
            row_number=34,
            category="기타의견",
            severity="L4",
            content="황당한 구조계산서입니다.",
        ),
    ])
    db_session.commit()

    res = client.get("/api/reviews/quality-checks", headers=headers)
    assert res.status_code == 200
    payload = res.json()
    assert payload["total"] == 1
    assert payload["items"] == [{
        "building_id": building.id,
        "mgmt_no": "QUAL-CHECK-001",
        "full_address": "서울특별시 강남구 역삼동 10-2",
        "building_name": building.building_name,
        "group_no": 4,
        "reviewer_name": "품질검토자",
        "quality_categories": ["감정적·비난성 표현", "과장 표현"],
        "severity_levels": ["L3", "L4"],
        "detail_count": 2,
    }]


def test_secretary_quality_checks_filters_by_group_and_mark_suitable(
    client, db_session, make_user, make_reviewer, make_building
):
    sec, sec_h = make_user(UserRole.SECRETARY)
    sec.group_no = 1
    db_session.commit()
    rev1_user, rev1, b1, rev2_user, rev2, b2 = _make_two_groups(
        make_user, make_reviewer, make_building, db_session
    )
    rev1_user.name = "1조검토자"
    rev2_user.name = "2조검토자"
    db_session.commit()

    stage1 = ReviewStage(
        building_id=b1.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
        reviewer_name="1조검토자",
    )
    stage2 = ReviewStage(
        building_id=b2.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=0,
        reviewer_name="2조검토자",
    )
    db_session.add_all([stage1, stage2])
    db_session.commit()
    db_session.refresh(stage1)
    db_session.refresh(stage2)
    visible_detail = ReviewOpinionDetail(
        stage_id=stage1.id,
        phase="preliminary",
        phase_group="preliminary",
        row_number=31,
        category="기타의견",
        severity="L4",
        content="황당한 구조계산서입니다.",
    )
    hidden_detail = ReviewOpinionDetail(
        stage_id=stage2.id,
        phase="preliminary",
        phase_group="preliminary",
        row_number=31,
        category="기타의견",
        severity="L4",
        content="황당한 구조계산서입니다.",
    )
    db_session.add_all([visible_detail, hidden_detail])
    db_session.commit()

    before = client.get("/api/reviews/quality-checks", headers=sec_h)
    assert before.status_code == 200
    assert [item["mgmt_no"] for item in before.json()["items"]] == ["VIS-G1"]

    hidden_res = client.patch(
        f"/api/reviews/quality-checks/{b2.id}/suitable",
        headers=sec_h,
    )
    assert hidden_res.status_code == 404

    patch_res = client.patch(
        f"/api/reviews/quality-checks/{b1.id}/suitable",
        headers=sec_h,
    )
    assert patch_res.status_code == 200
    assert patch_res.json() == {
        "building_id": b1.id,
        "updated_count": 1,
    }

    db_session.refresh(visible_detail)
    db_session.refresh(hidden_detail)
    assert visible_detail.quality_decision == "suitable"
    assert hidden_detail.quality_decision == "unsuitable"

    after = client.get("/api/reviews/quality-checks", headers=sec_h)
    assert after.status_code == 200
    assert after.json()["items"] == []


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


def test_secretary_cannot_see_unassigned_reviewer(
    client, db_session, make_user, make_reviewer, make_building
):
    sec, sec_h = make_user(UserRole.SECRETARY)
    sec.group_no = 1
    visible_user, visible_rev, _ = make_reviewer()
    visible_user.name = "공개위원"
    visible_rev.group_no = 1
    unassigned_user, unassigned_rev, _ = make_reviewer()
    unassigned_user.name = "미편성위원"
    unassigned_rev.group_no = None
    db_session.commit()

    visible_building = make_building(
        mgmt_no="VISIBLE-REVIEWER", reviewer_id=visible_rev.id
    )
    unassigned_building = make_building(
        mgmt_no="UNASSIGNED-REVIEWER", reviewer_id=unassigned_rev.id
    )
    visible_building.assigned_reviewer_name = visible_user.name
    unassigned_building.assigned_reviewer_name = unassigned_user.name
    db_session.commit()

    res = client.get("/api/buildings", headers=sec_h)
    assert res.status_code == 200
    mgmt_nos = {item["mgmt_no"] for item in res.json()["items"]}
    assert visible_building.mgmt_no in mgmt_nos
    assert unassigned_building.mgmt_no not in mgmt_nos

    detail_res = client.get(f"/api/buildings/{unassigned_building.id}", headers=sec_h)
    assert detail_res.status_code == 404
    patch_res = client.patch(
        f"/api/buildings/{unassigned_building.id}",
        headers=sec_h,
        json={"remarks": "hidden update"},
    )
    assert patch_res.status_code == 404

    names_res = client.get("/api/buildings/reviewer-names", headers=sec_h)
    assert names_res.status_code == 200
    names = names_res.json()
    assert "공개위원" in names
    assert "미편성위원" not in names

    schedule_res = client.get("/api/buildings/reviewer-schedule", headers=sec_h)
    assert schedule_res.status_code == 200
    schedule_names = {row["reviewer_name"] for row in schedule_res.json()}
    assert "공개위원" in schedule_names
    assert "미편성위원" not in schedule_names


def test_unassigned_secretary_keeps_existing_all_visibility(
    client, db_session, make_user, make_reviewer, make_building
):
    sec, sec_h = make_user(UserRole.SECRETARY)
    sec.group_no = None
    visible_user, visible_rev, _ = make_reviewer()
    visible_user.name = "다른조위원"
    visible_rev.group_no = 2
    unassigned_user, unassigned_rev, _ = make_reviewer()
    unassigned_user.name = "미편성위원"
    unassigned_rev.group_no = None
    db_session.commit()

    visible_building = make_building(
        mgmt_no="UNASSIGNED-SEC-VISIBLE", reviewer_id=visible_rev.id
    )
    unassigned_building = make_building(
        mgmt_no="UNASSIGNED-SEC-UNASSIGNED-REVIEWER", reviewer_id=unassigned_rev.id
    )
    visible_building.assigned_reviewer_name = visible_user.name
    unassigned_building.assigned_reviewer_name = unassigned_user.name
    db_session.commit()

    res = client.get("/api/buildings", headers=sec_h)
    assert res.status_code == 200
    mgmt_nos = {item["mgmt_no"] for item in res.json()["items"]}
    assert visible_building.mgmt_no in mgmt_nos
    assert unassigned_building.mgmt_no in mgmt_nos
