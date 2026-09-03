"""검토서 상세내용 조합 키워드 분석 엔진.

단어 하나(예: "누락", "하중")만 세면 "무엇이 어떻게 잘못됐는지"를 알 수 없어
통계로서의 의미가 약하다. 그래서 상세의견 한 건을 절(clause) 단위로 쪼갠 뒤
`대상(무엇을) x 세부항목(어느 국면이) x 문제유형(무엇이 잘못)` 조합으로
라벨을 만든다. 세부항목은 잡히지 않으면 비워 둔다.

    "구조일반사항이 누락되었습니다"        -> 구조일반사항 누락
    "구조계산서와 구조도면 불일치"          -> 구조계산서↔구조도면 불일치
    "지진력저항시스템 재검토가 필요합니다"   -> 내진설계 > 저항시스템 재검토요망

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
RULESET_VERSION = "2026.09.03d"

# 분류 체계(대상·유형 목록) 버전. 항목을 추가·삭제·개명하면 올린다.
# 규칙 라벨과 LLM 라벨 양쪽 모두 무효화 대상이므로 RULESET_VERSION과 분리한다.
TAXONOMY_VERSION = "2026.09.03d"

# 절이 이 길이를 넘으면 한 문장 안이라도 대상과 유형이 서로 멀 수 있으므로
# 문자 거리로 한 번 더 거른다.
LONG_CLAUSE_LEN = 120
PROXIMITY_LEN = 45


@dataclass(frozen=True)
class TargetRule:
    """지적 대상(무엇에 대한 지적인가).

    parent 가 있으면 그 대상의 하위 항목이다. 하위가 잡히면 상위는 빼서
    "풍하중 누락"과 "하중산정 누락"이 같이 세지지 않게 한다.
    """

    name: str
    group: str
    pattern: str
    parent: str | None = None


@dataclass(frozen=True)
class IssueRule:
    """문제유형(무엇이 잘못되었나). priority가 작을수록 구체적이라 우선한다."""

    name: str
    priority: int
    pattern: str


@dataclass(frozen=True)
class AspectRule:
    """세부항목(대상의 어느 국면이 문제인가).

    대상과 유형만으로는 "내진설계 재검토요망"처럼 무엇을 다시 보라는 것인지
    알 수 없다. 세부항목이 그 빈자리를 채운다.
    """

    name: str
    pattern: str


@dataclass(frozen=True)
class KeywordCombo:
    """상세의견 한 건에서 뽑아낸 조합 라벨 한 개."""

    primary_target: str
    secondary_target: str | None
    issue: str
    aspect: str | None = None

    @property
    def label(self) -> str:
        head = (
            f"{self.primary_target}↔{self.secondary_target}"
            if self.secondary_target
            else self.primary_target
        )
        if self.aspect:
            return f"{head} > {self.aspect} {self.issue}"
        return f"{head} {self.issue}"


# 대상 사전 27종(하중 8종·부재 7종 세분 포함).
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
    # 하중은 종류를 알 수 있으면 종류별로 센다. 종류를 특정할 수 없는 지적만
    # 상위 항목인 "하중산정"에 남는다.
    TargetRule(
        "고정하중", "하중",
        r"고정\s*하중|사\s*하중|자중|마감\s*하중|각파이프|외장\s*하중|커튼월|파라펫|조적\s*하중"
        r"|설비\s*하중|장비\s*하중|덕트|태양광|(?<![가-힣])PV(?![A-Za-z])",
        parent="하중산정",
    ),
    TargetRule(
        "활하중", "하중",
        r"활\s*하중|적재\s*하중|사용\s*하중|근린생활|계단실\s*하중|주차\s*하중|피난\s*하중"
        r"|발코니\s*하중|용도별\s*하중",
        parent="하중산정",
    ),
    TargetRule("풍하중", "하중", r"풍\s*하중|풍압|기본\s*풍속|풍\s*변위|내풍", parent="하중산정"),
    # "시설 하중", "가설 하중"처럼 앞 글자가 붙은 말에 걸리지 않도록 경계를 준다.
    TargetRule(
        "설하중", "하중",
        r"적설\s*하중|적설|눈\s*하중|(?<![가-힣])설\s*하중", parent="하중산정",
    ),
    TargetRule(
        "지진하중", "하중",
        r"지진\s*하중|지진력(?!\s*저항)|밑면\s*전단력|응답\s*스펙트럼|등가정적|특별\s*지진\s*하중|층간\s*변위",
        parent="하중산정",
    ),
    TargetRule(
        "크레인하중", "하중",
        r"크레인|호이스트|호이스크|천정\s*주행|천장\s*주행", parent="하중산정",
    ),
    TargetRule(
        "토압·수압", "하중",
        r"토압|수압|지하\s*수위|부력|측압", parent="하중산정",
    ),
    TargetRule(
        "하중조합", "하중",
        r"하중\s*조합|조합\s*하중|load\s*combination", parent="하중산정",
    ),
    TargetRule("하중산정", "설계", r"하중"),
    TargetRule(
        "내진설계", "설계",
        r"내진|지진력\s*저항\s*시스템|횡력\s*(저항)?\s*시스템|비정형|고유\s*주기|내진\s*등급|내진\s*상세",
    ),
    TargetRule(
        "시공상세·시공계획", "설계",
        r"시공\s*(상세|계획|순서|단계|중|시)|가설\s*(계획|구조)|거푸집|동바리|양중|캠버|camber",
    ),
    # --- 부재별 ---
    # 부재를 특정할 수 없는 지적은 상위 항목인 "부재설계"에 남는다.
    TargetRule("기둥", "부재", r"기둥|(?<![가-힣])칼럼|column", parent="부재설계"),
    TargetRule(
        "보", "부재",
        r"전이보|철골보|합성보|큰보|작은보|거더|girder|(?<![가-힣])보(?![가-힣])",
        parent="부재설계",
    ),
    TargetRule("슬래브", "부재", r"슬래브|슬라브|slab|바닥판", parent="부재설계"),
    TargetRule(
        "벽체", "부재",
        r"전단벽|내력벽|옹벽|벽체|(?<![가-힣])벽(?![가-힣])", parent="부재설계",
    ),
    TargetRule(
        "기초·파일", "부재",
        r"기초|파일|말뚝|매트\s*기초|footing|pile", parent="부재설계",
    ),
    TargetRule("접합부", "부재", r"접합부|용접|볼트|이음부|정착부", parent="부재설계"),
    TargetRule("부재설계", "부재", r"부재\s*(설계|검토|성능)|부재의"),
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
        r"재검토|재\s*확인|재산정|재계산|재작성|재제출"
        r"|검토\s*(요망|요함|필요|바|하시|할\s*것)"
        r"|확인\s*(요망|요함|필요|바|하시|할\s*것)"
        # "…입력 확인", "…적용확인"처럼 문장 끝에서 확인만 요구하는 표현.
        r"|확인(?=$|[\s.,)])",
    ),
    # 마지막 폴백. 앞의 어느 유형에도 안 걸리지만 무언가를 요구하는 문장은
    # 대개 보완 요구다. 지적 대상은 있는데 유형만 못 찾는 건이 많아서 둔다.
    IssueRule(
        "추가·보완제출", 7,
        r"추가|보완|수정|정정|제출|첨부|기입|표기|명기|반영|제시|적용|명확히|표현"
        r"|작성.{0,4}(필요|바|할\s*것)"
        r"|(필요함?|바랍니다|바람|요망|요함|할\s*것|하시기\s*바|해\s*주시|주시기\s*바)",
    ),
)

# 세부항목 사전 11종. 대상의 어느 국면을 지적했는지 나타낸다.
# 어느 것도 잡히지 않으면 세부항목 없이 대상 x 유형 조합만 만든다.
# 하중조합은 대상(하중산정 하위)으로 두었으므로 여기에는 넣지 않는다.
ASPECT_RULES: tuple[AspectRule, ...] = (
    AspectRule(
        "저항시스템",
        r"지진력\s*저항\s*시스템|횡력\s*(저항)?\s*시스템|반응\s*수정\s*계수|골조\s*형식"
        r"|모멘트\s*골조|전단벽\s*시스템|내력벽\s*시스템|역추형",
    ),
    AspectRule(
        "지반분류",
        r"지반\s*분류|지반\s*증폭|지반\s*등급|탄성파|(?<![A-Za-z])S[1-6](?![0-9])"
        r"|(?<![A-Za-z])F[av](?![A-Za-z])",
    ),
    AspectRule("내진등급", r"내진\s*등급|중요도\s*계수|중요도\s*(가|를|는)?|위험물|특\s*등급"),
    AspectRule(
        "모델링·해석",
        r"모델링|해석\s*(법|결과|모델|근거)|다이[어아]프램|질량\s*참여|모드|강성|경계\s*조건"
        r"|등가정적|동적\s*해석|입력\s*(자료|데이터)|input|하중\s*(분포도|입력)",
    ),
    AspectRule(
        "단면·응력",
        r"응력|단면\s*(성능|검토|산정|부족)?|부재력|안전율|좌굴|세장비|비지지\s*길이|횡지지\s*길이"
        r"|(?<![A-Za-z])SRF(?![A-Za-z])|내력\s*(부족|검토)",
    ),
    AspectRule(
        "배근·상세",
        r"배근|철근\s*(량|비|간격|배치|상세)?|스터럽|스트럽|후프|띠철근|피복|정착\s*길이|이음\s*길이",
    ),
    AspectRule("처짐·변위", r"처짐|캠버|camber|층간\s*변위|변위\s*(제한|검토)?|deflection"),
    AspectRule("접합·정착", r"접합\s*(부|상세|검토)|용접|볼트|앵커|이음\s*부"),
    AspectRule(
        "재료·강도",
        r"콘크리트\s*강도|설계\s*강도|(?<![A-Za-z])fck|재질|강재\s*(종류|재질)"
        r"|(?<![A-Za-z])(SS275|SM355|SM275|SHN|SD400|SD500)|내구성",
    ),
    AspectRule(
        "시공하중",
        r"시공\s*(중|시)?\s*하중|작업\s*하중|가설\s*하중|동바리|거푸집",
    ),
    AspectRule("수량·치수", r"치수|길이|두께|간격\s*(이|을|은)?|규격|수량|스팬|춤(?![가-힣])"),
)

TARGET_NAMES: tuple[str, ...] = tuple(rule.name for rule in TARGET_RULES)
ASPECT_NAMES: tuple[str, ...] = tuple(rule.name for rule in ASPECT_RULES)
# 하위 대상 -> 상위 대상. 하위가 잡히면 상위를 뺀다.
TARGET_PARENTS: dict[str, str] = {
    rule.name: rule.parent for rule in TARGET_RULES if rule.parent
}
ISSUE_NAMES: tuple[str, ...] = tuple(rule.name for rule in ISSUE_RULES)
TARGET_GROUPS: dict[str, str] = {rule.name: rule.group for rule in TARGET_RULES}

_TARGET_RES = tuple((rule, re.compile(rule.pattern, re.IGNORECASE)) for rule in TARGET_RULES)
_ASPECT_RES = tuple((rule, re.compile(rule.pattern, re.IGNORECASE)) for rule in ASPECT_RULES)
_ISSUE_RES = tuple((rule, re.compile(rule.pattern, re.IGNORECASE)) for rule in ISSUE_RULES)

# 절 구분자: 줄바꿈, 세미콜론, 한글/닫는괄호 뒤의 마침표, 슬래시 구분.
# "1. 항목"처럼 번호 뒤 마침표는 자르지 않도록 숫자 뒤 마침표는 제외한다.
_CLAUSE_SPLIT_RE = re.compile(r"[\n;]+|(?<=[가-힣\)])\.\s+|\s+/\s+")

# 검토서 원본 분류(category) -> 대상 힌트.
# 상세의견 본문에 대상이 안 적혀 있어도 검토서의 분류 열이 무엇에 대한 지적인지
# 이미 말해 준다. 본문에서 대상을 못 찾은 절에만 폴백으로 쓴다.
# 키는 category 에서 공백을 지운 문자열로 맞춘다(표기 흔들림 흡수).
CATEGORY_TARGET_HINTS: dict[str, str] = {
    # 하중
    "하중의적정성-고정하중": "고정하중",
    "하중의적정성-활하중": "활하중",
    "하중의적정성-풍하중": "풍하중",
    "하중의적정성-설하중": "설하중",
    "하중의적정성-지진하중": "지진하중",
    "하중의적정성-토압및수압": "토압·수압",
    "하중의적정성-기타": "하중산정",
    "하중적정성": "하중산정",
    # 구조도면
    "구조도면작성의적정성-구조일반사항": "구조일반사항",
    "구조도면작성의적정성-작성자기입": "작성자·날인",
    "구조도면작성의적정성-구조평면도": "구조도면",
    "구조도면작성의적정성-주요상세": "주요상세",
    "구조도면작성의적정성-부재일람표": "부재일람표",
    "구조도면작성의적정성-도면완성도": "구조도면",
    "구조도면작성의적정성-기타": "구조도면",
    "구조도면작성적정성": "구조도면",
    # 확인서
    "구조안전및내진설계확인서-내진설계": "내진설계",
    "구조안전및내진설계확인서-내풍설계": "풍하중",
    "구조안전및내진설계확인서-일반사항": "구조안전확인서",
    "구조안전및내진설계확인서-기타": "구조안전확인서",
    "구조안전및내진설계확인서": "구조안전확인서",
    # 부재설계
    "부재설계의적정성-구조설계요소": "부재설계",
    "부재설계의적정성-기타": "부재설계",
    "부재설계의적정성-내진설계대상": "내진설계",
    "부재설계적정성": "부재설계",
    "부재설계적정성-기타": "부재설계",
}


def category_target_hint(category: str | None) -> str | None:
    """검토서 분류에서 대상 힌트를 얻는다. 모르는 분류면 None."""
    if not category:
        return None
    key = re.sub(r"\s+", "", category)
    return CATEGORY_TARGET_HINTS.get(key)


# 대상 자체가 그 세부항목을 뜻하는 경우. "접합부 > 접합·정착"처럼 같은 말을
# 두 번 쓰는 라벨이 되므로 세부항목을 비운다.
REDUNDANT_ASPECTS: dict[str, frozenset[str]] = {
    "접합부": frozenset({"접합·정착"}),
    "하중조합": frozenset({"모델링·해석"}),
    "부재일람표": frozenset({"수량·치수"}),
}

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
    """절에서 대상과 그 등장 위치를 찾는다.

    하위 대상(예: 풍하중)이 잡히면 그 상위(하중산정)는 뺀다. 둘 다 두면
    같은 지적이 "풍하중 누락"과 "하중산정 누락" 두 건으로 세진다.
    """
    found: list[tuple[str, int]] = []
    for rule, regex in _TARGET_RES:
        match = regex.search(clause)
        if match:
            found.append((rule.name, match.start()))

    matched_parents = {
        TARGET_PARENTS[name] for name, _ in found if name in TARGET_PARENTS
    }
    if matched_parents:
        found = [(name, pos) for name, pos in found if name not in matched_parents]
    return found


def _match_aspect(clause: str, target_pos: int) -> str | None:
    """절에서 세부항목을 찾는다. 여러 개면 대상에 가장 가까운 것을 쓴다.

    한 절에 세부항목이 여럿 걸리는 문장이 많은데, 전부 쓰면 같은 지적이
    세부항목 수만큼 불어난다. 대상과 가장 가까운 하나만 남긴다.
    """
    best: tuple[int, str] | None = None
    for rule, regex in _ASPECT_RES:
        match = regex.search(clause)
        if match is None:
            continue
        distance = abs(match.start() - target_pos)
        if best is None or distance < best[0]:
            best = (distance, rule.name)
    return best[1] if best else None


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


def match_keyword_combos(
    content: str,
    category: str | None = None,
) -> set[KeywordCombo]:
    """상세의견 한 건에서 조합 라벨 집합을 만든다.

    같은 조합이 한 건 안에서 여러 번 등장해도 1건으로 센다. 반복 표현보다
    "몇 개 의견에서 그 조합이 지적됐는가"가 통계로서 안정적이기 때문이다.

    본문에 대상이 안 적힌 절은 검토서 분류(category)를 폴백으로 쓴다.
    "구조일반사항 추가바람"처럼 짧은 지적은 본문만으로 대상을 알 수 없지만
    분류 열이 이미 무엇에 대한 검토인지 말해 준다.
    """
    combos: set[KeywordCombo] = set()
    hint = category_target_hint(category)

    for clause in split_clauses(content):
        issue_hit = _match_issue(clause)
        if issue_hit is None:
            continue
        issue, issue_pos = issue_hit

        targets = _match_targets(clause)
        if not targets and hint:
            # 분류에서 온 대상은 절 안에 위치가 없으므로 유형 위치를 기준으로 둔다.
            targets = [(hint, issue_pos)]
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
                # 무엇이 서로 다른지는 세부항목으로 남긴다.
                pair_aspect = _match_aspect(clause, issue_pos)
                for i in range(len(pairable)):
                    for j in range(i + 1, len(pairable)):
                        combos.add(
                            KeywordCombo(pairable[i], pairable[j], issue, pair_aspect)
                        )
                continue

        for name, pos in targets:
            aspect = _match_aspect(clause, pos)
            if aspect and aspect in REDUNDANT_ASPECTS.get(name, frozenset()):
                aspect = None
            combos.add(KeywordCombo(name, None, issue, aspect))

    return combos


def analyze_unmatched(content: str, category: str | None = None) -> str | None:
    """조합이 하나도 안 나온 이유를 돌려준다(미분류 사유 집계용).

    'no_target' 대상 없음 / 'no_issue' 유형 없음 / 'no_link' 둘 다 있으나 연결 실패.
    조합이 하나라도 나오면 None.
    """
    clauses = split_clauses(content)
    if not clauses:
        return "empty"
    if match_keyword_combos(content, category):
        return None

    has_target = category_target_hint(category) is not None
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
