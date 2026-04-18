"""신규 User와 검토 배정 건물을 자동 연결하는 서비스.

운영 중 검토위원이 뒤늦게 가입하면 `Building.assigned_reviewer_name` 만 채워져 있고
`Building.reviewer_id` 는 NULL 상태라 "내 검토 대상"에 노출되지 않는다. 이 서비스는
User 등록 시점에 Reviewer 행을 보장하고 동일 이름으로 배정된 건물의 FK를 백필한다.

동명이인이 있으면 잘못된 사용자에게 건물을 붙일 위험이 있어 자동 연결을 건너뛰고,
운영자가 `scripts/backfill_reviewer_id.py` 로 수동 확인할 수 있도록 결과만 반환한다.

commit은 호출측(라우터)이 수행한다. 이 서비스는 flush까지만 보장한다.
"""

import unicodedata
from dataclasses import dataclass

from sqlalchemy.orm import Session

from models.building import Building
from models.reviewer import Reviewer
from models.user import User


def normalize_name(name: str | None) -> str:
    """이름 비교용 정규화: NFKC + 모든 공백 제거.

    backfill_reviewer_id 운영 스크립트와 동일한 규칙이어야 하므로
    양쪽이 본 함수를 공유한다.
    """
    if not name:
        return ""
    return "".join(unicodedata.normalize("NFKC", name).split())


@dataclass
class ReviewerLinkResult:
    reviewer_created: bool
    reviewer_id: int | None
    buildings_linked: int
    skipped_reason: str | None  # 동명이인 등으로 자동 연결을 건너뛴 사유


def ensure_reviewer_link(db: Session, user: User) -> ReviewerLinkResult:
    """user에 대한 Reviewer 행 보장 + 이름 일치 건물(reviewer_id NULL) FK 백필."""
    if not user or not user.id:
        return ReviewerLinkResult(False, None, 0, "invalid user")

    reviewer = db.query(Reviewer).filter(Reviewer.user_id == user.id).first()
    reviewer_created = False
    if reviewer is None:
        reviewer = Reviewer(user_id=user.id)
        db.add(reviewer)
        db.flush()
        reviewer_created = True

    key = normalize_name(user.name)
    if not key:
        return ReviewerLinkResult(reviewer_created, reviewer.id, 0, "empty name")

    # 동명이인 체크: 같은 이름의 다른 활성 User가 있으면 자동 배정 금지.
    other_names = (
        db.query(User.name)
        .filter(User.id != user.id, User.is_active.is_(True))
        .all()
    )
    for (other_name,) in other_names:
        if normalize_name(other_name) == key:
            return ReviewerLinkResult(
                reviewer_created, reviewer.id, 0, "duplicate name"
            )

    candidates = (
        db.query(Building)
        .filter(
            Building.reviewer_id.is_(None),
            Building.assigned_reviewer_name.isnot(None),
        )
        .all()
    )
    linked = 0
    for b in candidates:
        if normalize_name(b.assigned_reviewer_name) == key:
            b.reviewer_id = reviewer.id
            linked += 1

    return ReviewerLinkResult(reviewer_created, reviewer.id, linked, None)
