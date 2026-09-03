"""검토의견 조합 라벨(대상 x 문제유형) 저장 모델.

라벨은 원문이 아니라 규칙 사전·분류체계·LLM 모델 버전에 따라 다시 만들 수 있는
파생 데이터다. 그래서 ReviewOpinionDetail 에 컬럼을 붙이지 않고 별도 테이블로
분리해 재처리·실패 상태·감사 이력을 원본과 독립적으로 관리한다.

검토서 재업로드 시 상세의견 행이 삭제 후 재생성되므로(routers/reviews.py의
`_apply_opinion_details`) FK에 ON DELETE CASCADE 를 두어 오래된 라벨이 함께
정리되도록 한다.
"""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

# secondary_target / aspect 가 없을 때 쓰는 값.
# NULL 로 두면 PostgreSQL·SQLite 모두 유니크 제약에서 NULL 을 서로 다른 값으로 봐서
# 같은 조합이 중복 저장된다. 빈 문자열로 통일해 유니크 제약이 실제로 걸리게 한다.
NO_SECONDARY_TARGET = ""
NO_ASPECT = ""

# 라벨 출처.
LABEL_SOURCE_RULE = "rule"      # 정규식 규칙 사전
LABEL_SOURCE_LLM = "llm"        # LLM 보완 라벨
LABEL_SOURCE_MANUAL = "manual"  # 사람이 직접 교정

# 라벨 작업 상태.
RUN_STATUS_PENDING = "pending"      # LLM 처리 대기
RUN_STATUS_RUNNING = "running"      # 워커가 선점해 처리 중
RUN_STATUS_COMPLETED = "completed"  # 처리 완료(라벨이 없다는 결론도 완료다)
RUN_STATUS_FAILED = "failed"        # 최대 시도 초과


class OpinionCombinationLabel(Base):
    """상세의견 한 건에 붙은 조합 라벨 한 개.

    `A↔B 불일치`처럼 두 대상 사이의 관계인 라벨은 secondary_target 에 상대 대상을
    담는다. 단일 대상 라벨은 NO_SECONDARY_TARGET("")을 넣는다.

    aspect 는 대상의 어느 국면인지를 담는다(예: 내진설계 > 저항시스템).
    잡히지 않으면 NO_ASPECT("")다.
    """

    __tablename__ = "opinion_combination_labels"
    __table_args__ = (
        UniqueConstraint(
            "detail_id",
            "primary_target",
            "secondary_target",
            "aspect",
            "issue_type",
            name="uq_opinion_combination_label",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    detail_id: Mapped[int] = mapped_column(
        ForeignKey("review_opinion_details.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    primary_target: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    secondary_target: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=NO_SECONDARY_TARGET,
        server_default="",
    )
    # 세부항목 — 대상의 어느 국면이 문제인지. 없으면 빈 문자열.
    # "내진설계 재검토요망"만으로는 무엇을 다시 보라는 것인지 알 수 없어서 둔다.
    aspect: Mapped[str] = mapped_column(
        String(30),
        index=True,
        nullable=False,
        default=NO_ASPECT,
        server_default="",
    )
    issue_type: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    source: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default=LABEL_SOURCE_RULE,
        server_default=LABEL_SOURCE_RULE,
    )
    # 이 라벨을 만든 시점의 버전. 사전이 바뀌면 재계산 대상을 이 값으로 골라낸다.
    ruleset_version: Mapped[str | None] = mapped_column(String(20))
    taxonomy_version: Mapped[str | None] = mapped_column(String(20))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    detail = relationship("ReviewOpinionDetail")


class OpinionLabelRun(Base):
    """상세의견 한 건에 대한 라벨링 작업 이력.

    규칙만으로 조합이 나오지 않은 건을 pending 으로 등록해 두면 LLM 워커가
    선점해 처리한다. 같은 입력으로 두 번 호출하지 않도록 (detail_id, input_hash)
    를 유니크로 잡는다.
    """

    __tablename__ = "opinion_label_runs"
    __table_args__ = (
        UniqueConstraint("detail_id", "input_hash", name="uq_opinion_label_run_input"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    detail_id: Mapped[int] = mapped_column(
        ForeignKey("review_opinion_details.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # LLM 판단에 사용한 입력 전체(원문 + 규칙 결과 + 분류체계)의 sha256.
    # 원문만 해싱하면 규칙 결과가 바뀌어도 캐시가 갱신되지 않는다.
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    ruleset_version: Mapped[str | None] = mapped_column(String(20))
    taxonomy_version: Mapped[str | None] = mapped_column(String(20))
    llm_contract_version: Mapped[str | None] = mapped_column(String(20))
    requested_model: Mapped[str | None] = mapped_column(String(60))
    resolved_model: Mapped[str | None] = mapped_column(String(60))

    status: Mapped[str] = mapped_column(
        String(12),
        index=True,
        nullable=False,
        default=RUN_STATUS_PENDING,
        server_default=RUN_STATUS_PENDING,
    )
    # 규칙이 조합을 못 만든 이유(no_target / no_issue / no_target_issue / no_link).
    unmatched_reason: Mapped[str | None] = mapped_column(String(20), index=True)
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    error: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    detail = relationship("ReviewOpinionDetail")
