"""사용자 모델"""

import enum
from datetime import datetime

from sqlalchemy import String, Boolean, Enum, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class UserRole(str, enum.Enum):
    TEAM_LEADER = "team_leader"          # 모니터링 팀장
    CHIEF_SECRETARY = "chief_secretary"  # 총괄간사
    SECRETARY = "secretary"              # 간사
    REVIEWER = "reviewer"                # 검토위원


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50))
    email: Mapped[str] = mapped_column(String(100), unique=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole))
    phone: Mapped[str | None] = mapped_column(String(20))
    kakao_id: Mapped[str | None] = mapped_column(String(100))
    kakao_access_token: Mapped[str | None] = mapped_column(String(500))
    kakao_refresh_token: Mapped[str | None] = mapped_column(String(500))
    password_hash: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
