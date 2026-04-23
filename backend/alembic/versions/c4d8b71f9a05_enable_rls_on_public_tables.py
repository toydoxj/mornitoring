"""Supabase RLS: public 스키마 모든 테이블에 RLS ENABLE + FORCE

Revision ID: c4d8b71f9a05
Revises: a91c5e3d22f0
Create Date: 2026-04-23 00:00:00.000000

Supabase 프로젝트는 PostgREST를 통해 public 스키마 테이블을 anon/authenticated
역할로 자동 노출한다. 우리 백엔드는 슈퍼유저(postgres, BYPASSRLS) 로 직접
연결하므로 RLS 자체에는 영향을 받지 않지만, RLS가 꺼진 테이블은 anon key 만으로
외부 PostgREST 호출로 CRUD 가능해 위험하다.

이 마이그레이션은 idempotent 하게 모든 public 테이블에 RLS 를 켜고 FORCE 한다.
신규 테이블에 대한 자동 적용은 `alembic/env.py` 의 post-upgrade 훅에서 처리.

PostgreSQL 외 dialect(테스트용 SQLite 등)에서는 no-op.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'c4d8b71f9a05'
down_revision: Union[str, Sequence[str], None] = 'a91c5e3d22f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# `pg_class` 직접 조회 — 일반 테이블('r')과 partitioned table('p') 모두 포함.
# (`pg_tables` 뷰는 partitioned 부모 테이블이 누락될 수 있어 사용하지 않음)
_ENABLE_RLS_SQL = """
DO $$
DECLARE r RECORD;
BEGIN
    FOR r IN
        SELECT c.relname AS tablename
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind IN ('r', 'p')
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY;', r.tablename);
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY;', r.tablename);
    END LOOP;
END$$;
"""


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind is not None and bind.dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute(_ENABLE_RLS_SQL)


def downgrade() -> None:
    """일괄 RLS 해제는 보안 사고와 직결되므로 자동 downgrade를 막는다.

    되돌리려면 운영자가 의도적으로 SQL을 실행해야 한다 (operations-policy.md 참고).
    """
    raise NotImplementedError(
        "RLS 해제는 자동 downgrade로 수행하지 않는다. operations-policy.md의 비상 절차 참고."
    )
