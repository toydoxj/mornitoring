"""초대 발송 서비스 — 단건/일괄 공통 로직.

흐름:
  1. 대상 사용자별 setup token 발급 (기존 미소비 토큰은 자동 무효화)
  2. 카카오 매칭 사용자 모아 5명씩 batch로 send_message_to_friends 호출
  3. 미매칭/카카오 발송 실패자는 manual delivery로 결과 생성

응답 setup_url은 manual/error 케이스에만 포함한다(불필요한 민감 링크 노출 최소화).
사용자별 commit은 best-effort: 한 명 실패해도 나머지는 그대로 처리.
카카오 발신자 토큰 만료 시 모든 대상이 manual fallback으로 떨어진다.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from config import settings
from logging_config import log_event
from models.password_setup_token import (
    PasswordSetupToken,
    TokenDeliveryChannel,
    TokenPurpose,
)
from models.user import User
from services.password_setup import issue_setup_token

# 카카오 친구 메시지 batch 한 번에 5명 (이미 send_message_to_friends 패턴)
KAKAO_BATCH_SIZE = 5


@dataclass
class InviteResult:
    user_id: int
    name: str
    delivery: str  # "kakao" | "manual"
    expires_at: str
    setup_url: str | None  # manual/error에만
    error: str | None


@dataclass
class InviteSummary:
    total: int
    kakao_sent: int
    manual: int
    failed: int
    sender_error: str | None  # 카카오 발신자 토큰 미준비 등 공통 사유


def _setup_url_for(raw_token: str) -> str:
    return f"{settings.frontend_base_url.rstrip('/')}/setup-password?token={raw_token}"


async def send_invites(
    db: Session,
    *,
    sender: User,
    targets: list[User],
    purpose: TokenPurpose,
) -> tuple[InviteSummary, list[InviteResult]]:
    """단건/일괄 공통. targets에 1명만 들어와도 동일 흐름."""
    if not targets:
        return InviteSummary(0, 0, 0, 0, None), []

    # 1) 사용자별 토큰 발급 (사용자별 commit, 기존 미소비 토큰 자동 무효화)
    raw_tokens: dict[int, str] = {}
    tokens: dict[int, PasswordSetupToken] = {}
    for target in targets:
        # 잠정 channel 결정 (카카오 매칭이면 kakao 시도, 아니면 manual)
        channel = (
            TokenDeliveryChannel.KAKAO
            if target.kakao_uuid
            else TokenDeliveryChannel.MANUAL
        )
        raw, token = issue_setup_token(
            db,
            user_id=target.id,
            purpose=purpose,
            delivery_channel=channel,
            created_by=sender.id,
        )
        raw_tokens[target.id] = raw
        tokens[target.id] = token

    # 2) 카카오 매칭자/미매칭자 분리
    kakao_targets = [t for t in targets if t.kakao_uuid]
    manual_targets = [t for t in targets if not t.kakao_uuid]

    # 3) 카카오 발신자 토큰 준비
    sender_error: str | None = None
    access_token: str | None = None
    if kakao_targets:
        try:
            from services.kakao import ensure_valid_token
            access_token = await ensure_valid_token(sender, db)
        except Exception as exc:
            sender_error = f"카카오 발신자 토큰 사용 불가: {exc}"
            log_event(
                "warning", "bulk_invite_sender_unavailable",
                sender_id=sender.id, reason=str(exc),
            )

    # 결과 누적
    results: dict[int, InviteResult] = {}

    # 4) 카카오 batch 발송 (또는 sender_error 시 모두 manual fallback)
    if access_token and kakao_targets:
        from services.kakao import send_message_to_friends

        for i in range(0, len(kakao_targets), KAKAO_BATCH_SIZE):
            batch = kakao_targets[i : i + KAKAO_BATCH_SIZE]
            uuid_to_user = {t.kakao_uuid: t for t in batch if t.kakao_uuid}
            uuids = list(uuid_to_user.keys())

            # 같은 메시지 본문 — 사용자명 개별화는 batch 한계로 일단 공통
            title = "건축구조안전 모니터링 — 비밀번호 설정"
            description = (
                "시스템 접속을 위해 비밀번호를 설정해주세요. 링크는 72시간 후 만료됩니다."
            )

            # batch 단위 카카오 호출 — link_url은 공통이라 사용자별 setup_url을 따로 전달 못함.
            # 따라서 link_url 대신 메시지 본문에 사용자별 setup_url을 못 넣는 한계가 있음.
            # 대안: batch가 아닌 사용자별 호출로 setup_url 개별화. 효율 vs 개별화 트레이드오프.
            # 여기서는 사용자별 1건씩 친구 메시지 호출로 결정 — 개별 setup_url 보장.
            for target in batch:
                raw_token = raw_tokens[target.id]
                setup_url = _setup_url_for(raw_token)
                title_user = title
                description_user = (
                    f"{target.name}님, 시스템 접속을 위해 비밀번호를 설정해주세요. "
                    f"링크는 72시간 후 만료됩니다."
                )
                try:
                    res = await send_message_to_friends(
                        access_token=access_token,
                        receiver_uuids=[target.kakao_uuid] if target.kakao_uuid else [],
                        title=title_user,
                        description=description_user,
                        link_url=setup_url,
                    )
                except Exception as exc:
                    res = {"error": "exception", "detail": str(exc)}

                if "error" in res:
                    err = str(res.get("detail", "발송 실패"))
                    tokens[target.id].delivery_channel = TokenDeliveryChannel.MANUAL
                    db.commit()
                    log_event(
                        "error", "bulk_invite_kakao_failed",
                        user_id=target.id, reason=err,
                    )
                    results[target.id] = InviteResult(
                        user_id=target.id,
                        name=target.name,
                        delivery="manual",
                        expires_at=tokens[target.id].expires_at.isoformat(),
                        setup_url=setup_url,
                        error=err,
                    )
                else:
                    log_event(
                        "info", "bulk_invite_kakao_sent",
                        user_id=target.id, purpose=purpose.value,
                    )
                    results[target.id] = InviteResult(
                        user_id=target.id,
                        name=target.name,
                        delivery="kakao",
                        expires_at=tokens[target.id].expires_at.isoformat(),
                        setup_url=None,
                        error=None,
                    )
    else:
        # 카카오 발신자 사용 불가 → 카카오 매칭자도 manual fallback.
        # 토큰은 정상 발급됐고 setup_url 전달 가능하므로 정상 manual로 카운트.
        # 발신자 미준비 사유는 summary.sender_error에서만 한 번 노출.
        for target in kakao_targets:
            tokens[target.id].delivery_channel = TokenDeliveryChannel.MANUAL
            db.commit()
            results[target.id] = InviteResult(
                user_id=target.id,
                name=target.name,
                delivery="manual",
                expires_at=tokens[target.id].expires_at.isoformat(),
                setup_url=_setup_url_for(raw_tokens[target.id]),
                error=None,
            )

    # 5) 미매칭자 manual
    for target in manual_targets:
        results[target.id] = InviteResult(
            user_id=target.id,
            name=target.name,
            delivery="manual",
            expires_at=tokens[target.id].expires_at.isoformat(),
            setup_url=_setup_url_for(raw_tokens[target.id]),
            error=None,
        )

    # 입력 순서 유지
    ordered = [results[t.id] for t in targets]
    summary = InviteSummary(
        total=len(targets),
        kakao_sent=sum(1 for r in ordered if r.delivery == "kakao" and not r.error),
        manual=sum(1 for r in ordered if r.delivery == "manual" and not r.error),
        failed=sum(1 for r in ordered if r.error),
        sender_error=sender_error,
    )
    return summary, ordered
