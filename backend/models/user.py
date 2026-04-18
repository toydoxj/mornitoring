"""사용자 모델"""

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class UserRole(str, enum.Enum):
    TEAM_LEADER = "team_leader"          # 모니터링 팀장
    CHIEF_SECRETARY = "chief_secretary"  # 총괄간사
    SECRETARY = "secretary"              # 간사
    REVIEWER = "reviewer"                # 검토위원


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # kakao_id partial unique: 한 카카오 계정은 단 하나의 사용자에만 연결.
        # NULL은 다수 허용(카카오 미연동 사용자 다수 존재 가능).
        Index(
            "uq_users_kakao_id_not_null",
            "kakao_id",
            unique=True,
            postgresql_where=text("kakao_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50))
    email: Mapped[str] = mapped_column(String(100), unique=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole))
    phone: Mapped[str | None] = mapped_column(String(20))
    kakao_id: Mapped[str | None] = mapped_column(String(100))
    kakao_uuid: Mapped[str | None] = mapped_column(String(100))
    kakao_access_token: Mapped[str | None] = mapped_column(String(500))
    kakao_refresh_token: Mapped[str | None] = mapped_column(String(500))
    kakao_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_hash: Mapped[str | None] = mapped_column(String(200))
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
