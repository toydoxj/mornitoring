"""검토서 상세내용 조합 키워드 분석 엔진.

단어 하나(예: "누락", "하중")만 세면 "무엇이 어떻게 잘못됐는지"를 알 수 없어
통계로서의 의미가 약하다. 그래서 상세의견 한 건을 절(clause) 단위로 쪼갠 뒤
`대상(무엇을) x 문제유형(무엇이 잘못)` 조합으로 라벨을 만든다.

    "구조일반사항이 누락되었습니다"        -> 구조일반사항 누락
    "구조계산서와 구조도면 불일치"          -> 구조계산서↔구조도면 불일치

같은 절 안에서 대상이 둘 이상이면서 문제유형이 '불일치'인 경우에는 두 대상의
관계 자체가 지적 내용이므로 개별 조합 대신 `A↔B 불일치` 쌍으로만 센다.

주의: 대상 목록과 유형 목록을 단순 카테시안 곱으로 조합하면
"계산서에는 있으나 도면에는 없음" 한 문장에서 실제로 지적하지 않은
'구조도면 누락' 같은 허위 조합이 생긴다. 그래서 절 분할 + 근접 판정으로
같은 맥락에 있는 것끼리만 묶는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 규칙 사전(정규식) 버전. 정규식만 고치면 이것만 올린다 — 규칙 라벨만 재계산된다.
RULESET_VERSION = "2026.09.03"

# 분류 체계(대상·유형 목록) 버전. 항목을 추가·삭제·개명하면 올린다.
# 규칙 라벨과 LLM 라벨 양쪽 모두 무효화 대상이므로 RULESET_VERSION과 분리한다.
TAXONOMY_VERSION = "2026.09.03"

# 절이 이 길이를 넘으면 한 문장 안이라도 대상과 유형이 서로 멀 수 있으므로
# 문자 거리로 한 번 더 거른다.
LONG_CLAUSE_LEN = 120
PROXIMITY_LEN = 45


@dataclass(frozen=True)
class TargetRule:
    """지적 대상(무엇에 대한 지적인가)."""

    name: str
    group: str
    pattern: str


@dataclass(frozen=True)
class IssueRule:
    """문제유형(무엇이 잘못되었나). priority가 작을수록 구체적이라 우선한다."""

    name: str
    priority: int
    pattern: str


@dataclass(frozen=True)
class KeywordCombo:
    """상세의견 한 건에서 뽑아낸 조합 라벨 한 개."""

    primary_target: str
    secondary_target: str | None
    issue: str

    @property
    def label(self) -> str:
        if self.secondary_target:
            return f"{self.primary_target}↔{self.secondary_target} {self.issue}"
        return f"{self.primary_target} {self.issue}"


# 대상 사전 18종.
# 한글은 정규식 \b가 동작하지 않으므로 단독 토큰은 (?<![가-힣])X(?![가-힣])로 잡는다.
# 예: "보"를 \b로 잡으면 "확보", "보완"에 오탐이 난다.
TARGET_RULES: tuple[TargetRule, ...] = (
    # --- 도서류 ---
    TargetRule(
        "구조계산서", "도서",
        r"구조\s*계산서|구조\s*설계서|(?<![가-힣])계산서|설계\s*근거\s*자료|구조\s*검토\s*(자료|결과|서)",
    ),
    TargetRule(
        "구조도면", "도서",
        r"구조\s*도면|구조\s*평면도|배근도|골조도|구조\s*상세도|(?<!건축)(?<!건축\s)(?<![가-힣])도면",
    ),
    TargetRule(
        "건축도면", "도서",
        r"건축\s*도면|건축\s*개요|건축\s*평면도|건축\s*도서|(실내)?\s*재료\s*마감표",
    ),
    TargetRule(
        "구조안전확인서", "도서",
        r"구조안전.{0,12}확인서|안전\s*확인서|내진설계\s*확인서|(?<![가-힣])확인서",
    ),
    TargetRule(
        "지반조사서", "도서",
        r"지반\s*조사\s*(보고서|서)?|시추\s*주상도|지내력|지반\s*분류",
    ),
    TargetRule("구조일반사항", "도서", r"구조\s*일반\s*사항"),
    TargetRule("부재일람표", "도서", r"일람표"),
    TargetRule(
        "주요상세", "도서",
        r"주요\s*상세|상세도|접합\s*상세|정착\s*상세|이음\s*상세|배근\s*상세|철근\s*상세|단면\s*상세",
    ),
    # --- 설계 요소 ---
    TargetRule("하중산정", "설계", r"하중"),
    TargetRule(
        "내진설계", "설계",
        r"내진|지진력\s*저항\s*시스템|횡력\s*(저항)?\s*시스템|비정형|밑면\s*전단력|고유\s*주기|응답\s*스펙트럼",
    ),
    TargetRule(
        "시공상세·시공계획", "설계",
        r"시공\s*(상세|계획|순서|단계|중|시)|가설\s*(계획|구조)|거푸집|동바리|양중|캠버|camber",
    ),
    # --- 부재별 ---
    TargetRule("기둥", "부재", r"기둥|(?<![가-힣])칼럼|column"),
    TargetRule(
        "보", "부재",
        r"전이보|철골보|합성보|큰보|작은보|거더|girder|(?<![가-힣])보(?![가-힣])",
    ),
    TargetRule("슬래브", "부재", r"슬래브|슬라브|slab|바닥판"),
    TargetRule("벽체", "부재", r"전단벽|내력벽|옹벽|벽체|(?<![가-힣])벽(?![가-힣])"),
    TargetRule("기초·파일", "부재", r"기초|파일|말뚝|매트\s*기초|footing|pile"),
    TargetRule("접합부", "부재", r"접합부|용접|볼트|이음부|정착부"),
    # --- 기타 ---
    TargetRule(
        "작성자·날인", "기타",
        r"날인|서명|작성자|책임구조기술자|건축사\s*(정보|날인|성명)|기명|면허|자격\s*(사항|증)",
    ),
)

# 문제유형 사전 7종. 한 절에서 여러 개가 걸리면 priority가 가장 작은 것 하나만 쓴다.
# "구조일반사항 누락 → 추가 필요"처럼 누락과 추가·보완제출이 함께 나오는 문장이 많아
# 전부 세면 같은 지적이 두 번 집계된다.
ISSUE_RULES: tuple[IssueRule, ...] = (
    IssueRule(
        "불일치", 1,
        r"불일치|상이|상의(?!하)|서로\s*다르|다르게|차이가|일치하지|맞지\s*않|정합\s*(성)?\s*(미|불)",
    ),
    IssueRule(
        "미확보", 2,
        r"미확보|부족|미달|확보.{0,6}(어려|않|못|불가)|만족하지|불만족|초과",
    ),
    IssueRule(
        "오류", 3,
        r"오류|잘못|틀림|틀렸|부적절|부적정|과소|과대|타당하지\s*않|타당성\s*(부족|없)",
    ),
    IssueRule(
        "근거미제시", 4,
        r"근거.{0,8}(없|미제시|미첨부|누락|불명|부재)|미제출|제출되지\s*않|확인\s*불가|자료\s*(가)?\s*없|출처\s*(불명|없)",
    ),
    IssueRule(
        "누락", 5,
        r"누락|빠져|빠짐|미기입|미표기|미작성|미반영|미적용|기재\s*(가)?\s*없|표기\s*(가)?\s*없|없습니다|없음",
    ),
    IssueRule(
        "재검토요망", 6,
        r"재검토|재\s*확인|재산정|검토\s*(요망|필요|바|하시|할\s*것)|확인\s*(요망|필요|바|하시|할\s*것)",
    ),
    IssueRule(
        "추가·보완제출", 7,
        r"추가|보완|수정|제출|기입|반영|작성.{0,4}(필요|바|할\s*것)",
    ),
)

TARGET_NAMES: tuple[str, ...] = tuple(rule.name for rule in TARGET_RULES)
ISSUE_NAMES: tuple[str, ...] = tuple(rule.name for rule in ISSUE_RULES)
TARGET_GROUPS: dict[str, str] = {rule.name: rule.group for rule in TARGET_RULES}

_TARGET_RES = tuple((rule, re.compile(rule.pattern, re.IGNORECASE)) for rule in TARGET_RULES)
_ISSUE_RES = tuple((rule, re.compile(rule.pattern, re.IGNORECASE)) for rule in ISSUE_RULES)

# 절 구분자: 줄바꿈, 세미콜론, 한글/닫는괄호 뒤의 마침표, 슬래시 구분.
# "1. 항목"처럼 번호 뒤 마침표는 자르지 않도록 숫자 뒤 마침표는 제외한다.
_CLAUSE_SPLIT_RE = re.compile(r"[\n;]+|(?<=[가-힣\)])\.\s+|\s+/\s+")

# 대상 간 '불일치' 관계로 묶을 수 있는 도서류. 부재끼리의 불일치는 의미가 약하다.
PAIRABLE_TARGETS = frozenset({
    "구조계산서", "구조도면", "건축도면", "구조안전확인서", "지반조사서", "부재일람표",
})


def split_clauses(content: str) -> list[str]:
    """상세의견 원문을 절 단위로 나눈다."""
    text = (content or "").strip()
    if not text:
        return []
    return [clause.strip() for clause in _CLAUSE_SPLIT_RE.split(text) if clause and clause.strip()]


def _match_targets(clause: str) -> list[tuple[str, int]]:
    """절에서 대상과 그 등장 위치를 찾는다."""
    found: list[tuple[str, int]] = []
    for rule, regex in _TARGET_RES:
        match = regex.search(clause)
        if match:
            found.append((rule.name, match.start()))
    return found


def _match_issue(clause: str) -> tuple[str, int] | None:
    """절에서 우선순위가 가장 높은 문제유형 하나와 그 위치를 찾는다."""
    best: tuple[int, str, int] | None = None
    for rule, regex in _ISSUE_RES:
        match = regex.search(clause)
        if match is None:
            continue
        candidate = (rule.priority, rule.name, match.start())
        if best is None or candidate[0] < best[0]:
            best = candidate
    if best is None:
        return None
    return best[1], best[2]


def match_keyword_combos(content: str) -> set[KeywordCombo]:
    """상세의견 한 건에서 조합 라벨 집합을 만든다.

    같은 조합이 한 건 안에서 여러 번 등장해도 1건으로 센다. 반복 표현보다
    "몇 개 의견에서 그 조합이 지적됐는가"가 통계로서 안정적이기 때문이다.
    """
    combos: set[KeywordCombo] = set()

    for clause in split_clauses(content):
        issue_hit = _match_issue(clause)
        if issue_hit is None:
            continue
        issue, issue_pos = issue_hit

        targets = _match_targets(clause)
        if not targets:
            continue

        # 절이 길면 대상과 유형이 실제로 같은 맥락인지 문자 거리로 한 번 더 거른다.
        if len(clause) > LONG_CLAUSE_LEN:
            targets = [
                (name, pos) for name, pos in targets
                if abs(pos - issue_pos) <= PROXIMITY_LEN
            ]
            if not targets:
                continue

        if issue == "불일치":
            pairable = sorted({name for name, _ in targets if name in PAIRABLE_TARGETS})
            if len(pairable) >= 2:
                # 두 대상 간의 관계가 지적 내용이므로 쌍으로만 센다.
                for i in range(len(pairable)):
                    for j in range(i + 1, len(pairable)):
                        combos.add(KeywordCombo(pairable[i], pairable[j], issue))
                continue

        for name, _ in targets:
            combos.add(KeywordCombo(name, None, issue))

    return combos


def analyze_unmatched(content: str) -> str | None:
    """조합이 하나도 안 나온 이유를 돌려준다(미분류 사유 집계용).

    'no_target' 대상 없음 / 'no_issue' 유형 없음 / 'no_link' 둘 다 있으나 연결 실패.
    조합이 하나라도 나오면 None.
    """
    clauses = split_clauses(content)
    if not clauses:
        return "empty"
    if match_keyword_combos(content):
        return None

    has_target = False
    has_issue = False
    for clause in clauses:
        if _match_targets(clause):
            has_target = True
        if _match_issue(clause) is not None:
            has_issue = True

    if not has_target and not has_issue:
        return "no_target_issue"
    if not has_target:
        return "no_target"
    if not has_issue:
        return "no_issue"
    return "no_link"
