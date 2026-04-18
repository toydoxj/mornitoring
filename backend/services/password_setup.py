"""비밀번호 셋업 토큰 발급/검증/소비 서비스.

평문 토큰은 생성 시점에만 호출자에게 반환되고, DB에는 sha256 해시만 저장한다.
검증·소비 패턴은 `services/kakao.py`의 lock_link_session과 동일하게
`with_for_update` 행 락 + caller 책임으로 consumed_at 마킹하는 방식.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from logging_config import log_event
from models.password_setup_token import (
    PasswordSetupToken,
    TokenDeliveryChannel,
    TokenPurpose,
)

# 72시간 — codex 권고. 48시간보다 운영 여유, 7일보다 노출 짧음.
SETUP_TOKEN_TTL_SECONDS = 72 * 3600


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _ensure_aware_utc(dt: datetime | None) -> datetime | None:
    """SQLite 등 tz-naive 환경 호환."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def issue_setup_token(
    db: Session,
    *,
    user_id: int,
    purpose: TokenPurpose,
    delivery_channel: TokenDeliveryChannel | None,
    created_by: int | None,
    ttl_seconds: int = SETUP_TOKEN_TTL_SECONDS,
) -> tuple[str, PasswordSetupToken]:
    """평문 토큰 + 저장된 모델 반환.

    같은 사용자의 같은 purpose 미소비 토큰이 있으면 모두 즉시 만료시킨다(consumed_at 마킹).
    이렇게 하면 새 초대를 발송할 때 이전 링크가 자동 무효화된다.
    """
    now = datetime.now(timezone.utc)

    # 기존 미소비 토큰 폐기
    existing = (
        db.query(PasswordSetupToken)
        .filter(
            PasswordSetupToken.user_id == user_id,
            PasswordSetupToken.purpose == purpose,
            PasswordSetupToken.consumed_at.is_(None),
        )
        .all()
    )
    for row in existing:
        row.consumed_at = now

    raw_token = secrets.token_urlsafe(32)  # 256bit
    token = PasswordSetupToken(
        token_hash=_hash_token(raw_token),
        user_id=user_id,
        purpose=purpose,
        delivery_channel=delivery_channel,
        expires_at=now + timedelta(seconds=ttl_seconds),
        created_by=created_by,
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    log_event(
        "info", "password_setup_token_issued",
        user_id=user_id, purpose=purpose.value,
        delivery=delivery_channel.value if delivery_channel else "-",
    )
    return raw_token, token


def lookup_setup_token(db: Session, raw_token: str) -> PasswordSetupToken | None:
    """평문 토큰으로 조회. 만료/소비/존재하지 않으면 None.

    조회 시 행 락(`with_for_update`)을 잡아 동시 소비를 직렬화한다.
    consumed_at 마킹은 호출자가 비밀번호 설정 후 같은 트랜잭션에서 수행한다.
    """
    if not raw_token:
        return None
    token = (
        db.query(PasswordSetupToken)
        .filter(PasswordSetupToken.token_hash == _hash_token(raw_token))
        .with_for_update()
        .first()
    )
    if token is None:
        return None
    if token.consumed_at is not None:
        return None
    if _ensure_aware_utc(token.expires_at) <= datetime.now(timezone.utc):
        return None
    return token


def purge_expired_setup_tokens(db: Session) -> int:
    """만료/소비 토큰 정리. 운영 영향 줄이려면 주기 호출 권장."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    deleted = (
        db.query(PasswordSetupToken)
        .filter(
            (PasswordSetupToken.expires_at <= datetime.now(timezone.utc))
            | (PasswordSetupToken.consumed_at <= cutoff)
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted
