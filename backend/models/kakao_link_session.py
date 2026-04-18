"""카카오 계정 연결 임시 세션 모델

OAuth 콜백에서 `need_link` 흐름이 발생했을 때, 카카오 토큰을 URL/JSON으로
프론트에 노출하지 않기 위해 서버에 1회성 세션을 저장하고 추측 불가한
session_id만 프론트에 전달한다.
"""

import secrets
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


def _generate_session_id() -> str:
    # 256비트 랜덤 토큰. 추측 불가 + URL-safe.
    return secrets.token_urlsafe(32)


class KakaoLinkSession(Base):
    __tablename__ = "kakao_link_sessions"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=_generate_session_id
    )
    kakao_id: Mapped[str] = mapped_column(String(100), index=True)
    kakao_access_token: Mapped[str] = mapped_column(String(500))
    kakao_refresh_token: Mapped[str | None] = mapped_column(String(500))
    kakao_expires_in: Mapped[int | None] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
