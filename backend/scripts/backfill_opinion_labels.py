"""기존 검토의견에 조합 라벨(대상 x 문제유형)을 채워 넣는 백필 스크립트.

업로드 시점에는 `services/opinion_labeling.sync_rule_labels_for_stage` 가
자동으로 라벨을 만든다. 이 스크립트는 그 기능이 생기기 전에 저장된 의견과,
규칙 사전을 고쳐 재계산이 필요할 때를 위한 것이다.

사용법:
    python scripts/backfill_opinion_labels.py            # 라벨 없는 건만 처리
    python scripts/backfill_opinion_labels.py --all      # 규칙 라벨 전체 재계산
    python scripts/backfill_opinion_labels.py --dry-run  # 저장 없이 건수만 확인
    python scripts/backfill_opinion_labels.py --chunk 2000
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, select  # noqa: E402

from database import SessionLocal  # noqa: E402
from engines.review_keyword_analyzer import RULESET_VERSION, TAXONOMY_VERSION  # noqa: E402
from models.opinion_label import (  # noqa: E402
    LABEL_SOURCE_RULE,
    OpinionCombinationLabel,
)
from models.review_opinion_detail import ReviewOpinionDetail  # noqa: E402
from services.opinion_labeling import sync_rule_labels  # noqa: E402

DEFAULT_CHUNK = 1000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="검토의견 조합 라벨 백필")
    parser.add_argument(
        "--all",
        action="store_true",
        help="이미 라벨이 있는 의견도 포함해 규칙 라벨을 전부 다시 만든다",
    )
    parser.add_argument(
        "--chunk",
        type=int,
        default=DEFAULT_CHUNK,
        help=f"한 번에 처리할 의견 수 (기본 {DEFAULT_CHUNK})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="저장하지 않고 처리 대상 건수만 출력한다",
    )
    return parser.parse_args()


def target_detail_ids(db, process_all: bool) -> list[int]:
    """처리 대상 상세의견 id를 모은다."""
    stmt = select(ReviewOpinionDetail.id).order_by(ReviewOpinionDetail.id)
    if not process_all:
        # 규칙 라벨이 이미 현재 버전으로 붙어 있는 건은 건너뛴다.
        current = (
            select(OpinionCombinationLabel.detail_id)
            .where(
                OpinionCombinationLabel.detail_id == ReviewOpinionDetail.id,
                OpinionCombinationLabel.source == LABEL_SOURCE_RULE,
                OpinionCombinationLabel.ruleset_version == RULESET_VERSION,
                OpinionCombinationLabel.taxonomy_version == TAXONOMY_VERSION,
            )
            .exists()
        )
        stmt = stmt.where(~current)
    return list(db.execute(stmt).scalars().all())


def main() -> int:
    args = parse_args()
    db = SessionLocal()
    started = time.monotonic()
    try:
        total_details = db.execute(
            select(func.count(ReviewOpinionDetail.id))
        ).scalar_one()
        detail_ids = target_detail_ids(db, args.all)
        print(
            f"상세의견 전체 {total_details}건 / 처리 대상 {len(detail_ids)}건 "
            f"(사전 {RULESET_VERSION}, 분류체계 {TAXONOMY_VERSION})"
        )
        if args.dry_run:
            print("[dry-run] 저장하지 않고 종료한다.")
            return 0
        if not detail_ids:
            print("처리할 대상이 없다.")
            return 0

        totals = {"details": 0, "labeled_details": 0, "labels": 0, "pending_runs": 0}
        for offset in range(0, len(detail_ids), args.chunk):
            chunk_ids = detail_ids[offset:offset + args.chunk]
            details = db.execute(
                select(ReviewOpinionDetail).where(ReviewOpinionDetail.id.in_(chunk_ids))
            ).scalars().all()
            result = sync_rule_labels(db, details)
            db.commit()
            for key in totals:
                totals[key] += result[key]
            print(
                f"  {offset + len(chunk_ids)}/{len(detail_ids)} 처리 "
                f"(라벨 {totals['labels']}건, 미분류 대기 {totals['pending_runs']}건)"
            )

        elapsed = time.monotonic() - started
        print(
            f"완료: 의견 {totals['details']}건 중 {totals['labeled_details']}건 분류, "
            f"라벨 {totals['labels']}건, LLM 대기 {totals['pending_runs']}건 "
            f"({elapsed:.1f}초)"
        )
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
