"""검토위원 상세 모델"""

from sqlalchemy import String, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Reviewer(Base):
    __tablename__ = "reviewers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    group_no: Mapped[str | None] = mapped_column(String(10))   # 조 번호
    specialty: Mapped[str | None] = mapped_column(String(100))  # 전문 분야

    user = relationship("User")
    buildings = relationship("Building", back_populates="reviewer")
