"""비밀번호 초기 설정/재설정용 1회성 토큰 모델.

평문 토큰은 응답으로 단 한 번만 노출되고, DB에는 sha256 해시만 저장한다.
DB 유출 시에도 토큰 자체는 재사용 불가.

검증 흐름:
  1. 사용자가 평문 토큰을 들고 `/setup-password?token=...`로 접근
  2. 서버에서 `sha256(token)`을 키로 행 조회 + 락
  3. 만료/소비 검사
  4. 비밀번호 설정 완료 후 consumed_at 마킹
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class TokenPurpose(str, enum.Enum):
    INITIAL_SETUP = "initial_setup"
    PASSWORD_RESET = "password_reset"


class TokenDeliveryChannel(str, enum.Enum):
    KAKAO = "kakao"      # 카카오 메시지로 자동 발송됨
    MANUAL = "manual"    # 관리자가 다른 채널로 직접 전달


class PasswordSetupToken(Base):
    __tablename__ = "password_setup_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # sha256(raw_token) hex 문자열 — 평문은 절대 저장하지 않는다
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    purpose: Mapped[TokenPurpose] = mapped_column(Enum(TokenPurpose))
    delivery_channel: Mapped[TokenDeliveryChannel | None] = mapped_column(
        Enum(TokenDeliveryChannel)
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
