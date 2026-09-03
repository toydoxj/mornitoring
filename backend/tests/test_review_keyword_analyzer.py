"""조합 키워드 분석 엔진 테스트."""

from engines.review_keyword_analyzer import (
    ASPECT_NAMES,
    ISSUE_NAMES,
    TARGET_NAMES,
    KeywordCombo,
    analyze_unmatched,
    category_target_hint,
    match_keyword_combos,
    split_clauses,
)


def labels(content: str) -> set[str]:
    return {combo.label for combo in match_keyword_combos(content)}


def labels_with(content: str, category: str) -> set[str]:
    return {combo.label for combo in match_keyword_combos(content, category)}


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
    assert result == {"구조계산서 불일치", "구조도면 > 수량·치수 누락"}


def test_한_절에서_유형은_우선순위가_높은_하나만_쓴다():
    # "누락 → 추가 필요"는 같은 지적이므로 누락 하나로만 센다.
    assert labels("구조일반사항이 누락되었으므로 추가 필요") == {"구조일반사항 누락"}
    # 불일치가 누락보다 우선한다.
    assert labels("배근도와 값이 상이하고 일부 표기가 없음") == {
        "구조도면 > 배근·상세 불일치"
    }


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


def test_하중은_종류별로_세분되고_상위는_빠진다():
    # 종류를 알 수 있으면 종류별로 센다.
    assert labels("지상1층 사하중 및 활하중이 누락되어 있음") == {
        "고정하중 누락",
        "활하중 누락",
    }
    assert labels("경사지붕에 대한 적설하중이 누락되었습니다") == {"설하중 누락"}
    assert labels("풍하중 산정 근거 미제시") == {"풍하중 근거미제시"}
    assert labels("지진하중 검토 필요") == {"지진하중 재검토요망"}
    # 상위 항목은 함께 세지 않는다.
    assert "하중산정 누락" not in labels("적설하중 누락")
    # 종류를 특정할 수 없으면 상위 항목에 남는다.
    assert labels("하중 산정 근거 확인 필요") == {"하중산정 재검토요망"}


def test_내진설계와_지진하중을_구분한다():
    assert labels("내진등급 최신화 수정 요망") == {"내진설계 > 내진등급 추가·보완제출"}
    assert "내진설계 재검토요망" not in labels("밑면전단력 재산정 필요")


def test_세부항목이_붙어_무엇을_지적했는지_드러난다():
    # 대상·유형만으로는 "무엇을 재검토하라는지" 알 수 없던 것이 드러난다.
    assert labels("지진력저항시스템에 대한 재검토가 필요합니다") == {
        "내진설계 > 저항시스템 재검토요망"
    }
    assert labels("구조계산서와 구조도면의 배근 상이") == {
        "구조계산서↔구조도면 > 배근·상세 불일치"
    }
    # 세부 국면이 문장에 없으면 붙이지 않는다.
    assert labels("구조일반사항이 누락되었습니다") == {"구조일반사항 누락"}


def test_대상과_같은_뜻인_세부항목은_붙이지_않는다():
    # "접합부 > 접합·정착"은 같은 말을 두 번 쓰는 라벨이다.
    assert "접합부 > 접합·정착 누락" not in labels("철골 접합부 상세 누락")
    assert "접합부 누락" in labels("철골 접합부 상세 누락")


def test_하중_종류가_더_세분된다():
    assert labels("크레인 하중 조합 누락") == {"크레인하중 누락", "하중조합 누락"}
    assert labels("편토압에 대한 하중 검토가 누락됐습니다") == {"토압·수압 누락"}
    assert labels("지붕층 하중 중 각파이프 하중 누락") == {"고정하중 누락"}
    # "시설 하중"이 설하중으로 오탐되지 않아야 한다.
    assert "설하중 누락" not in labels("제2종 근린생활시설 하중이 누락됨")


def test_검토서_분류를_대상_폴백으로_쓴다():
    # 본문에 대상이 없어도 검토서 분류 열이 무엇에 대한 지적인지 말해 준다.
    assert match_keyword_combos("추가바람", "구조도면 작성의 적정성 - 구조일반사항") == {
        KeywordCombo("구조일반사항", None, "추가·보완제출", None)
    }
    assert labels_with("산정 근거가 누락되었습니다", "하중의 적정성 - 풍하중") == {
        "풍하중 근거미제시"
    }
    # 본문에 대상이 있으면 본문이 우선이다.
    assert labels_with("구조도면에 부재 치수 누락", "하중의 적정성 - 풍하중") == {
        "구조도면 > 수량·치수 누락"
    }
    # 모르는 분류는 힌트를 주지 않는다.
    assert category_target_hint("기타의견") is None
    assert category_target_hint(None) is None
    assert labels_with("추가바람", "기타의견") == set()


def test_부재를_특정할_수_없으면_상위_부재설계로_남는다():
    assert labels_with("응력 검토 재확인 요망", "부재설계의 적정성 - 구조설계 요소") == {
        "부재설계 > 단면·응력 재검토요망"
    }
    # 부재가 드러나면 그 부재로 센다.
    assert "부재설계 누락" not in labels("슬래브 배근 누락")


def test_사전_구성():
    assert len(TARGET_NAMES) == 27
    assert len(ISSUE_NAMES) == 7
    assert len(ASPECT_NAMES) == 11
    assert len(set(ASPECT_NAMES)) == len(ASPECT_NAMES)
    assert len(set(TARGET_NAMES)) == len(TARGET_NAMES)
    assert len(set(ISSUE_NAMES)) == len(ISSUE_NAMES)
