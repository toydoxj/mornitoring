"""Inquiry.submitter_id 백필 스크립트.

N3에서 `Inquiry.submitter_id` FK를 추가하고 `/my-inquiries`가 이 컬럼만 사용하도록
변경했기 때문에, 그 이전에 작성된 historical inquiry는 submitter_id가 NULL로 남아
작성자가 본인 문의 목록에서 보지 못한다. 이 스크립트는 `submitter_name`을 이름
정규화(NFKC + 공백 제거) 후 `User.name`과 단일 매칭되면 `submitter_id`를 채운다.

사용:
  python -m scripts.backfill_inquiry_submitter_id            # dry-run
  python -m scripts.backfill_inquiry_submitter_id --apply    # 실제 반영
"""

import argparse
import os
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models.inquiry import Inquiry
from models.user import User


def _normalize_name(name: str | None) -> str:
    if not name:
        return ""
    return "".join(unicodedata.normalize("NFKC", name).split())


@dataclass
class Report:
    matched: list[tuple[int, str, int]]      # (inquiry_id, name, user_id)
    no_user: list[tuple[int, str]]           # 같은 이름 사용자 0명
    multiple_users: list[tuple[int, str, int]]  # 동명이인 다수


def collect(db: Session) -> Report:
    user_index: dict[str, list[User]] = defaultdict(list)
    for u in db.query(User).all():
        user_index[_normalize_name(u.name)].append(u)

    targets = db.query(Inquiry).filter(Inquiry.submitter_id.is_(None)).all()
    matched: list = []
    no_user: list = []
    multiple: list = []

    for inq in targets:
        key = _normalize_name(inq.submitter_name)
        candidates = user_index.get(key, [])
        if len(candidates) == 1:
            matched.append((inq.id, inq.submitter_name or "", candidates[0].id))
        elif len(candidates) >= 2:
            multiple.append((inq.id, inq.submitter_name or "", len(candidates)))
        else:
            no_user.append((inq.id, inq.submitter_name or ""))

    return Report(matched=matched, no_user=no_user, multiple_users=multiple)


def apply(db: Session, report: Report) -> int:
    for inquiry_id, _name, user_id in report.matched:
        inq = db.query(Inquiry).filter(Inquiry.id == inquiry_id).first()
        if inq is None:
            continue
        inq.submitter_id = user_id
    db.commit()
    return len(report.matched)


def print_report(report: Report, *, applied: bool) -> None:
    print("=" * 60)
    print("inquiry.submitter_id 백필 리포트")
    print("=" * 60)
    print(f"매핑 가능 (단일 후보): {len(report.matched)}건")
    for iid, name, uid in report.matched[:20]:
        print(f"  - inquiry_id={iid}  name='{name}'  → user_id={uid}")
    if len(report.matched) > 20:
        print(f"  ... 그 외 {len(report.matched) - 20}건")

    print(f"\n매핑 불가 — User 없음: {len(report.no_user)}건")
    for iid, name in report.no_user[:20]:
        print(f"  - inquiry_id={iid}  name='{name}'")

    print(f"\n매핑 불가 — 동명이인 다수: {len(report.multiple_users)}건")
    for iid, name, count in report.multiple_users:
        print(f"  - inquiry_id={iid}  name='{name}'  candidates={count}")

    print("\n" + "=" * 60)
    if applied:
        print(f"적용 완료: {len(report.matched)}건의 submitter_id 갱신")
    else:
        print("[dry-run] 변경 없음. --apply로 실제 반영.")


def main() -> int:
    parser = argparse.ArgumentParser(description="inquiry.submitter_id 백필")
    parser.add_argument("--apply", action="store_true")
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
