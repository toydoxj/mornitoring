"""규칙으로 분류되지 않은 검토의견을 LLM으로 보완 라벨링하는 배치 워커.

`services/opinion_labeling.sync_rule_labels` 가 pending 으로 등록해 둔 작업을
선점해 처리한다. 업로드 트랜잭션 안에서 외부 API를 호출하지 않기 위해
분리된 실행 경로다.

사용법:
    python scripts/label_opinions.py                 # pending 처리(설정 상한까지)
    python scripts/label_opinions.py --limit 100     # 이번 실행에서 100건만
    python scripts/label_opinions.py --dry-run       # LLM 호출 없이 대상만 확인
    python scripts/label_opinions.py --retry-failed  # failed 를 pending 으로 되돌림

동시 실행해도 같은 건을 두 번 호출하지 않는다(FOR UPDATE SKIP LOCKED 선점).
실행이 중간에 죽으면 선점된 건이 running 으로 남는데, 다음 실행 시작 때
--stale-minutes(기본 30분)보다 오래된 running 을 자동으로 회수한다.
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai import OpenAIError  # noqa: E402
from sqlalchemy import func, select, update  # noqa: E402

from config import settings  # noqa: E402
from database import SessionLocal  # noqa: E402
from engines.review_keyword_analyzer import RULESET_VERSION, TAXONOMY_VERSION  # noqa: E402
from models.opinion_label import (  # noqa: E402
    LABEL_SOURCE_LLM,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_PENDING,
    RUN_STATUS_RUNNING,
    OpinionCombinationLabel,
    OpinionLabelRun,
)
from models.review_opinion_detail import ReviewOpinionDetail  # noqa: E402
from services.opinion_labeler import is_enabled, label_batch  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("label_opinions")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="검토의견 LLM 보완 라벨링")
    parser.add_argument(
        "--limit",
        type=int,
        default=settings.opinion_label_max_runs_per_execution,
        help="이번 실행에서 처리할 최대 의견 수",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="LLM을 호출하지 않고 대기 건수만 출력한다",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="failed 상태를 pending 으로 되돌린 뒤 처리한다",
    )
    parser.add_argument(
        "--stale-minutes",
        type=int,
        default=30,
        help="이 시간보다 오래 running 인 작업을 회수한다 (기본 30분)",
    )
    return parser.parse_args()


def claim_runs(db, batch_size: int) -> list[tuple[OpinionLabelRun, ReviewOpinionDetail]]:
    """pending 작업을 선점해 running 으로 바꾼다.

    여러 워커가 동시에 돌아도 같은 건을 잡지 않도록 SKIP LOCKED 를 쓴다.
    """
    run_ids = db.execute(
        select(OpinionLabelRun.id)
        .where(
            OpinionLabelRun.status == RUN_STATUS_PENDING,
            OpinionLabelRun.attempts < settings.opinion_label_max_attempts,
        )
        .order_by(OpinionLabelRun.id)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    ).scalars().all()
    if not run_ids:
        return []

    db.execute(
        update(OpinionLabelRun)
        .where(OpinionLabelRun.id.in_(run_ids))
        .values(
            status=RUN_STATUS_RUNNING,
            started_at=datetime.now(timezone.utc),
            attempts=OpinionLabelRun.attempts + 1,
            requested_model=settings.openai_model,
        )
    )
    db.commit()

    rows = db.execute(
        select(OpinionLabelRun, ReviewOpinionDetail)
        .join(ReviewOpinionDetail, OpinionLabelRun.detail_id == ReviewOpinionDetail.id)
        .where(OpinionLabelRun.id.in_(run_ids))
        .order_by(OpinionLabelRun.id)
    ).all()
    return [(run, detail) for run, detail in rows]


def release_runs(db, runs: list[OpinionLabelRun], error: str) -> None:
    """실패한 작업을 재시도 가능 상태로 되돌리거나 failed 로 확정한다."""
    for run in runs:
        exhausted = run.attempts >= settings.opinion_label_max_attempts
        run.status = RUN_STATUS_FAILED if exhausted else RUN_STATUS_PENDING
        run.error = error[:2000]
        if exhausted:
            run.completed_at = datetime.now(timezone.utc)
    db.commit()


def reset_stale_runs(db, stale_minutes: int) -> int:
    """중단된 워커가 선점한 채 남긴 running 작업을 pending 으로 되돌린다.

    워커는 pending 만 선점하므로, 선점 직후 프로세스가 죽으면 그 건은 아무도
    다시 잡지 않는다. 실행 시작 시 오래된 running 을 회수해 그 고착을 푼다.
    attempts 는 유지해 무한 재시도를 막는다.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)
    reset = db.execute(
        update(OpinionLabelRun)
        .where(
            OpinionLabelRun.status == RUN_STATUS_RUNNING,
            (OpinionLabelRun.started_at.is_(None)) | (OpinionLabelRun.started_at < cutoff),
        )
        .values(status=RUN_STATUS_PENDING, error="중단된 작업 회수")
    ).rowcount
    db.commit()
    return reset


def store_labels(
    db,
    run: OpinionLabelRun,
    detail_id: int,
    labels,
    outcome,
    batch_count: int,
) -> int:
    """LLM 라벨을 저장하고 작업을 완료 처리한다.

    라벨이 하나도 없다는 결론도 completed 다. 그래야 같은 건을 다시 호출하지 않는다.
    """
    saved = 0
    for label in labels:
        exists = db.execute(
            select(OpinionCombinationLabel.id).where(
                OpinionCombinationLabel.detail_id == detail_id,
                OpinionCombinationLabel.primary_target == label.primary_target,
                OpinionCombinationLabel.secondary_target == label.secondary_target,
                OpinionCombinationLabel.aspect == label.aspect,
                OpinionCombinationLabel.issue_type == label.issue_type,
            )
        ).first()
        if exists is not None:
            continue
        db.add(OpinionCombinationLabel(
            detail_id=detail_id,
            primary_target=label.primary_target,
            secondary_target=label.secondary_target,
            aspect=label.aspect,
            issue_type=label.issue_type,
            source=LABEL_SOURCE_LLM,
            ruleset_version=RULESET_VERSION,
            taxonomy_version=TAXONOMY_VERSION,
        ))
        saved += 1

    run.status = RUN_STATUS_COMPLETED
    run.completed_at = datetime.now(timezone.utc)
    run.error = None
    run.resolved_model = outcome.resolved_model
    # 토큰은 배치 단위로만 알 수 있다. 배치 전체값을 건마다 그대로 넣으면
    # 합계가 배치 크기만큼 부풀려지므로 이 건의 몫으로 나눠 저장한다.
    run.input_tokens = outcome.input_tokens // batch_count if batch_count else None
    run.output_tokens = outcome.output_tokens // batch_count if batch_count else None
    return saved


def main() -> int:
    args = parse_args()
    db = SessionLocal()
    started = time.monotonic()
    try:
        if args.retry_failed:
            reset = db.execute(
                update(OpinionLabelRun)
                .where(OpinionLabelRun.status == RUN_STATUS_FAILED)
                .values(status=RUN_STATUS_PENDING, attempts=0, error=None)
            ).rowcount
            db.commit()
            logger.info("failed → pending 되돌림: %s건", reset)

        recovered = reset_stale_runs(db, args.stale_minutes)
        if recovered:
            logger.info("중단된 running 작업 회수: %s건", recovered)

        pending = db.execute(
            select(func.count(OpinionLabelRun.id)).where(
                OpinionLabelRun.status == RUN_STATUS_PENDING
            )
        ).scalar_one()
        logger.info(
            "LLM 대기 %s건 / 이번 실행 상한 %s건 / 배치 %s건",
            pending, args.limit, settings.opinion_label_batch_size,
        )
        if args.dry_run:
            logger.info("[dry-run] LLM을 호출하지 않고 종료한다.")
            return 0
        if not is_enabled():
            logger.error("OPENAI_API_KEY 가 설정되지 않아 중단한다.")
            return 1
        if pending == 0:
            return 0

        processed = 0
        labeled = 0
        total_labels = 0
        input_tokens = 0
        output_tokens = 0

        while processed < args.limit:
            batch_size = min(settings.opinion_label_batch_size, args.limit - processed)
            claimed = claim_runs(db, batch_size)
            if not claimed:
                break

            items = [
                (index, detail.content or "", detail.category)
                for index, (_run, detail) in enumerate(claimed)
            ]
            try:
                outcome = label_batch(items)
            except (OpenAIError, RuntimeError) as exc:
                logger.warning("배치 실패: %s", exc)
                release_runs(db, [run for run, _ in claimed], str(exc))
                processed += len(claimed)
                continue

            for index, (run, detail) in enumerate(claimed):
                labels = outcome.labels_by_index.get(index, [])
                saved = store_labels(db, run, detail.id, labels, outcome, len(claimed))
                total_labels += saved
                if labels:
                    labeled += 1
            db.commit()

            processed += len(claimed)
            input_tokens += outcome.input_tokens
            output_tokens += outcome.output_tokens
            logger.info(
                "  %s건 처리 (라벨 %s건, 토큰 in %s / out %s)",
                processed, total_labels, input_tokens, output_tokens,
            )

        elapsed = time.monotonic() - started
        logger.info(
            "완료: %s건 처리, %s건 분류, 라벨 %s건, 토큰 in %s / out %s (%.1f초)",
            processed, labeled, total_labels, input_tokens, output_tokens, elapsed,
        )
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
