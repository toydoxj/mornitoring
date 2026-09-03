"""조합 키워드 분석 엔진 테스트."""

from engines.review_keyword_analyzer import (
    ISSUE_NAMES,
    TARGET_NAMES,
    analyze_unmatched,
    match_keyword_combos,
    split_clauses,
)


def labels(content: str) -> set[str]:
    return {combo.label for combo in match_keyword_combos(content)}


def test_단순_조합을_대상과_유형으로_만든다():
    assert labels("구조일반사항이 누락되었습니다.") == {"구조일반사항 누락"}
    assert labels("지반조사서 누락") == {"지반조사서 누락"}


def test_대상_두개가_불일치면_쌍으로_센다():
    result = labels("구조계산서와 구조도면 불일치")
    assert result == {"구조계산서↔구조도면 불일치"}
    # 개별 조합은 만들지 않는다 — 지적 내용은 두 대상의 관계 자체다.
    assert "구조계산서 불일치" not in result
    assert "구조도면 불일치" not in result


def test_절이_다르면_각각_조합된다():
    # 카테시안 곱이면 "구조도면 불일치", "구조계산서 누락"까지 생기지만
    # 절 단위로 끊으므로 실제 지적만 남는다.
    result = labels("구조계산서 값이 상이함\n구조도면에 부재 치수 누락")
    assert result == {"구조계산서 불일치", "구조도면 누락"}


def test_한_절에서_유형은_우선순위가_높은_하나만_쓴다():
    # "누락 → 추가 필요"는 같은 지적이므로 누락 하나로만 센다.
    assert labels("구조일반사항이 누락되었으므로 추가 필요") == {"구조일반사항 누락"}
    # 불일치가 누락보다 우선한다.
    assert labels("배근도와 값이 상이하고 일부 표기가 없음") == {"구조도면 불일치"}


def test_부재_보는_확보나_보완에_오탐되지_않는다():
    assert "보" not in {c.primary_target for c in match_keyword_combos("정착길이 미확보")}
    assert "보" not in {c.primary_target for c in match_keyword_combos("구조도면 보완 필요")}
    assert "보" in {c.primary_target for c in match_keyword_combos("전이보 스트럽 간격 보완할 것")}


def test_건축도면과_구조도면을_구분한다():
    assert labels("건축도면 작성자 미기입") == {
        "건축도면 누락",
        "작성자·날인 누락",
    }
    assert "구조도면 누락" not in labels("건축도면 작성자 미기입")


def test_같은_조합은_한_건으로_센다():
    result = match_keyword_combos("구조도면 누락\n구조도면 또 누락\n구조도면 누락")
    assert len(result) == 1


def test_미분류_사유를_구분한다():
    assert analyze_unmatched("적합") == "no_target_issue"
    assert analyze_unmatched("누락되었습니다") == "no_target"
    assert analyze_unmatched("구조계산서") == "no_issue"
    assert analyze_unmatched("") == "empty"
    assert analyze_unmatched("구조도면 누락") is None


def test_절_분할은_번호목록을_자르지_않는다():
    clauses = split_clauses("1. 기초 검토 필요. 2. 기둥 확인 바람")
    assert any("기초" in clause for clause in clauses)
    assert any("기둥" in clause for clause in clauses)


def test_사전_구성():
    assert len(TARGET_NAMES) == 18
    assert len(ISSUE_NAMES) == 7
    assert len(set(TARGET_NAMES)) == len(TARGET_NAMES)
    assert len(set(ISSUE_NAMES)) == len(ISSUE_NAMES)
