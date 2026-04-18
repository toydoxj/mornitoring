"""감사 로그 모델"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base

# 운영(PostgreSQL)은 JSONB, 테스트(SQLite)는 JSON으로 자동 매핑.
JSONField = JSONB().with_variant(JSON(), "sqlite")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100))       # create / update / delete / upload
    target_type: Mapped[str] = mapped_column(String(50))    # building / review_stage / user
    target_id: Mapped[int | None] = mapped_column(Integer)
    before_data: Mapped[dict | None] = mapped_column(JSONField)
    after_data: Mapped[dict | None] = mapped_column(JSONField)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
