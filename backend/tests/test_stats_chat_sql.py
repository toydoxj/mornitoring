"""통계 분석 챗봇 SQL 안전 계층 테스트.

LLM이 만든 SQL을 그대로 실행하는 구조이므로, 정책을 벗어난 SQL이 하나라도
통과하면 사고로 직결된다. 허용/거부 양쪽을 모두 고정해 둔다.
"""

import pytest
from sqlalchemy import text

from services.stats_chat_sql import (
    SqlNotAllowed,
    run_select,
    validate_sql,
)


ALLOWED_QUERIES = [
    "SELECT sido, COUNT(*) AS cnt FROM buildings GROUP BY sido",
    "WITH x AS (SELECT id, sido FROM buildings) SELECT sido, COUNT(*) FROM x GROUP BY sido",
    (
        "SELECT b.mgmt_no, s.report_submitted_at FROM buildings b "
        "JOIN review_stages s ON s.building_id = b.id WHERE s.phase_order = 0"
    ),
    "SELECT r.group_no, COUNT(*) FROM reviewers r GROUP BY r.group_no ORDER BY 1",
    "SELECT severity, COUNT(*) FROM review_opinion_details GROUP BY severity",
    "SELECT name FROM users WHERE is_active = true",
]

BLOCKED_QUERIES = [
    # 쓰기·DDL
    ("DELETE FROM buildings", "SELECT"),
    ("UPDATE buildings SET sido = 'x'", "SELECT"),
    ("DROP TABLE buildings", "SELECT"),
    ("INSERT INTO buildings (mgmt_no) VALUES ('x')", "SELECT"),
    # 다중 문장
    ("SELECT id FROM buildings; DROP TABLE buildings", "한 문장"),
    # 화이트리스트 밖 테이블
    ("SELECT id FROM audit_logs", "테이블"),
    ("SELECT tablename FROM pg_catalog.pg_tables", "스키마"),
    # 개인정보 컬럼
    ("SELECT email FROM users", "컬럼"),
    ("SELECT u.phone FROM users u", "컬럼"),
    ("SELECT password_hash FROM users", "컬럼"),
    ("SELECT kakao_access_token FROM users", "컬럼"),
    ("SELECT s3_file_key FROM review_stages", "컬럼"),
    # 별표 (블랙리스트 컬럼 우회 방지)
    ("SELECT * FROM users", "*"),
    ("SELECT u.* FROM users u", "*"),
    # 행 전체 참조 / 행 직렬화 (컬럼 이름 없이 차단 컬럼을 빼내는 우회)
    ("SELECT u FROM users u", "행 전체 참조"),
    ("SELECT users FROM users", "행 전체 참조"),
    ("SELECT to_jsonb(u) FROM users u", "행 전체 참조"),
    ("SELECT row_to_json(u) FROM users u", "행 전체 참조"),
    ("SELECT to_jsonb(name) FROM users", "함수"),
    ("SELECT json_agg(name) FROM users", "함수"),
    # 위험 함수
    ("SELECT pg_read_file('/etc/passwd')", "함수"),
    ("SELECT current_setting('is_superuser')", "함수"),
    ("SELECT dblink('x', 'y')", "함수"),
    # 주석으로 함수명 검사를 피하려는 시도
    ("SELECT pg_read_file/**/('/etc/passwd')", "함수"),
    ("SELECT pg_sleep/**/(10)", "함수"),
    ("SELECT pg_advisory_lock/**/(123)", "함수"),
    # 결과 크기를 폭발시키는 함수
    ("SELECT repeat(mgmt_no, 100000) FROM buildings", "함수"),
    # CTE 이름으로 화이트리스트를 우회하려는 시도
    (
        "WITH audit_logs AS (SELECT before_data FROM public.audit_logs) "
        "SELECT before_data FROM audit_logs",
        "테이블",
    ),
    # 안쪽 CTE 이름으로 바깥의 금지 테이블을 가리려는 시도
    (
        "SELECT id FROM audit_logs "
        "WHERE EXISTS (WITH audit_logs AS (SELECT 1 AS x) SELECT x FROM audit_logs)",
        "테이블",
    ),
    # JOIN USING 의 조인 키는 Column 이 아니라 Identifier 로 파싱된다
    (
        "WITH probe AS (SELECT 'a@b.c' AS email) "
        "SELECT u.name FROM users u JOIN probe USING (email)",
        "컬럼",
    ),
    # 스키마를 붙여 허용목록 이름으로 위장하려는 시도
    ("SELECT evil.sum(1) FROM buildings", "스키마"),
    ("SELECT public.count(1) FROM buildings", "스키마"),
]

# 실무에서 자주 쓰는 형태 — 허용목록 때문에 막히면 안 된다.
FUNCTION_HEAVY_QUERIES = [
    "SELECT DATE_TRUNC('month', doc_received_at) AS m, COUNT(*) FROM review_stages GROUP BY 1",
    "SELECT TO_CHAR(doc_received_at, 'YYYY-MM') AS m, COUNT(*) FROM review_stages GROUP BY 1",
    "SELECT EXTRACT(YEAR FROM doc_received_at) AS y, COUNT(*) FROM review_stages GROUP BY 1",
    "SELECT SPLIT_PART(mgmt_no, '-', 2) AS serial FROM buildings",
    "SELECT ROW_NUMBER() OVER (ORDER BY gross_area DESC) AS rn, mgmt_no FROM buildings",
    "SELECT COUNT(*) FILTER (WHERE gross_area > 1000) AS big, COUNT(*) AS total FROM buildings",
    "SELECT CAST(SUBSTRING(mgmt_no FROM 6 FOR 4) AS INTEGER) AS serial FROM buildings",
    "SELECT ROUND(AVG(gross_area)::numeric, 1) FROM buildings",
    "SELECT STRING_AGG(name, ',') FROM users",
    # sqlglot이 Func 노드로 분류하는 연산자들 — 허용목록에서 빠지면 CASE/AND가 막힌다
    (
        "SELECT COUNT(CASE WHEN s.doc_received_at IS NOT NULL "
        "AND s.report_submitted_at IS NOT NULL THEN 1 END) FROM review_stages s"
    ),
    (
        "SELECT sido FROM buildings WHERE gross_area BETWEEN 100 AND 200 "
        "AND sido IN ('서울특별시') AND building_name LIKE 'A%'"
    ),
    "SELECT sido || '-' || sigungu AS addr FROM buildings",
    (
        "SELECT b.mgmt_no FROM buildings b "
        "WHERE EXISTS (SELECT 1 FROM review_stages s WHERE s.building_id = b.id)"
    ),
    # BOOL_OR/BOOL_AND 는 sqlglot 에서 LOGICAL_OR/LOGICAL_AND 로 정규화된다
    "SELECT sido, BOOL_OR(is_high_rise) FROM buildings GROUP BY sido",
    "SELECT sido, BOOL_AND(is_multi_use) FROM buildings GROUP BY sido",
    # CTE 이름이 실제 테이블 이름과 같아도 스코프상 CTE를 가리키므로 허용된다
    "WITH users AS (SELECT 1 AS x) SELECT x FROM users",
]


@pytest.mark.parametrize("sql", ALLOWED_QUERIES)
def test_allowed_queries_pass(sql):
    assert validate_sql(sql)


@pytest.mark.parametrize("sql", FUNCTION_HEAVY_QUERIES)
def test_common_functions_are_allowed(sql):
    """허용목록이 통계 집계에 필요한 기본 함수를 막지 않는지 확인한다."""
    assert validate_sql(sql)


@pytest.mark.parametrize("sql,keyword", BLOCKED_QUERIES)
def test_blocked_queries_rejected(sql, keyword):
    with pytest.raises(SqlNotAllowed) as exc:
        validate_sql(sql)
    assert keyword in str(exc.value)


def test_count_star_is_allowed():
    """`*` 는 막되 COUNT(*) 는 통과해야 한다."""
    assert "COUNT(*)" in validate_sql("SELECT COUNT(*) FROM buildings").upper()


def test_empty_sql_rejected():
    with pytest.raises(SqlNotAllowed):
        validate_sql("   ")


def test_run_select_enforces_row_limit(engine):
    """LIMIT 을 강제로 씌워 지정 행수 이상은 돌려주지 않는다."""
    with engine.begin() as conn:
        for i in range(5):
            conn.execute(
                text("INSERT INTO buildings (mgmt_no, sido) VALUES (:m, :s)"),
                {"m": f"2026-{i:04d}", "s": "서울특별시"},
            )

    result = run_select(
        "SELECT mgmt_no FROM buildings ORDER BY mgmt_no",
        row_limit=3,
        db_engine=engine,
    )
    assert result["row_count"] == 3
    assert result["truncated"] is True
    assert result["columns"] == ["mgmt_no"]


def test_run_select_serializes_values(engine):
    """Decimal·date 등이 JSON 직렬화 가능한 값으로 바뀐다."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO buildings (mgmt_no, gross_area, created_at) "
                "VALUES ('2026-9999', 1234.56, '2026-01-02 03:04:05')"
            )
        )

    result = run_select(
        "SELECT gross_area, created_at FROM buildings WHERE mgmt_no = '2026-9999'",
        db_engine=engine,
    )
    area, created = result["rows"][0]
    assert isinstance(area, float)
    assert isinstance(created, str)


def test_run_select_rejects_write_before_execution(engine):
    """실행 단계까지 가지 않고 검증에서 막힌다."""
    with pytest.raises(SqlNotAllowed):
        run_select("DELETE FROM buildings", db_engine=engine)
