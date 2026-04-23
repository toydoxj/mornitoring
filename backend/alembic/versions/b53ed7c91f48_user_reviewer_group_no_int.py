"""사용자/검토위원 조 컬럼 추가 + Reviewer.group_no 정수 변환

Revision ID: b53ed7c91f48
Revises: aa0a2a8c5bf9
Create Date: 2026-04-23 16:00:00.000000

- users 테이블에 group_no(Integer, nullable, 1~7 CHECK) 추가
- reviewers.group_no 를 String(10) → Integer 로 변환
  - 비숫자/공백값은 NULL 로 정리 후 ALTER TYPE
- 두 테이블 모두 1~7 범위 CHECK 제약 추가

PostgreSQL 외(SQLite 테스트) 환경에서는 ALTER TYPE/CHECK 처리가 제한적이라
호환 분기를 둔다. SQLite는 batch_alter_table 로 컬럼 재생성.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b53ed7c91f48'
down_revision: Union[str, Sequence[str], None] = 'aa0a2a8c5bf9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    # 1) users.group_no 컬럼 추가 + CHECK
    op.add_column('users', sa.Column('group_no', sa.Integer(), nullable=True))
    op.create_check_constraint(
        'ck_users_group_no_range',
        'users',
        'group_no IS NULL OR (group_no >= 1 AND group_no <= 7)',
    )

    # 2) reviewers.group_no 를 정수로 변환
    if _is_postgres():
        # 비숫자값은 NULL 로 정리 (운영 데이터 안전 캐스팅)
        op.execute(
            "UPDATE reviewers SET group_no = NULL "
            "WHERE group_no IS NOT NULL AND TRIM(group_no) !~ '^[0-9]+$'"
        )
        op.execute(
            "UPDATE reviewers SET group_no = NULL "
            "WHERE group_no IS NOT NULL AND TRIM(group_no) = ''"
        )
        op.execute(
            "ALTER TABLE reviewers "
            "ALTER COLUMN group_no TYPE INTEGER "
            "USING NULLIF(TRIM(group_no), '')::integer"
        )
    else:
        # SQLite (테스트) — batch 모드로 컬럼 재생성
        with op.batch_alter_table('reviewers') as batch:
            batch.alter_column(
                'group_no',
                existing_type=sa.String(length=10),
                type_=sa.Integer(),
                existing_nullable=True,
                postgresql_using='NULLIF(TRIM(group_no), \'\')::integer',
            )

    # 3) 안전장치: 1~7 외 정수가 남아 있으면 NULL 로 정리 후 CHECK 추가
    #    (CHECK 추가 시점에 위반 행이 있으면 ALTER 가 실패)
    op.execute(
        "UPDATE reviewers SET group_no = NULL "
        "WHERE group_no IS NOT NULL AND (group_no < 1 OR group_no > 7)"
    )
    op.create_check_constraint(
        'ck_reviewers_group_no_range',
        'reviewers',
        'group_no IS NULL OR (group_no >= 1 AND group_no <= 7)',
    )


def downgrade() -> None:
    op.drop_constraint('ck_reviewers_group_no_range', 'reviewers', type_='check')
    if _is_postgres():
        op.execute(
            "ALTER TABLE reviewers "
            "ALTER COLUMN group_no TYPE VARCHAR(10) "
            "USING group_no::text"
        )
    else:
        with op.batch_alter_table('reviewers') as batch:
            batch.alter_column(
                'group_no',
                existing_type=sa.Integer(),
                type_=sa.String(length=10),
                existing_nullable=True,
            )

    op.drop_constraint('ck_users_group_no_range', 'users', type_='check')
    op.drop_column('users', 'group_no')
