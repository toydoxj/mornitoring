"""검토서 상세내용 키워드 분석 엔진."""

from __future__ import annotations

import re
from dataclasses import dataclass

from engines.review_opinion_parser import OpinionEntry


@dataclass(frozen=True)
class KeywordRule:
    keyword: str
    patterns: tuple[str, ...]


@dataclass
class KeywordCount:
    category: str
    severity: str
    keyword: str
    count: int


# 상세의견 본문에서 통계화할 기본 키워드 사전.
# 너무 넓은 단어는 노이즈가 커지므로 구조/도서/보완 사유 중심으로 둔다.
KEYWORD_RULES: tuple[KeywordRule, ...] = (
    KeywordRule("전이보", ("전이보",)),
    KeywordRule("전이구조", ("전이구조",)),
    KeywordRule("스트럽", ("스트럽", "stirrup")),
    KeywordRule("철근간격", ("철근\\s*간격",)),
    KeywordRule("철근상세", ("철근\\s*상세",)),
    KeywordRule("동결심도", ("동결\\s*심도",)),
    KeywordRule("단면상세", ("단면\\s*상세",)),
    KeywordRule("지반조사서", ("지반\\s*조사서",)),
    KeywordRule("구조계산서", ("구조\\s*계산서",)),
    KeywordRule("구조도면", ("구조\\s*도면",)),
    KeywordRule("건축도면", ("건축\\s*도면",)),
    KeywordRule("하중", ("하중",)),
    KeywordRule("풍하중", ("풍\\s*하중",)),
    KeywordRule("지진하중", ("지진\\s*하중",)),
    KeywordRule("내진", ("내진",)),
    KeywordRule("기초", ("기초",)),
    KeywordRule("슬래브", ("슬래브", "slab")),
    KeywordRule("보강", ("보강",)),
    KeywordRule("접합부", ("접합부",)),
    KeywordRule("누락", ("누락",)),
    KeywordRule("불일치", ("불일치",)),
    KeywordRule("오류", ("오류",)),
    KeywordRule("보완", ("보완",)),
    KeywordRule("재검토", ("재검토", "재\\s*검토")),
)


def analyze_opinion_keywords(entries: list[OpinionEntry]) -> list[KeywordCount]:
    """상세내용 원문만 대상으로 분류/심각도/키워드별 건수를 만든다.

    같은 상세의견 한 줄에서 같은 키워드가 여러 번 반복돼도 1건으로 센다.
    반복 표현보다 "몇 개 의견에서 그 키워드가 등장했는가"가 통계에 더 안정적이다.
    """
    counts: dict[tuple[str, str, str], int] = {}

    for entry in entries:
        matched_keywords = match_keywords(entry.content)
        for keyword in matched_keywords:
            key = (entry.section, entry.severity, keyword)
            counts[key] = counts.get(key, 0) + 1

    rows = [
        KeywordCount(
            category=category,
            severity=severity,
            keyword=keyword,
            count=count,
        )
        for (category, severity, keyword), count in counts.items()
    ]
    return sorted(rows, key=lambda row: (row.category, row.keyword, row.severity))


def match_keywords(content: str) -> set[str]:
    """상세내용 텍스트에서 사전 기반 키워드를 찾는다."""
    matched: set[str] = set()
    text = content.strip()
    if not text:
        return matched

    for rule in KEYWORD_RULES:
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in rule.patterns):
            matched.add(rule.keyword)
    return matched
