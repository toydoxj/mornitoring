import sys
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, text
from sqlalchemy import pool

from alembic import context

# backend 디렉터리를 sys.path에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from database import Base
from config import settings
import models  # 모든 모델 import

config = context.config
# %를 %%로 이스케이프하여 configparser 호환
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


_ENSURE_RLS_SQL = """
DO $$
DECLARE r RECORD;
BEGIN
    FOR r IN
        SELECT c.relname AS tablename
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind IN ('r', 'p')
          AND (c.relrowsecurity = false OR c.relforcerowsecurity = false)
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY;', r.tablename);
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY;', r.tablename);
    END LOOP;
END$$;
"""


def _ensure_rls_on_public_tables(connection) -> None:
    """upgrade 직후 호출: PostgreSQL이면 신규/누락 테이블에 RLS를 idempotent하게 적용.

    `c4d8b71f9a05` 마이그레이션이 한 번 적용되면 이후 새 테이블은 이 훅이
    자동으로 ENABLE+FORCE 한다. SQLite 등 다른 dialect에서는 no-op.

    트랜잭션: `connection.begin()` 으로 별도 트랜잭션을 시작해 ALTER 결과가
    확실히 commit 되게 한다 (alembic 의 begin_transaction 블록 종료 후 호출되어
    autocommit 보장 없음).

    실패 정책: 기본은 stderr 경고만 남기고 마이그레이션 흐름은 유지한다.
    운영에서 보안 드리프트를 즉시 알아채려면 환경변수 `STRICT_RLS_HOOK=1` 설정 시
    예외를 그대로 raise 하여 deploy 를 실패시킨다. 운영자는 별도 점검 SQL로도
    상태를 확인할 수 있다 (`.doc/operations-policy.md` 참고).
    """
    if connection.dialect.name != "postgresql":
        return
    strict = os.environ.get("STRICT_RLS_HOOK", "").strip() in ("1", "true", "True")
    try:
        with connection.begin():
            # text()로 감싸 SQLAlchemy 2.x의 빈 parameters 처리(immutabledict) 이슈 회피.
            connection.execute(text(_ENSURE_RLS_SQL))
    except Exception as exc:
        msg = f"[alembic post-upgrade] RLS 자동 적용 실패: {exc}"
        if strict:
            raise
        import sys
        print(msg, file=sys.stderr)


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )
        with context.begin_transaction():
            context.run_migrations()
        # 마이그레이션이 끝난 뒤 신규 테이블 RLS 보장 (Supabase 보안)
        _ensure_rls_on_public_tables(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
