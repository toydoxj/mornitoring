"""검토위원별 현황 '검토완료' 집계 회귀 테스트.

검토완료 = 검토서를 한 장이라도 제출한 건물(관리번호) 수.
한 건물에서 예비·1차·2차를 몇 장 내든 1로 센다.
"""

from datetime import datetime

from models.review_stage import PhaseType, ReviewStage
from models.user import UserRole


PHASE_ORDER = {
    PhaseType.PRELIMINARY: 0,
    PhaseType.SUPPLEMENT_1: 1,
    PhaseType.SUPPLEMENT_2: 2,
}


def _add_stage(db_session, building, phase, *, submitted: bool):
    """건물에 검토 단계를 붙인다. submitted=False면 도서 접수만 된 상태."""
    stage = ReviewStage(
        building_id=building.id,
        phase=phase,
        phase_order=PHASE_ORDER[phase],
        doc_received_at=datetime(2026, 3, 2),
        report_submitted_at=datetime(2026, 3, 10) if submitted else None,
        reviewer_name="검토위원1" if submitted else None,
    )
    db_session.add(stage)
    db_session.commit()
    return stage


def _reviewer_row(client, headers, name):
    res = client.get("/api/buildings/stats?scope=all", headers=headers)
    assert res.status_code == 200, res.text
    rows = res.json()["reviewer_stats"]
    return next(row for row in rows if row["name"] == name)


def test_multiple_reports_on_one_building_count_as_one(
    client, db_session, make_user, make_reviewer, make_building
):
    """한 건물에 예비+1차 2장을 내도 검토완료는 1건이다."""
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    rev_user, reviewer, _ = make_reviewer(group_no=1)
    rev_user.name = "검토위원1"
    db_session.commit()

    building = make_building(mgmt_no="RVW-0001", reviewer_id=reviewer.id)
    _add_stage(db_session, building, PhaseType.PRELIMINARY, submitted=True)
    _add_stage(db_session, building, PhaseType.SUPPLEMENT_1, submitted=True)

    row = _reviewer_row(client, headers, "검토위원1")
    assert row["reviewed"] == 1
    # 검토서 장수는 기존 열이 그대로 2장으로 센다
    assert row["preliminary"]["report_submitted"] == 1
    assert row["supplement"]["report_submitted"] == 1


def test_preliminary_only_counts_as_one(
    client, db_session, make_user, make_reviewer, make_building
):
    """예비검토서만 제출해도 1건이다."""
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    rev_user, reviewer, _ = make_reviewer(group_no=1)
    rev_user.name = "검토위원1"
    db_session.commit()

    building = make_building(mgmt_no="RVW-0002", reviewer_id=reviewer.id)
    _add_stage(db_session, building, PhaseType.PRELIMINARY, submitted=True)

    assert _reviewer_row(client, headers, "검토위원1")["reviewed"] == 1


def test_supplement_only_counts_as_one(
    client, db_session, make_user, make_reviewer, make_building
):
    """예비 없이 1차 보완검토서만 제출해도 1건이다."""
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    rev_user, reviewer, _ = make_reviewer(group_no=1)
    rev_user.name = "검토위원1"
    db_session.commit()

    building = make_building(mgmt_no="RVW-0003", reviewer_id=reviewer.id)
    _add_stage(db_session, building, PhaseType.SUPPLEMENT_1, submitted=True)

    assert _reviewer_row(client, headers, "검토위원1")["reviewed"] == 1


def test_three_phases_on_one_building_count_as_one(
    client, db_session, make_user, make_reviewer, make_building
):
    """예비·1차·2차까지 진행돼도 건물 1개면 1건이다."""
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    rev_user, reviewer, _ = make_reviewer(group_no=1)
    rev_user.name = "검토위원1"
    db_session.commit()

    building = make_building(mgmt_no="RVW-0004", reviewer_id=reviewer.id)
    for phase in (PhaseType.PRELIMINARY, PhaseType.SUPPLEMENT_1, PhaseType.SUPPLEMENT_2):
        _add_stage(db_session, building, phase, submitted=True)

    assert _reviewer_row(client, headers, "검토위원1")["reviewed"] == 1


def test_unsubmitted_stage_is_not_counted(
    client, db_session, make_user, make_reviewer, make_building
):
    """도서만 접수되고 검토서가 없으면 검토완료에 들어가지 않는다."""
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    rev_user, reviewer, _ = make_reviewer(group_no=1)
    rev_user.name = "검토위원1"
    db_session.commit()

    building = make_building(mgmt_no="RVW-0005", reviewer_id=reviewer.id)
    _add_stage(db_session, building, PhaseType.PRELIMINARY, submitted=False)

    row = _reviewer_row(client, headers, "검토위원1")
    assert row["reviewed"] == 0
    assert row["total"] == 1


def test_reviewed_counts_distinct_buildings(
    client, db_session, make_user, make_reviewer, make_building
):
    """건물이 여러 개면 검토서를 낸 건물 수만큼 센다."""
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    rev_user, reviewer, _ = make_reviewer(group_no=1)
    rev_user.name = "검토위원1"
    db_session.commit()

    b1 = make_building(mgmt_no="RVW-0006", reviewer_id=reviewer.id)
    b2 = make_building(mgmt_no="RVW-0007", reviewer_id=reviewer.id)
    b3 = make_building(mgmt_no="RVW-0008", reviewer_id=reviewer.id)
    _add_stage(db_session, b1, PhaseType.PRELIMINARY, submitted=True)
    _add_stage(db_session, b1, PhaseType.SUPPLEMENT_1, submitted=True)
    _add_stage(db_session, b2, PhaseType.SUPPLEMENT_1, submitted=True)
    _add_stage(db_session, b3, PhaseType.PRELIMINARY, submitted=False)

    row = _reviewer_row(client, headers, "검토위원1")
    assert row["total"] == 3
    assert row["reviewed"] == 2


def test_reviewer_without_any_stage_has_zero(
    client, db_session, make_user, make_reviewer, make_building
):
    """검토 단계가 아예 없는 위원도 0으로 응답에 포함된다."""
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    rev_user, reviewer, _ = make_reviewer(group_no=2)
    rev_user.name = "검토위원2"
    db_session.commit()

    make_building(mgmt_no="RVW-0009", reviewer_id=reviewer.id)

    row = _reviewer_row(client, headers, "검토위원2")
    assert row["reviewed"] == 0


def test_name_only_assignment_is_counted(
    client, db_session, make_user, make_building
):
    """Reviewer 계정 없이 이름만 배정된 건물도 그 이름으로 집계된다."""
    _, headers = make_user(UserRole.CHIEF_SECRETARY)

    building = make_building(mgmt_no="RVW-0010")
    building.assigned_reviewer_name = "이름만위원"
    db_session.commit()
    _add_stage(db_session, building, PhaseType.PRELIMINARY, submitted=True)
    _add_stage(db_session, building, PhaseType.SUPPLEMENT_1, submitted=True)

    row = _reviewer_row(client, headers, "이름만위원")
    assert row["total"] == 1
    assert row["reviewed"] == 1


def test_reviewed_is_split_per_reviewer(
    client, db_session, make_user, make_reviewer, make_building
):
    """위원이 여럿이면 각자의 건물만 센다 (합계행 단순 합산의 전제)."""
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    user_a, rev_a, _ = make_reviewer(group_no=1)
    user_a.name = "위원A"
    user_b, rev_b, _ = make_reviewer(group_no=2)
    user_b.name = "위원B"
    db_session.commit()

    a1 = make_building(mgmt_no="RVW-0011", reviewer_id=rev_a.id)
    a2 = make_building(mgmt_no="RVW-0012", reviewer_id=rev_a.id)
    b1 = make_building(mgmt_no="RVW-0013", reviewer_id=rev_b.id)
    _add_stage(db_session, a1, PhaseType.PRELIMINARY, submitted=True)
    _add_stage(db_session, a1, PhaseType.SUPPLEMENT_1, submitted=True)
    _add_stage(db_session, a2, PhaseType.PRELIMINARY, submitted=True)
    _add_stage(db_session, b1, PhaseType.PRELIMINARY, submitted=True)

    res = client.get("/api/buildings/stats?scope=all", headers=headers)
    rows = {row["name"]: row for row in res.json()["reviewer_stats"]}
    assert rows["위원A"]["reviewed"] == 2
    assert rows["위원B"]["reviewed"] == 1
    # 합계행은 프론트에서 단순 합산한다 — 건물 3개 중 검토서가 있는 건 3개
    assert sum(row["reviewed"] for row in rows.values()) == 3


# ===== 엑셀 import 경로: 제출일시 없이 판정·상세의견만 들어온 검토 이력 =====
#
# ledger_import_technical 로 들어온 검토 이력은 양식에 제출일 열이 없어
# report_submitted_at 이 비어 있다. 제출일시만 보면 실제 검토한 건이 통계에서
# 통째로 빠지므로 판정(result)도 검토 흔적으로 인정한다. 상세의견은 '미실시'
# 메모에서도 생성되므로 근거로 쓰지 않는다.


def _add_imported_stage(
    db_session, building, phase, *, result=None, opinion=None, detail_count=0
):
    """엑셀 import 로 들어온 모양의 단계 (report_submitted_at 없음)."""
    from models.review_opinion_detail import ReviewOpinionDetail
    from models.review_stage import ResultType

    stage = ReviewStage(
        building_id=building.id,
        phase=phase,
        phase_order=PHASE_ORDER[phase],
        report_submitted_at=None,
        result=ResultType(result) if result else None,
        review_opinion=opinion,
    )
    db_session.add(stage)
    db_session.commit()
    db_session.refresh(stage)

    for i in range(detail_count):
        db_session.add(
            ReviewOpinionDetail(
                stage_id=stage.id,
                phase=phase.value,
                phase_group="preliminary" if phase == PhaseType.PRELIMINARY else "supplement",
                row_number=i + 1,
                category="하중 적정성",
                severity="L1",
                content=f"상세의견 {i + 1}",
            )
        )
    db_session.commit()
    return stage


def test_imported_stage_with_result_counts_as_reviewed(
    client, db_session, make_user, make_reviewer, make_building
):
    """제출일시가 없어도 판정이 있으면 검토완료로 센다."""
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    rev_user, reviewer, _ = make_reviewer(group_no=1)
    rev_user.name = "검토위원1"
    db_session.commit()

    building = make_building(mgmt_no="RVW-0020", reviewer_id=reviewer.id)
    _add_imported_stage(
        db_session, building, PhaseType.PRELIMINARY,
        result="recalculate", opinion="[하중 적정성] 1. 조적하중 추가 필요",
    )

    row = _reviewer_row(client, headers, "검토위원1")
    assert row["reviewed"] == 1
    # 기존 예비검토서 열도 같은 기준을 쓴다
    assert row["preliminary"]["report_submitted"] == 1
    assert row["preliminary"]["results"]["recalculate"] == 1


def test_detail_only_stage_is_not_counted(
    client, db_session, make_user, make_reviewer, make_building
):
    """판정 없이 상세의견만 있는 건은 검토완료로 세지 않는다.

    importer 가 분류 없는 본문도 [기타의견] 상세의견 1건으로 변환하므로
    (_parse_ledger_opinion_entries), 상세의견 유무로는 '미실시' 메모와
    실제 검토를 구분할 수 없다.
    """
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    rev_user, reviewer, _ = make_reviewer(group_no=1)
    rev_user.name = "검토위원1"
    db_session.commit()

    building = make_building(mgmt_no="RVW-0021", reviewer_id=reviewer.id)
    _add_imported_stage(
        db_session, building, PhaseType.PRELIMINARY,
        opinion="기초자료 미제출로 1차(예비)검토 미실시", detail_count=1,
    )

    assert _reviewer_row(client, headers, "검토위원1")["reviewed"] == 0


def test_not_reviewed_memo_through_real_importer_is_excluded(
    client, db_session, make_user, make_reviewer, make_building
):
    """실제 importer 경로로 들어온 '미실시' 메모도 검토완료에서 제외된다.

    _replace_ledger_opinion_details 는 대괄호 분류가 없는 본문을 [기타의견]
    상세의견으로 변환한다. 그 산출물이 집계에 섞이지 않는지 확인한다.
    """
    from engines.ledger_import_technical import _replace_ledger_opinion_details
    from models.review_opinion_detail import ReviewOpinionDetail

    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    rev_user, reviewer, _ = make_reviewer(group_no=1)
    rev_user.name = "검토위원1"
    db_session.commit()

    building = make_building(mgmt_no="RVW-0023", reviewer_id=reviewer.id)
    stage = ReviewStage(
        building_id=building.id,
        phase=PhaseType.PRELIMINARY,
        phase_order=PHASE_ORDER[PhaseType.PRELIMINARY],
        review_opinion="기초자료 미제출로 1차(예비)검토 미실시",
    )
    db_session.add(stage)
    db_session.commit()

    _replace_ledger_opinion_details(
        db_session,
        stage,
        phase=PhaseType.PRELIMINARY,
        opinion_text="기초자료 미제출로 1차(예비)검토 미실시",
    )
    db_session.commit()

    # importer 가 실제로 상세의견을 만들었는지 먼저 확인 (전제가 깨지면 테스트 무의미)
    created = (
        db_session.query(ReviewOpinionDetail)
        .filter(ReviewOpinionDetail.stage_id == stage.id)
        .count()
    )
    assert created >= 1, "importer 가 상세의견을 만들지 않으면 이 회귀 테스트는 의미가 없다"

    row = _reviewer_row(client, headers, "검토위원1")
    assert row["reviewed"] == 0
    assert row["preliminary"]["report_submitted"] == 0


def test_mixed_reviewer_matches_operational_pattern(
    client, db_session, make_user, make_reviewer, make_building
):
    """운영 데이터 형태 재현: 업로드 2건 + import 검토 1건 + 미실시 2건 = 3건."""
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    rev_user, reviewer, _ = make_reviewer(group_no=1)
    rev_user.name = "혼합위원"
    db_session.commit()

    uploaded_a = make_building(mgmt_no="RVW-0030", reviewer_id=reviewer.id)
    uploaded_b = make_building(mgmt_no="RVW-0031", reviewer_id=reviewer.id)
    imported = make_building(mgmt_no="RVW-0032", reviewer_id=reviewer.id)
    skipped_a = make_building(mgmt_no="RVW-0033", reviewer_id=reviewer.id)
    skipped_b = make_building(mgmt_no="RVW-0034", reviewer_id=reviewer.id)

    _add_stage(db_session, uploaded_a, PhaseType.PRELIMINARY, submitted=True)
    _add_stage(db_session, uploaded_b, PhaseType.PRELIMINARY, submitted=True)
    _add_imported_stage(
        db_session, imported, PhaseType.PRELIMINARY,
        result="recalculate", opinion="[하중 적정성] 1. 확인 바랍니다", detail_count=16,
    )
    for b in (skipped_a, skipped_b):
        _add_imported_stage(
            db_session, b, PhaseType.PRELIMINARY,
            opinion="기초자료 미제출로 1차(예비)검토 미실시",
        )

    row = _reviewer_row(client, headers, "혼합위원")
    assert row["total"] == 5
    assert row["reviewed"] == 3
