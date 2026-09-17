"""표현 품질 규칙 엔진 회귀 테스트.

성능을 위해 패턴을 미리 컴파일하고 선검사로 건너뛰도록 바꿨으므로,
규칙마다 re.search 를 부르던 원래 방식과 결과가 같은지 확인한다.
"""

import re

import pytest

from engines.opinion_quality_analyzer import (
    OPINION_QUALITY_RULES,
    OpinionQualityMatch,
    match_opinion_quality,
)


def _reference_match(content: str) -> list[OpinionQualityMatch]:
    """최적화 전 구현 (규칙·패턴마다 re.search)."""
    text = content.strip()
    if not text:
        return []
    matched = {}
    for rule in OPINION_QUALITY_RULES:
        if any(re.search(p, text, flags=re.IGNORECASE) for p in rule.patterns):
            matched[(rule.tag, rule.term)] = OpinionQualityMatch(
                category=rule.category,
                tag=rule.tag,
                level=rule.level,
                term=rule.term,
                issue=rule.issue,
                replacement=rule.replacement,
            )
    return sorted(matched.values(), key=lambda m: (m.category, m.tag, m.term))


SAMPLES = [
    "",
    "   ",
    "적합",
    "기초자료 미제출로 1차(예비)검토 미실시",
    "[하중 적정성] 1. 조적하중 추가 필요(화장실), 구조계산서",
    "철근 정착길이가 부족하여 보완 필요",
    "설계 오류로 판단되며 명백히 오류임",
    "이건 말이 안 되는 엉터리 설계, 너무 부실함",
    "설계자가 잘못 적용하였고 고의로 빠뜨린 것으로 보임",
    "그냥 적용한 듯하며 확인 안 한 듯함. 왜 이렇게 했는지 모르겠음",
    "구조적으로 위험하고 시공 불가, 절대 불가, 무조건 부적합",
    "과소 산정 및 과대 설계, 과도한 하중",
    "이상합니다. 애매하고 불합리한 부분이 많음",
    "하자 발생 시 책임 있음",
    "전혀 맞지 않음 / 전혀 불가능 / 완전히 틀림 / 심각하게 잘못됨",
    "검토가 안 되어 있음, 검토 없이 적용함, 무시하고 방치함",
    "매우 상당히 심히 극히 도저히",
    "ABC 영문 본문 only",
    "안 됩니다. 안 맞음. 좀 부족함. 많이 부족함. 대충 산정",
]


@pytest.mark.parametrize("content", SAMPLES)
def test_matches_reference_implementation(content):
    assert match_opinion_quality(content) == _reference_match(content)


def test_every_rule_pattern_still_detected():
    """규칙의 모든 패턴이 개별적으로도 여전히 잡힌다."""
    for rule in OPINION_QUALITY_RULES:
        for pattern in rule.patterns:
            # 정규식 패턴을 사람이 쓰는 문장으로 바꿔 넣는다 (\s* → 공백, \w* → 가)
            sample = re.sub(r"\\s\*", " ", pattern)
            sample = re.sub(r"\\w\*", "가", sample)
            sample = f"본문 {sample} 확인"
            result = match_opinion_quality(sample)
            assert result == _reference_match(sample)
            assert any(m.term == rule.term for m in result), (rule.term, pattern)


def test_rule_patterns_are_safe_to_combine():
    """패턴을 이어 붙여도 의미가 바뀌지 않는 형태인지 검사한다.

    캡처 그룹·역참조가 있으면 묶었을 때 그룹 번호가 어긋나고,
    전역 인라인 플래그는 (?:...) 로 감싸면 컴파일되지 않는다.
    """
    for rule in OPINION_QUALITY_RULES:
        assert rule.patterns, f"빈 패턴 목록: {rule.term}"
        for pattern in rule.patterns:
            assert pattern, f"빈 패턴: {rule.term}"
            compiled = re.compile(f"(?:{pattern})")
            assert compiled.groups == 0, f"캡처 그룹 금지 ((?:...) 사용): {rule.term} {pattern}"


def test_clean_text_returns_empty():
    assert match_opinion_quality("철근 배근 상세 확인 바랍니다.") == []
