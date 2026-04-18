"""검토위원 리마인드 카톡 일괄 발송 스크립트 (cron 전용 뼈대).

Render Cron Job 또는 수동 CLI 실행에서 사용한다. 실제 발신자는 카카오 로그인된
관리자 계정이어야 하므로 `--sender-email` 인자로 지정한다. 현재는 배포 환경에
자동 등록하지 않았고, 필요 시 Render 대시보드에서 Cron Job 을 추가한 뒤
다음과 같이 호출한다:

    python -m scripts.send_review_reminders --trigger d_minus_1 --sender-email "..." --apply
    python -m scripts.send_review_reminders --trigger overdue    --sender-email "..." --apply

`--apply` 없이 실행하면 dry-run 으로 대상자만 출력한다.
"""

import argparse
import asyncio
import json
import os
import sys

# backend 모듈 경로 보장
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal  # noqa: E402
from models.user import User, UserRole  # noqa: E402
from services.review_reminder import send_review_reminders  # noqa: E402


_ALLOWED_SENDER_ROLES = {UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY}


async def _run(trigger: str, sender_email: str, apply: bool) -> int:
    db = SessionLocal()
    try:
        sender = db.query(User).filter(User.email == sender_email).first()
        if sender is None:
            print(f"[!] sender not found: {sender_email}", file=sys.stderr)
            return 2
        # HTTP 엔드포인트와 동일한 권한 제약을 CLI 에도 적용 (cron 에서
        # 임의 계정이 사용되는 것을 막는다)
        if sender.role not in _ALLOWED_SENDER_ROLES:
            print(
                f"[!] sender role '{sender.role.value}' is not allowed. "
                "Only team_leader / chief_secretary can send review reminders.",
                file=sys.stderr,
            )
            return 3

        result = await send_review_reminders(
            db, sender, trigger, dry_run=not apply
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="검토위원 리마인드 카톡 발송")
    parser.add_argument(
        "--trigger",
        choices=["d_minus_1", "overdue"],
        required=True,
        help="리마인드 트리거 유형",
    )
    parser.add_argument(
        "--sender-email",
        required=True,
        help="발송 주체 관리자 이메일 (카카오 토큰이 유효해야 함)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="실제 발송. 미지정 시 dry-run으로 대상만 출력.",
    )
    args = parser.parse_args()
    return asyncio.run(_run(args.trigger, args.sender_email, args.apply))


if __name__ == "__main__":
    sys.exit(main())
