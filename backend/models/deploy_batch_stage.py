"""배포차수별 기준 검토 단계.

배포차수(관리번호 일련번호 구간으로 나눈 배포 배치)마다 "지금 이 차수는 어느
검토 단계여야 하는가"를 총괄간사가 지정한다. 도서 접수 시 자동 판별된 단계가
이 기준과 어긋나면 기준에 맞춰 강제 보정한다.

phase 는 ReviewStage 의 제출 단계 값(preliminary, supplement_1~5)을 쓴다.
행이 없는 차수는 기준 미설정으로 보고 보정을 건너뛴다.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class DeployBatchStage(Base):
    __tablename__ = "deploy_batch_stages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 배포차수 1~5 (engines/deploy_batch.py의 DEPLOY_BATCH_NUMBERS)
    batch_no: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    # 기준 검토 단계 — preliminary / supplement_1 ~ supplement_5
    phase: Mapped[str] = mapped_column(String(30))
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
