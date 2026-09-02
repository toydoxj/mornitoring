"""통계 분석 챗봇의 SQL 안전 계층.

LLM이 생성한 SQL을 그대로 실행하지 않는다. 실행 전에 sqlglot 으로 파싱해
AST 수준에서 다음을 모두 만족하는지 검사하고, 하나라도 어긋나면 거부한다.

  1. 문장이 정확히 1개이고 SELECT(또는 WITH ... SELECT / UNION)일 것
  2. 참조 테이블이 화이트리스트 안에 있을 것
     (CTE 별칭은 예외지만, 실제 테이블 이름과 같은 CTE 이름은 금지 — 그렇지
      않으면 `WITH audit_logs AS (...)` 로 화이트리스트를 통째로 우회할 수 있다)
  3. 개인정보·자격증명 컬럼을 건드리지 않을 것
  4. `*` 와 행 전체 참조(`SELECT u FROM users u`)를 쓰지 않을 것
     (COUNT(*) 만 허용) — 컬럼 블랙리스트 우회 방지
  5. 함수는 허용목록(ALLOWED_FUNCTIONS)에 있는 것만 호출할 것.
     블랙리스트는 주석 삽입(`pg_sleep/**/(1)`)으로 뚫려서 허용목록으로 뒤집었다.

검증을 통과한 SQL도 그대로 실행하지 않고 `SELECT * FROM (...) LIMIT n` 으로
한 번 감싸 행수를 강제 제한하며, READ ONLY 트랜잭션과 statement_timeout 안에서
실행한 뒤 항상 롤백한다. 결과는 셀 길이·전체 크기도 함께 잘라낸다.
"""

from __future__ import annotations

import datetime as dt
import decimal
import time
from functools import lru_cache
from typing import Any

import sqlglot
from sqlglot import exp
from sqlalchemy import inspect as sa_inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from config import settings
from database import engine as default_engine

# 한 셀에서 모델에 넘길 최대 문자 수. 검토의견 원문이 길어 잘라야 한다.
MAX_CELL_CHARS = 2000
# 한 번의 조회 결과 전체 크기 상한(문자). 넘으면 남은 행을 버리고 truncated 표시.
MAX_RESULT_CHARS = 120_000


class SqlNotAllowed(Exception):
    """정책 위반으로 실행을 거부한 SQL. 메시지는 LLM에게 그대로 돌려준다."""


# 조회를 허용하는 테이블. 여기 없는 테이블은 이름만 등장해도 거부한다.
ALLOWED_TABLES: frozenset[str] = frozenset({
    "buildings",
    "review_stages",
    "review_opinion_details",
    "review_severity_summaries",
    "reviewers",
    "users",
    "inquiries",
    "resubmission_requests",
    "deploy_batch_stages",
})

# 개인정보·자격증명 컬럼. 이름이 같으면 어느 테이블이든 거부한다.
# 검토위원·간사 '이름'은 통계자료 화면에 이미 노출되므로 차단 대상이 아니다.
BLOCKED_COLUMNS: frozenset[str] = frozenset({
    "password_hash",
    "phone",
    "email",
    "kakao_id",
    "kakao_uuid",
    "kakao_login_uuid",
    "kakao_access_token",
    "kakao_refresh_token",
    "kakao_token_expires_at",
    "kakao_scopes_ok",
    "kakao_scopes_checked_at",
    "token",
    "token_hash",
    "access_token",
    "refresh_token",
    "s3_file_key",
    "s3_key",
})

# 호출을 허용하는 함수 (allowlist). 블랙리스트는 주석 삽입(`pg_sleep/**/(1)`)이나
# sqlglot의 이름 변형(json_agg → J_S_O_N_ARRAY_AGG)으로 쉽게 뚫려서, 아는 것만
# 통과시키는 방식으로 뒤집었다. 비교는 `_normalize_func_name` 으로 정규화해서 한다.
# 값은 sqlglot 이 정규화한 이름을 `_normalize_func_name` 으로 변환한 형태다
# (예: DATE_TRUNC → TIMESTAMP_TRUNC → "timestamptrunc").
ALLOWED_FUNCTIONS: frozenset[str] = frozenset({
    # 집계
    "count", "sum", "avg", "min", "max", "stddev", "variance",
    "groupconcat", "percentilecont", "percentiledisc",
    # 수치
    "abs", "round", "ceil", "ceiling", "floor", "trunc", "mod", "power", "sqrt",
    "greatest", "least",
    # NULL 처리·분기
    "coalesce", "nullif", "if", "case",
    # 형변환
    "cast", "trycast", "tonumber", "strtodate", "strtotime", "timetostr",
    # 날짜
    "currentdate", "currenttimestamp", "timestamptrunc", "datetrunc",
    "dateadd", "datediff", "extract", "age",
    # 문자열
    "lower", "upper", "initcap", "length", "substring", "left", "right",
    "trim", "pad", "concat", "concatws", "replace", "split", "splitpart",
    "strposition", "strpos",
    # 창 함수
    "rownumber", "rank", "denserank", "ntile", "lag", "lead",
    "firstvalue", "lastvalue", "percentrank", "cumedist",
    # 기타
    "anyvalue",
    # sqlglot 이 Func 노드로 분류하는 연산자·구문. 호출 가능한 함수가 아니라
    # SQL 문법 요소라서 막으면 CASE/AND 같은 기본 표현식이 전부 걸린다.
    "and", "or", "not", "xor", "exists", "array", "in", "between", "like",
    "is", "paren", "neg", "dpipe",
})

# SELECT 이외의 최상위 표현식은 전부 거부. 아래 노드는 하위에도 나타나면 안 된다.
FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.Grant,
    exp.Command,
    exp.Merge,
    exp.Set,
    exp.Use,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
)


def _cte_aliases(tree: exp.Expression) -> set[str]:
    """WITH 절로 정의된 이름들 — 테이블 화이트리스트 검사에서 제외한다."""
    names: set[str] = set()
    for cte in tree.find_all(exp.CTE):
        alias = cte.alias_or_name
        if alias:
            names.add(alias.lower())
    return names


def _normalize_func_name(name: str) -> str:
    """함수 이름 비교용 정규화.

    sqlglot은 표준 함수를 전용 노드로 바꾸면서 이름 표기를 바꾼다
    (json_agg → `J_S_O_N_ARRAY_AGG`). 소문자로 낮추고 밑줄을 지워 비교한다.
    """
    return name.replace("_", "").lower()


def _func_name(node: exp.Expression) -> str:
    """AST 노드에서 실제 호출 함수 이름을 뽑는다.

    `Anonymous.sql_name()` 은 실제 이름이 아니라 'ANONYMOUS' 를 돌려주므로
    익명 함수는 `this` 에 담긴 원래 식별자를 쓴다.
    """
    if isinstance(node, exp.Anonymous):
        return str(node.this or "")
    return node.sql_name() or ""


@lru_cache(maxsize=1)
def _real_table_names() -> frozenset[str]:
    """DB에 실제로 존재하는 테이블 이름 집합 (프로세스 1회 조회 후 캐시).

    CTE 이름이 실제 테이블 이름과 같으면 화이트리스트 검사를 통째로 우회할 수
    있어(`WITH audit_logs AS (...) SELECT ... FROM audit_logs`), 그런 CTE 이름을
    아예 금지하기 위해 필요하다.
    """
    try:
        names = {name.lower() for name in sa_inspect(default_engine).get_table_names()}
    except SQLAlchemyError:
        # 메타데이터를 못 읽어도 최소한 화이트리스트 테이블 이름은 막는다.
        names = set()
    return frozenset(names | set(ALLOWED_TABLES))


def validate_sql(sql: str) -> str:
    """정책 검사를 통과한 SQL을 정규화해서 돌려준다. 위반 시 SqlNotAllowed."""
    raw = (sql or "").strip().rstrip(";").strip()
    if not raw:
        raise SqlNotAllowed("빈 SQL은 실행할 수 없습니다.")

    try:
        statements = sqlglot.parse(raw, read="postgres")
    except Exception as exc:  # sqlglot 파싱 실패 전반
        raise SqlNotAllowed(f"SQL 구문을 해석하지 못했습니다: {exc}") from exc

    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise SqlNotAllowed("SQL은 SELECT 한 문장만 허용합니다.")

    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.Union, exp.Except, exp.Intersect, exp.Subquery)):
        raise SqlNotAllowed("SELECT 문만 허용합니다. (INSERT/UPDATE/DDL 불가)")

    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise SqlNotAllowed("SELECT 이외의 명령은 허용하지 않습니다.")

    # `*` 금지 — COUNT(*) 등 집계 함수의 인자로 쓰인 Star 만 통과시킨다.
    for star in tree.find_all(exp.Star):
        parent = star.parent
        if not isinstance(parent, (exp.Count, exp.AggFunc)):
            raise SqlNotAllowed(
                "`*` 는 사용할 수 없습니다. 필요한 컬럼을 직접 나열하세요. "
                "(COUNT(*) 는 허용)"
            )

    cte_names = _cte_aliases(tree)
    # CTE 이름이 실제 테이블 이름과 같으면 그 이름의 테이블 참조가 CTE인지 실제
    # 테이블인지 구분할 수 없어 검사가 무력화된다. 그런 이름은 아예 금지한다.
    real_tables = _real_table_names()
    for cte_name in sorted(cte_names):
        if cte_name in real_tables:
            raise SqlNotAllowed(
                f"CTE 이름이 실제 테이블 이름과 같습니다: {cte_name}. "
                "다른 이름을 쓰세요."
            )

    for table in tree.find_all(exp.Table):
        name = (table.name or "").lower()
        if not name:
            continue
        schema = (table.db or "").lower()
        if schema and schema != "public":
            raise SqlNotAllowed(f"허용되지 않는 스키마입니다: {schema}")
        # 스키마를 명시한 참조는 언제나 실제 테이블이므로 CTE로 취급하지 않는다.
        if not schema and name in cte_names:
            continue
        if name not in ALLOWED_TABLES:
            allowed = ", ".join(sorted(ALLOWED_TABLES))
            raise SqlNotAllowed(
                f"조회할 수 없는 테이블입니다: {name}. 허용 테이블: {allowed}"
            )

    # 테이블 자체를 가리키는 이름(별칭 포함) — 아래 whole-row 참조 검사에 쓴다.
    row_refs: set[str] = set(cte_names)
    for table in tree.find_all(exp.Table):
        if table.name:
            row_refs.add(table.name.lower())
        if table.alias:
            row_refs.add(table.alias.lower())

    for column in tree.find_all(exp.Column):
        col_name = (column.name or "").lower()
        if col_name in BLOCKED_COLUMNS:
            raise SqlNotAllowed(f"조회할 수 없는 컬럼입니다: {col_name}")
        # `SELECT u FROM users u` 처럼 행 전체를 참조하면 컬럼 이름을 적지 않고도
        # 차단 컬럼이 통째로 딸려 나온다. 한정자 없는 테이블/별칭 참조를 막는다.
        if not column.table and col_name in row_refs:
            raise SqlNotAllowed(
                f"행 전체 참조(`{col_name}`)는 사용할 수 없습니다. "
                "필요한 컬럼을 직접 나열하세요."
            )

    for func_node in tree.find_all(exp.Func):
        raw_name = _func_name(func_node)
        if _normalize_func_name(raw_name) not in ALLOWED_FUNCTIONS:
            raise SqlNotAllowed(
                f"허용되지 않는 함수입니다: {raw_name or '알 수 없음'}. "
                "집계·문자열·날짜 등 기본 함수만 사용할 수 있습니다."
            )

    return tree.sql(dialect="postgres")


def _wrap_with_limit(sql: str, row_limit: int) -> str:
    """행수를 강제로 제한하는 바깥 SELECT로 감싼다."""
    return f"SELECT * FROM (\n{sql}\n) AS _stats_chat_q LIMIT {int(row_limit)}"


def _clip(text_value: str) -> str:
    """한 셀이 프롬프트를 잠식하지 않도록 길이를 자른다."""
    if len(text_value) <= MAX_CELL_CHARS:
        return text_value
    return text_value[:MAX_CELL_CHARS] + "…(잘림)"


def _to_jsonable(value: Any) -> Any:
    """LLM에 넘길 수 있도록 DB 값을 JSON 직렬화 가능한 형태로 바꾼다."""
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        return _clip(value)
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "<binary>"
    return _clip(str(value))


def run_select(
    sql: str,
    *,
    row_limit: int | None = None,
    timeout_ms: int | None = None,
    db_engine: Engine | None = None,
) -> dict[str, Any]:
    """검증 → 실행 → 직렬화. 항상 롤백하며 커밋하지 않는다.

    반환: {"sql", "columns", "rows", "row_count", "truncated", "duration_ms"}
    """
    limit = row_limit if row_limit is not None else settings.stats_chat_row_limit
    timeout = timeout_ms if timeout_ms is not None else settings.stats_chat_sql_timeout_ms
    eng = db_engine or default_engine

    validated = validate_sql(sql)
    wrapped = _wrap_with_limit(validated, limit)

    started = time.perf_counter()
    try:
        with eng.connect() as conn:
            trans = conn.begin()
            try:
                if conn.dialect.name == "postgresql":
                    # 세션 자체를 읽기 전용으로 고정하고 장시간 쿼리를 끊는다.
                    conn.execute(text("SET TRANSACTION READ ONLY"))
                    conn.execute(text(f"SET LOCAL statement_timeout = {int(timeout)}"))
                result = conn.execute(text(wrapped))
                columns = list(result.keys())
                raw_rows = result.fetchall()
            finally:
                # 조회만 했으므로 어떤 경우에도 커밋하지 않는다.
                trans.rollback()
    except SQLAlchemyError as exc:
        # 원문 예외에는 접속 정보가 섞일 수 있어 첫 줄만 노출한다.
        message = str(getattr(exc, "orig", exc)).strip().splitlines()
        raise SqlNotAllowed(
            f"SQL 실행에 실패했습니다: {message[0] if message else '알 수 없는 오류'}"
        ) from exc
    duration_ms = int((time.perf_counter() - started) * 1000)

    # 행수 상한과 별개로 전체 크기도 제한한다. 셀 하나가 수 MB인 경우
    # (예: repeat(...)) 메모리와 다음 LLM 요청 크기를 동시에 망가뜨린다.
    rows: list[list[Any]] = []
    total_chars = 0
    size_truncated = False
    for raw_row in raw_rows:
        row = [_to_jsonable(v) for v in raw_row]
        total_chars += sum(len(str(v)) for v in row)
        if total_chars > MAX_RESULT_CHARS:
            size_truncated = True
            break
        rows.append(row)

    return {
        "sql": validated,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": size_truncated or len(raw_rows) >= limit,
        "duration_ms": duration_ms,
    }
