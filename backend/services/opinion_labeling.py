"""검토의견 조합 라벨 동기화 서비스.

규칙 사전으로 조합 라벨을 만들어 저장하고, 규칙만으로 분류되지 않은 건은
LLM 워커가 나중에 처리하도록 `OpinionLabelRun` 에 pending 으로 등록한다.

라벨 계산 자체는 `engines/review_keyword_analyzer.py` 가 담당하고,
이 모듈은 "언제 다시 계산해서 어떻게 저장할지"만 다룬다.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from engines.review_keyword_analyzer import (
    RULESET_VERSION,
    TAXONOMY_VERSION,
    analyze_unmatched,
    match_keyword_combos,
)
from models.opinion_label import (
    LABEL_SOURCE_RULE,
    NO_ASPECT,
    NO_SECONDARY_TARGET,
    RUN_STATUS_PENDING,
    OpinionCombinationLabel,
    OpinionLabelRun,
)
from models.review_opinion_detail import ReviewOpinionDetail

# LLM 프롬프트·응답 스키마 계약 버전. 프롬프트나 출력 스키마를 바꾸면 올린다.
LLM_CONTRACT_VERSION = "3"


def compute_input_hash(
    *,
    content: str,
    category: str | None,
    unmatched_reason: str | None,
) -> str:
    """LLM 입력 전체를 해싱한다.

    원문만 해싱하면 분류체계나 프롬프트 계약이 바뀌어도 캐시가 갱신되지 않는다.
    실제 판단에 들어가는 값을 모두 포함해야 해당 건만 자동으로 무효화된다.
    """
    payload = {
        "content": content,
        "category": category or "",
        "unmatched_reason": unmatched_reason or "",
        "taxonomy_version": TAXONOMY_VERSION,
        "contract_version": LLM_CONTRACT_VERSION,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _label_rows_for(detail: ReviewOpinionDetail) -> list[dict]:
    """상세의견 한 건의 규칙 라벨을 INSERT 용 dict 목록으로 만든다."""
    combos = match_keyword_combos(detail.content or "", detail.category)
    return [
        {
            "detail_id": detail.id,
            "primary_target": combo.primary_target,
            "secondary_target": combo.secondary_target or NO_SECONDARY_TARGET,
            "aspect": combo.aspect or NO_ASPECT,
            "issue_type": combo.issue,
            "source": LABEL_SOURCE_RULE,
            "ruleset_version": RULESET_VERSION,
            "taxonomy_version": TAXONOMY_VERSION,
        }
        for combo in combos
    ]


def sync_rule_labels(
    db: Session,
    details: Iterable[ReviewOpinionDetail],
) -> dict[str, int]:
    """상세의견들의 규칙 라벨을 다시 계산해 저장한다.

    - 기존 규칙 라벨은 지우고 새로 넣는다(LLM·수기 라벨은 건드리지 않는다).
    - 규칙으로 조합이 안 나오면 LLM 처리 대기(run pending)로 등록한다.

    커밋은 호출한 쪽에서 한다. 업로드 트랜잭션 안에서 함께 쓰기 위함이다.
    """
    result = {"details": 0, "labeled_details": 0, "labels": 0, "pending_runs": 0}

    details = list(details)
    if not details:
        return result

    detail_ids = [detail.id for detail in details if detail.id is not None]
    # LLM·수기 라벨이 이미 붙은 의견은 규칙이 여전히 못 풀어도 다시 LLM에 보내지 않는다.
    # 사전을 고칠 때마다 전량 재호출되는 것을 막기 위함이다. 이 건들을 다시 분류하려면
    # 해당 라벨을 지우면 된다(그러면 라벨이 없어져 pending 으로 다시 등록된다).
    # LLM·수기 라벨이 붙은 의견은 그 라벨을 그대로 둔다.
    # 규칙 라벨을 덧붙이면 같은 지적이 두 조합으로 세지고, 규칙으로 덮으면
    # 문맥을 읽어 붙인 결과를 버리게 된다. 둘 중 사람·모델이 판단한 쪽을 남긴다.
    # 이 건들을 규칙으로 다시 분류하려면 해당 라벨을 지우면 된다.
    externally_labeled: set[int] = set()
    if detail_ids:
        externally_labeled = {
            row[0]
            for row in db.execute(
                select(OpinionCombinationLabel.detail_id).where(
                    OpinionCombinationLabel.detail_id.in_(detail_ids),
                    OpinionCombinationLabel.source != LABEL_SOURCE_RULE,
                )
            ).all()
        }
        db.query(OpinionCombinationLabel).filter(
            OpinionCombinationLabel.detail_id.in_(detail_ids),
            OpinionCombinationLabel.source == LABEL_SOURCE_RULE,
        ).delete(synchronize_session=False)

    new_labels: list[dict] = []
    for detail in details:
        if detail.id is None:
            continue
        result["details"] += 1
        if detail.id in externally_labeled:
            result["labeled_details"] += 1
            continue

        rows = _label_rows_for(detail)
        if rows:
            new_labels.extend(rows)
            result["labeled_details"] += 1
            continue

        reason = analyze_unmatched(detail.content or "", detail.category)
        if reason in (None, "empty"):
            # 빈 내용은 라벨링 대상이 아니다.
            continue
        if _register_pending_run(db, detail, reason):
            result["pending_runs"] += 1

    if new_labels:
        db.bulk_insert_mappings(OpinionCombinationLabel, new_labels)
        result["labels"] = len(new_labels)

    return result


def _register_pending_run(
    db: Session,
    detail: ReviewOpinionDetail,
    unmatched_reason: str,
) -> bool:
    """LLM 처리 대기 작업을 등록한다. 같은 입력이 이미 있으면 등록하지 않는다."""
    input_hash = compute_input_hash(
        content=detail.content or "",
        category=detail.category,
        unmatched_reason=unmatched_reason,
    )
    existing = db.execute(
        select(OpinionLabelRun.id).where(
            OpinionLabelRun.detail_id == detail.id,
            OpinionLabelRun.input_hash == input_hash,
        )
    ).first()
    if existing is not None:
        return False

    db.add(OpinionLabelRun(
        detail_id=detail.id,
        input_hash=input_hash,
        ruleset_version=RULESET_VERSION,
        taxonomy_version=TAXONOMY_VERSION,
        llm_contract_version=LLM_CONTRACT_VERSION,
        status=RUN_STATUS_PENDING,
        unmatched_reason=unmatched_reason,
    ))
    return True


def sync_rule_labels_for_stage(db: Session, stage_id: int) -> dict[str, int]:
    """검토 단계 하나에 속한 상세의견 전체의 규칙 라벨을 다시 계산한다."""
    details: Sequence[ReviewOpinionDetail] = db.execute(
        select(ReviewOpinionDetail).where(ReviewOpinionDetail.stage_id == stage_id)
    ).scalars().all()
    return sync_rule_labels(db, details)
