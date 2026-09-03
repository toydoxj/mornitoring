"""규칙 사전으로 분류되지 않은 검토의견을 LLM으로 보완 라벨링한다.

규칙(engines/review_keyword_analyzer.py)이 대상 또는 문제유형을 못 찾은 건만
대상으로 한다. 모델 출력은 신뢰 경계 밖이므로 Structured Outputs 의 닫힌 enum
으로 받고, 저장 직전에 한 번 더 화이트리스트로 검증한다.

외부 전송 최소화: 판정에 필요한 의견 원문과 분류(category)만 보낸다.
관리번호·검토위원 등 식별 정보는 보내지 않고, `store=False` 로 호출한다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from openai import OpenAI, OpenAIError

from config import settings
from engines.review_keyword_analyzer import ISSUE_NAMES, TARGET_NAMES
from models.opinion_label import NO_SECONDARY_TARGET

logger = logging.getLogger(__name__)

# 프롬프트·스키마를 바꾸면 services/opinion_labeling.LLM_CONTRACT_VERSION 도 함께 올린다.
SYSTEM_PROMPT = """너는 건축구조 검토서의 지적사항을 분류하는 도구다.

각 검토의견에 대해 "무엇에 대한 지적인가(대상)"와 "무엇이 잘못되었나(문제유형)"의
조합 라벨을 만든다. 아래 규칙을 지켜라.

1. 대상과 문제유형은 주어진 목록에서만 고른다. 목록에 없으면 라벨을 만들지 마라.
2. 의견 한 건에 지적이 여러 개면 라벨을 여러 개 만든다.
3. 두 도서 사이의 불일치(예: 구조계산서와 구조도면의 값이 다름)는 primary_target 과
   secondary_target 에 두 대상을 넣고 issue_type 을 "불일치"로 한다.
   그 외에는 secondary_target 을 빈 문자열로 둔다.
4. 실제로 지적하지 않은 조합을 만들지 마라. 대상 목록과 유형 목록을 임의로
   교차 조합하면 안 된다.
5. 분류할 수 없으면 labels 를 빈 배열로 둔다. 억지로 채우지 마라.
6. "적합", "해당없음"처럼 지적이 아닌 내용은 labels 를 빈 배열로 둔다."""


@dataclass(frozen=True)
class LabelResult:
    """LLM이 판정한 라벨 하나."""

    primary_target: str
    secondary_target: str
    issue_type: str


@dataclass
class BatchOutcome:
    """배치 1회 호출 결과."""

    labels_by_index: dict[int, list[LabelResult]]
    resolved_model: str
    input_tokens: int
    output_tokens: int


def is_enabled() -> bool:
    return bool(settings.openai_api_key)


def build_json_schema() -> dict:
    """닫힌 enum 기반 Structured Outputs 스키마."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["items"],
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["index", "labels"],
                    "properties": {
                        "index": {"type": "integer"},
                        "labels": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": [
                                    "primary_target",
                                    "secondary_target",
                                    "issue_type",
                                ],
                                "properties": {
                                    "primary_target": {"enum": list(TARGET_NAMES)},
                                    "secondary_target": {
                                        "enum": [NO_SECONDARY_TARGET, *TARGET_NAMES]
                                    },
                                    "issue_type": {"enum": list(ISSUE_NAMES)},
                                },
                            },
                        },
                    },
                },
            }
        },
    }


def build_user_message(items: list[tuple[int, str, str | None]]) -> str:
    """(index, content, category) 목록을 프롬프트 본문으로 만든다."""
    lines = [
        "대상 목록: " + ", ".join(TARGET_NAMES),
        "문제유형 목록: " + ", ".join(ISSUE_NAMES),
        "",
        "다음 검토의견을 분류하라.",
    ]
    limit = settings.opinion_label_max_content_chars
    for index, content, category in items:
        text = (content or "").strip()[:limit]
        lines.append(f"[{index}] (분류: {category or '미기재'}) {text}")
    return "\n".join(lines)


def _validate(raw_labels: list[dict]) -> list[LabelResult]:
    """모델 출력이 허용 목록 안에 있는지 다시 확인한다."""
    valid_targets = set(TARGET_NAMES)
    valid_issues = set(ISSUE_NAMES)
    results: list[LabelResult] = []
    seen: set[tuple[str, str, str]] = set()

    for item in raw_labels:
        if not isinstance(item, dict):
            continue
        primary = str(item.get("primary_target") or "")
        secondary = str(item.get("secondary_target") or NO_SECONDARY_TARGET)
        issue = str(item.get("issue_type") or "")
        if primary not in valid_targets or issue not in valid_issues:
            continue
        if secondary and secondary not in valid_targets:
            continue
        if secondary == primary:
            secondary = NO_SECONDARY_TARGET
        # 관계형 라벨은 불일치에만 허용한다.
        if secondary and issue != "불일치":
            secondary = NO_SECONDARY_TARGET
        # 쌍은 순서를 고정해 같은 관계가 두 방향으로 저장되지 않게 한다.
        if secondary and primary > secondary:
            primary, secondary = secondary, primary
        key = (primary, secondary, issue)
        if key in seen:
            continue
        seen.add(key)
        results.append(LabelResult(primary, secondary, issue))
    return results


def label_batch(items: list[tuple[int, str, str | None]]) -> BatchOutcome:
    """의견 묶음 하나를 LLM으로 분류한다.

    호출 실패는 OpenAIError 를 그대로 올려 호출한 쪽(워커)이 재시도를 판단한다.
    """
    if not is_enabled():
        raise RuntimeError("OPENAI_API_KEY 가 설정되지 않았습니다.")

    client = OpenAI(api_key=settings.openai_api_key)
    response = client.responses.create(
        model=settings.openai_model,
        instructions=SYSTEM_PROMPT,
        input=build_user_message(items),
        reasoning={"effort": settings.openai_reasoning_effort},
        max_output_tokens=settings.opinion_label_max_output_tokens,
        text={
            "format": {
                "type": "json_schema",
                "name": "opinion_labels",
                "strict": True,
                "schema": build_json_schema(),
            }
        },
        store=False,
    )

    text = (response.output_text or "").strip()
    if not text:
        raise OpenAIError("빈 응답을 받았습니다.")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OpenAIError(f"응답 JSON 파싱 실패: {exc}") from exc

    labels_by_index: dict[int, list[LabelResult]] = {}
    for entry in parsed.get("items") or []:
        if not isinstance(entry, dict):
            continue
        try:
            index = int(entry.get("index"))
        except (TypeError, ValueError):
            continue
        labels_by_index[index] = _validate(entry.get("labels") or [])

    usage = getattr(response, "usage", None)
    return BatchOutcome(
        labels_by_index=labels_by_index,
        resolved_model=getattr(response, "model", "") or settings.openai_model,
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
    )
