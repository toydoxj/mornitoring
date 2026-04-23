"""검토위원 상세 모델"""

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Reviewer(Base):
    __tablename__ = "reviewers"
    __table_args__ = (
        # 조는 1~7만 허용. NULL은 미배정으로 자유롭게.
        CheckConstraint(
            "group_no IS NULL OR (group_no >= 1 AND group_no <= 7)",
            name="ck_reviewers_group_no_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    group_no: Mapped[int | None] = mapped_column(Integer)        # 조 번호 (1~7)
    specialty: Mapped[str | None] = mapped_column(String(100))   # 전문 분야

    user = relationship("User")
    buildings = relationship("Building", back_populates="reviewer")
