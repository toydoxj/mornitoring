"""통계 챗봇 스키마 사전의 업무 규칙 (issues #11-③)."""
from services.stats_chat_schema import build_system_prompt

HIGH_RISK_COLUMNS = ("is_special_structure", "is_high_rise", "is_multi_use", "is_quasi_multi_use")


def _high_risk_rule() -> str:
    prompt = build_system_prompt(max_sql_calls=5, row_limit=100)
    start = prompt.index("5. **고위험 건물**")
    return prompt[start:prompt.index("6. **연면적", start)]


def test_high_risk_rule_lists_four_attributes():
    rule = _high_risk_rule()
    assert all(column in rule for column in HIGH_RISK_COLUMNS)


def test_high_risk_rule_does_not_use_high_risk_type_as_criterion():
    assert "high_risk_type 열은 참고용" in _high_risk_rule()
