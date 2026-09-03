"""조합 라벨 저장·LLM 출력 검증 테스트."""

from models.opinion_label import (
    LABEL_SOURCE_LLM,
    LABEL_SOURCE_RULE,
    NO_SECONDARY_TARGET,
    RUN_STATUS_PENDING,
    OpinionCombinationLabel,
    OpinionLabelRun,
)
from models.review_opinion_detail import ReviewOpinionDetail
from models.review_stage import PhaseType, ReviewStage
from services.opinion_labeler import _validate, build_json_schema
from services.opinion_labeling import compute_input_hash, sync_rule_labels


def _make_details(db_session, make_building, contents):
    building = make_building(mgmt_no=f"LABEL-{id(contents)}")
    stage = ReviewStage(
        building_id=building.id, phase=PhaseType.PRELIMINARY, phase_order=0
    )
    db_session.add(stage)
    db_session.commit()
    db_session.refresh(stage)
    details = [
        ReviewOpinionDetail(
            stage_id=stage.id,
            phase="preliminary",
            phase_group="preliminary",
            row_number=index + 1,
            category="기타의견",
            severity="L1",
            content=content,
        )
        for index, content in enumerate(contents)
    ]
    db_session.add_all(details)
    db_session.commit()
    return details


def test_규칙_라벨을_저장하고_미분류는_대기로_등록한다(db_session, make_building):
    details = _make_details(db_session, make_building, [
        "구조일반사항이 누락되었습니다.",
        "구조계산서와 구조도면 불일치",
        "적합",
    ])

    result = sync_rule_labels(db_session, details)
    db_session.commit()

    assert result["details"] == 3
    assert result["labeled_details"] == 2
    assert result["labels"] == 2
    assert result["pending_runs"] == 1

    labels = db_session.query(OpinionCombinationLabel).all()
    made = {(row.primary_target, row.secondary_target, row.issue_type) for row in labels}
    assert ("구조일반사항", NO_SECONDARY_TARGET, "누락") in made
    assert ("구조계산서", "구조도면", "불일치") in made
    assert all(row.source == LABEL_SOURCE_RULE for row in labels)

    runs = db_session.query(OpinionLabelRun).all()
    assert len(runs) == 1
    assert runs[0].status == RUN_STATUS_PENDING
    assert runs[0].unmatched_reason == "no_target_issue"


def test_다시_동기화해도_라벨과_대기가_중복되지_않는다(db_session, make_building):
    details = _make_details(db_session, make_building, [
        "구조일반사항 누락",
        "적합",
    ])

    sync_rule_labels(db_session, details)
    db_session.commit()
    sync_rule_labels(db_session, details)
    db_session.commit()

    assert db_session.query(OpinionCombinationLabel).count() == 1
    assert db_session.query(OpinionLabelRun).count() == 1


def test_LLM_라벨은_규칙_동기화로_지워지지_않는다(db_session, make_building):
    details = _make_details(db_session, make_building, ["구조일반사항 누락"])
    db_session.add(OpinionCombinationLabel(
        detail_id=details[0].id,
        primary_target="내진설계",
        secondary_target=NO_SECONDARY_TARGET,
        issue_type="근거미제시",
        source=LABEL_SOURCE_LLM,
    ))
    db_session.commit()

    sync_rule_labels(db_session, details)
    db_session.commit()

    sources = {row.source for row in db_session.query(OpinionCombinationLabel).all()}
    assert sources == {LABEL_SOURCE_RULE, LABEL_SOURCE_LLM}


def test_입력_해시는_내용과_사유에_따라_달라진다():
    base = compute_input_hash(content="구조도면", category="기타의견", unmatched_reason="no_issue")
    assert base == compute_input_hash(
        content="구조도면", category="기타의견", unmatched_reason="no_issue"
    )
    assert base != compute_input_hash(
        content="구조도면 누락", category="기타의견", unmatched_reason="no_issue"
    )
    assert base != compute_input_hash(
        content="구조도면", category="기타의견", unmatched_reason="no_target"
    )


def test_LLM_출력은_허용_목록_밖이면_버린다():
    result = _validate([
        {"primary_target": "구조도면", "secondary_target": "", "issue_type": "누락"},
        {"primary_target": "존재하지않는대상", "secondary_target": "", "issue_type": "누락"},
        {"primary_target": "구조도면", "secondary_target": "", "issue_type": "존재하지않는유형"},
        "문자열",
    ])
    assert [(r.primary_target, r.secondary_target, r.issue_type) for r in result] == [
        ("구조도면", "", "누락")
    ]


def test_LLM_출력의_관계형_라벨을_정규화한다():
    # 불일치가 아닌데 secondary 가 오면 단일 대상으로 낮춘다.
    downgraded = _validate([
        {"primary_target": "구조도면", "secondary_target": "구조계산서", "issue_type": "누락"},
    ])
    assert downgraded[0].secondary_target == NO_SECONDARY_TARGET

    # 같은 관계가 두 방향으로 저장되지 않도록 순서를 고정한다.
    a = _validate([
        {"primary_target": "구조도면", "secondary_target": "구조계산서", "issue_type": "불일치"},
    ])[0]
    b = _validate([
        {"primary_target": "구조계산서", "secondary_target": "구조도면", "issue_type": "불일치"},
    ])[0]
    assert (a.primary_target, a.secondary_target) == (b.primary_target, b.secondary_target)

    # primary 와 secondary 가 같으면 단일 대상으로 본다.
    same = _validate([
        {"primary_target": "구조도면", "secondary_target": "구조도면", "issue_type": "불일치"},
    ])
    assert same[0].secondary_target == NO_SECONDARY_TARGET


def test_JSON_스키마는_닫힌_enum이다():
    schema = build_json_schema()
    label_props = (
        schema["properties"]["items"]["items"]["properties"]["labels"]["items"]["properties"]
    )
    assert "구조도면" in label_props["primary_target"]["enum"]
    assert NO_SECONDARY_TARGET in label_props["secondary_target"]["enum"]
    assert "누락" in label_props["issue_type"]["enum"]
    assert schema["additionalProperties"] is False
