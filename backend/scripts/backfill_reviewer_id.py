"""Building.assigned_reviewer_name → reviewer_id 백필 스크립트.

C 권한 정책에서 검토위원 매칭을 reviewer_id만 사용하도록 변경했기 때문에,
`assigned_reviewer_name`은 채워졌지만 `reviewer_id`가 비어 있는 건물은
검토위원이 본인 건물을 못 보게 된다. 이 스크립트는 그 데이터를 자동 백필한다.

매핑 규칙:
  assigned_reviewer_name (이름)
    → User(role=REVIEWER, name=이름) 단일 매칭
    → 그 User에 연결된 Reviewer.id

매핑 불가 케이스(unresolved)는 리포트로만 출력하고 건너뛴다:
  - 같은 이름의 REVIEWER User가 0명
  - 같은 이름의 REVIEWER User가 2명 이상 (동명이인)
  - User는 있지만 연결된 Reviewer 행이 없음

사용:
  python -m scripts.backfill_reviewer_id            # dry-run (변경 없음)
  python -m scripts.backfill_reviewer_id --apply    # 실제 반영
"""

import argparse
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy.orm import Session


def _normalize_name(name: str | None) -> str:
    """이름 비교용 정규화: NFKC + 모든 공백 제거.

    엑셀 데이터의 "박 준 형" 같이 자모 사이 공백이 들어간 케이스와
    NFC/NFKC 차이로 인한 한글 표현 불일치를 흡수한다.
    공격적 변환(한자→한글, 초성 추정 등)은 오매핑 위험으로 적용하지 않는다.
    """
    if not name:
        return ""
    normalized = unicodedata.normalize("NFKC", name)
    return "".join(normalized.split())

# backend 모듈 경로 보장
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models.building import Building
from models.reviewer import Reviewer
from models.user import User, UserRole


@dataclass
class BackfillReport:
    matched: list[tuple[int, str, int]]  # (building_id, name, reviewer_id)
    no_user: list[tuple[int, str]]       # (building_id, name)
    multiple_users: list[tuple[int, str, int]]  # (building_id, name, user_count)
    no_reviewer_row: list[tuple[int, str, int]]  # (building_id, name, user_id)


def _build_reviewer_index(db: Session) -> dict[str, dict[str, list]]:
    """REVIEWER 역할 사용자명(정규화 키) → Reviewer/User 목록 인덱스.

    동명이인이 있으면 같은 키에 여러 행이 들어간다.
    Reviewer 행이 없는 User는 user_only로 분류 → no_reviewer_row 리포트용.
    """
    rows = (
        db.query(User, Reviewer)
        .outerjoin(Reviewer, Reviewer.user_id == User.id)
        .filter(User.role == UserRole.REVIEWER)
        .all()
    )
    index: dict[str, list[Reviewer]] = defaultdict(list)
    user_only: dict[str, list[User]] = defaultdict(list)
    for user, reviewer in rows:
        key = _normalize_name(user.name)
        if reviewer is not None:
            index[key].append(reviewer)
        else:
            user_only[key].append(user)
    return {"with_reviewer": dict(index), "user_only": dict(user_only)}


def collect(db: Session) -> BackfillReport:
    """백필 대상과 unresolved를 분류만 한다 (DB 변경 없음)."""
    index = _build_reviewer_index(db)
    with_reviewer: dict[str, list[Reviewer]] = index["with_reviewer"]
    user_only: dict[str, list[User]] = index["user_only"]

    targets = (
        db.query(Building)
        .filter(
            Building.assigned_reviewer_name.isnot(None),
            Building.reviewer_id.is_(None),
        )
        .all()
    )

    matched: list[tuple[int, str, int]] = []
    no_user: list[tuple[int, str]] = []
    multiple: list[tuple[int, str, int]] = []
    no_reviewer_row: list[tuple[int, str, int]] = []

    for building in targets:
        raw_name = building.assigned_reviewer_name or ""
        key = _normalize_name(raw_name)
        candidates = with_reviewer.get(key, [])
        if len(candidates) == 1:
            matched.append((building.id, raw_name, candidates[0].id))
        elif len(candidates) >= 2:
            multiple.append((building.id, raw_name, len(candidates)))
        else:
            users_without_reviewer = user_only.get(key, [])
            if users_without_reviewer:
                no_reviewer_row.append(
                    (building.id, raw_name, users_without_reviewer[0].id)
                )
            else:
                no_user.append((building.id, raw_name))

    return BackfillReport(
        matched=matched,
        no_user=no_user,
        multiple_users=multiple,
        no_reviewer_row=no_reviewer_row,
    )


def apply(db: Session, report: BackfillReport) -> int:
    """matched 항목만 실제 반영. 변경 행 수 반환."""
    if not report.matched:
        return 0
    for building_id, _name, reviewer_id in report.matched:
        building = db.query(Building).filter(Building.id == building_id).first()
        if building is None:
            continue
        building.reviewer_id = reviewer_id
    db.commit()
    return len(report.matched)


def print_report(report: BackfillReport, *, applied: bool) -> None:
    print("=" * 60)
    print("reviewer_id 백필 리포트")
    print("=" * 60)
    print(f"매핑 가능 (단일 후보): {len(report.matched)}건")
    for bid, name, rid in report.matched:
        print(f"  - building_id={bid}  name='{name}'  → reviewer_id={rid}")

    print(f"\n매핑 불가 — User 없음: {len(report.no_user)}건")
    for bid, name in report.no_user:
        print(f"  - building_id={bid}  name='{name}'")

    print(f"\n매핑 불가 — 동명이인 다수: {len(report.multiple_users)}건")
    for bid, name, count in report.multiple_users:
        print(f"  - building_id={bid}  name='{name}'  candidates={count}")

    print(f"\n매핑 불가 — User는 있으나 Reviewer 행 없음: {len(report.no_reviewer_row)}건")
    for bid, name, uid in report.no_reviewer_row:
        print(f"  - building_id={bid}  name='{name}'  user_id={uid}")

    print("\n" + "=" * 60)
    if applied:
        print(f"적용 완료: {len(report.matched)}건의 reviewer_id 갱신")
    else:
        print("[dry-run] 변경 없음. 실제 반영하려면 --apply 옵션을 추가하세요.")
    if report.no_user or report.multiple_users or report.no_reviewer_row:
        print("\n[!] 매핑 불가 건은 수동 확인이 필요합니다.")


def main() -> int:
    parser = argparse.ArgumentParser(description="reviewer_id 백필")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="실제로 DB에 반영. 미지정 시 dry-run.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        report = collect(db)
        if args.apply:
            apply(db, report)
        print_report(report, applied=args.apply)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
