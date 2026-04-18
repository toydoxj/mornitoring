"""Building.assigned_reviewer_name → reviewer_id 백필 스크립트.

C 권한 정책에서 검토위원 매칭을 reviewer_id만 사용하도록 변경했기 때문에,
`assigned_reviewer_name`은 채워졌지만 `reviewer_id`가 비어 있는 건물은
검토위원이 본인 건물을 못 보게 된다. 이 스크립트는 그 데이터를 자동 백필한다.

매핑 규칙:
  assigned_reviewer_name (이름)
    → User(role=REVIEWER, name=이름) 단일 매칭
    → 그 User에 연결된 Reviewer.id

매핑 불가 케이스(unresolved)는 리포트로만 출력하고 건너뛴다:
  - 같은 이름의 User가 0명
  - 같은 이름의 User가 2명 이상 (동명이인)
  - User는 있지만 연결된 Reviewer 행 없음 (--create-missing-reviewer로 자동 생성 가능)

사용:
  python -m scripts.backfill_reviewer_id                              # dry-run (REVIEWER만)
  python -m scripts.backfill_reviewer_id --apply                       # 실제 반영
  python -m scripts.backfill_reviewer_id --include-all-roles           # 모든 역할 대상 + Reviewer 자동 생성 (dry-run)
  python -m scripts.backfill_reviewer_id --include-all-roles --apply   # 정식 운영용
"""

import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy.orm import Session

# backend 모듈 경로 보장
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models.building import Building
from models.reviewer import Reviewer
from models.user import User, UserRole
from services.reviewer_link import normalize_name as _normalize_name


@dataclass
class BackfillReport:
    matched: list[tuple[int, str, int]]  # (building_id, name, reviewer_id)
    no_user: list[tuple[int, str]]       # (building_id, name)
    multiple_users: list[tuple[int, str, int]]  # (building_id, name, user_count)
    no_reviewer_row: list[tuple[int, str, int]]  # (building_id, name, user_id)


def _build_reviewer_index(
    db: Session, *, include_all_roles: bool = False
) -> dict[str, dict[str, list]]:
    """사용자명(정규화 키) → Reviewer/User 목록 인덱스.

    include_all_roles=False (기본): REVIEWER 역할만 대상
    include_all_roles=True: 모든 활성 사용자 대상 (검토 업무하는 SECRETARY/CHIEF/TEAM_LEADER 포함)
    """
    query = (
        db.query(User, Reviewer)
        .outerjoin(Reviewer, Reviewer.user_id == User.id)
        .filter(User.is_active.is_(True))
    )
    if not include_all_roles:
        query = query.filter(User.role == UserRole.REVIEWER)
    rows = query.all()

    index: dict[str, list[Reviewer]] = defaultdict(list)
    user_only: dict[str, list[User]] = defaultdict(list)
    for user, reviewer in rows:
        key = _normalize_name(user.name)
        if reviewer is not None:
            index[key].append(reviewer)
        else:
            user_only[key].append(user)
    return {"with_reviewer": dict(index), "user_only": dict(user_only)}


def collect(db: Session, *, include_all_roles: bool = False) -> BackfillReport:
    """백필 대상과 unresolved를 분류만 한다 (DB 변경 없음)."""
    index = _build_reviewer_index(db, include_all_roles=include_all_roles)
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


def apply(
    db: Session,
    report: BackfillReport,
    *,
    create_missing_reviewer: bool = False,
) -> tuple[int, int]:
    """matched 항목 + (옵션) no_reviewer_row 자동 생성. (반영 건물 수, 생성 Reviewer 수)."""
    created_reviewer_ids: dict[int, int] = {}  # user_id → reviewer_id
    if create_missing_reviewer and report.no_reviewer_row:
        for _bid, _name, user_id in report.no_reviewer_row:
            if user_id in created_reviewer_ids:
                continue
            existing = db.query(Reviewer).filter(Reviewer.user_id == user_id).first()
            if existing:
                created_reviewer_ids[user_id] = existing.id
                continue
            new_reviewer = Reviewer(user_id=user_id)
            db.add(new_reviewer)
            db.flush()
            created_reviewer_ids[user_id] = new_reviewer.id

    updated = 0
    for building_id, _name, reviewer_id in report.matched:
        building = db.query(Building).filter(Building.id == building_id).first()
        if building is None:
            continue
        building.reviewer_id = reviewer_id
        updated += 1

    if create_missing_reviewer:
        for building_id, _name, user_id in report.no_reviewer_row:
            new_reviewer_id = created_reviewer_ids.get(user_id)
            if not new_reviewer_id:
                continue
            building = db.query(Building).filter(Building.id == building_id).first()
            if building is None:
                continue
            building.reviewer_id = new_reviewer_id
            updated += 1

    db.commit()
    return updated, len(created_reviewer_ids)


def print_report(
    report: BackfillReport,
    *,
    applied: bool,
    updated_buildings: int = 0,
    created_reviewers: int = 0,
    create_missing_reviewer: bool = False,
) -> None:
    print("=" * 60)
    print("reviewer_id 백필 리포트")
    print("=" * 60)
    print(f"매핑 가능 (단일 후보): {len(report.matched)}건")
    for bid, name, rid in report.matched:
        print(f"  - building_id={bid}  name='{name}'  → reviewer_id={rid}")

    print(f"\n매핑 불가 — User 없음: {len(report.no_user)}건")
    for bid, name in report.no_user[:20]:
        print(f"  - building_id={bid}  name='{name}'")
    if len(report.no_user) > 20:
        print(f"  ... 그 외 {len(report.no_user) - 20}건")

    print(f"\n매핑 불가 — 동명이인 다수: {len(report.multiple_users)}건")
    for bid, name, count in report.multiple_users:
        print(f"  - building_id={bid}  name='{name}'  candidates={count}")

    label_no_reviewer = (
        "User는 있으나 Reviewer 행 없음 (자동 생성 대상)"
        if create_missing_reviewer
        else "User는 있으나 Reviewer 행 없음 (--create-missing-reviewer로 자동 생성 가능)"
    )
    print(f"\n매핑 불가 — {label_no_reviewer}: {len(report.no_reviewer_row)}건")
    for bid, name, uid in report.no_reviewer_row[:20]:
        print(f"  - building_id={bid}  name='{name}'  user_id={uid}")
    if len(report.no_reviewer_row) > 20:
        print(f"  ... 그 외 {len(report.no_reviewer_row) - 20}건")

    print("\n" + "=" * 60)
    if applied:
        print(f"적용 완료: building.reviewer_id {updated_buildings}건 갱신")
        if create_missing_reviewer:
            print(f"          Reviewer 행 신규 생성: {created_reviewers}명")
    else:
        suggest = "--apply"
        if report.no_reviewer_row and not create_missing_reviewer:
            suggest = "--apply --create-missing-reviewer"
        print(f"[dry-run] 변경 없음. 실제 반영하려면 `{suggest}` 옵션을 추가하세요.")
    if report.no_user or report.multiple_users or (
        report.no_reviewer_row and not create_missing_reviewer
    ):
        print("\n[!] 매핑 불가 건은 수동 확인이 필요합니다.")


def main() -> int:
    parser = argparse.ArgumentParser(description="reviewer_id 백필")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="실제로 DB에 반영. 미지정 시 dry-run.",
    )
    parser.add_argument(
        "--include-all-roles",
        action="store_true",
        help="REVIEWER 외 SECRETARY/CHIEF_SECRETARY/TEAM_LEADER 등 모든 활성 사용자 대상.",
    )
    parser.add_argument(
        "--create-missing-reviewer",
        action="store_true",
        help="User는 있으나 Reviewer 행이 없는 사용자에게 Reviewer 행 자동 생성.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        report = collect(db, include_all_roles=args.include_all_roles)
        updated_buildings = 0
        created_reviewers = 0
        if args.apply:
            updated_buildings, created_reviewers = apply(
                db, report, create_missing_reviewer=args.create_missing_reviewer
            )
        print_report(
            report,
            applied=args.apply,
            updated_buildings=updated_buildings,
            created_reviewers=created_reviewers,
            create_missing_reviewer=args.create_missing_reviewer,
        )
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
