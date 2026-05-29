"""검토서 상세의견/심각도 파싱 회귀 테스트."""

from openpyxl import Workbook

from engines.review_extractor import extract_review_data
from engines.review_validator import validate_review_file


def _make_workbook(path, *, missing_severity: bool = False) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "검토서 (1차)"
    ws["C4"] = "2026-0001"
    ws["F4"] = "이공우"
    ws["H4"] = "재계산"
    ws["C5"] = "1차 적정성 검토"
    ws["D17"] = "상세의견"
    ws["H17"] = "심각도"

    ws["B33"] = "2. 부재 설계 적정성"
    ws["C33"] = "구조설계 요소"
    ws["D33"] = "전이보 스트럽 간격 보완할 것."
    ws["H33"] = "2"
    ws["D34"] = "동결심도 깊이에 대한 단면 상세 자료 추가 보완할 것"
    if not missing_severity:
        ws["H34"] = "L3"

    ws["B78"] = "기타의견"
    ws["D78"] = "지반조사서 누락되었으니 보완 바람."
    ws["H78"] = "0"

    ws["B81"] = "적정성 검토 결과"
    ws["D81"] = "기존 수식 요약 텍스트"
    ws["F83"] = "판정결과 부적합 유형"
    ws["G83"] = "기타오류"
    wb.save(path)


def test_validate_review_file_builds_opinion_from_detail_rows(tmp_path):
    path = tmp_path / "2026-0001.xlsm"
    _make_workbook(path)

    result = validate_review_file(
        path,
        filename="2026-0001.xlsm",
        expected_mgmt_no="2026-0001",
        submitter_name="이공우",
        expected_phase="preliminary",
    )

    assert result.is_valid is True
    assert result.extracted_data["review_opinion"] == (
        "[부재설계의 적정성 - 구조설계 요소]\n"
        "{L2} 전이보 스트럽 간격 보완할 것.\n"
        "{L3} 동결심도 깊이에 대한 단면 상세 자료 추가 보완할 것\n\n"
        "[기타의견]\n"
        "{L0} 지반조사서 누락되었으니 보완 바람."
    )
    assert result.extracted_data["severity_counts"] == {
        "L0": 1,
        "L1": 0,
        "L2": 1,
        "L3": 1,
        "L4": 0,
    }

    extracted = extract_review_data(path)
    assert extracted["review_opinion"] == result.extracted_data["review_opinion"]
    assert extracted["severity_counts"]["L3"] == 1


def test_validate_review_file_rejects_detail_without_severity(tmp_path):
    path = tmp_path / "2026-0001.xlsm"
    _make_workbook(path, missing_severity=True)

    result = validate_review_file(
        path,
        filename="2026-0001.xlsm",
        expected_mgmt_no="2026-0001",
        submitter_name="이공우",
        expected_phase="preliminary",
    )

    assert result.is_valid is False
    assert any("34행의 심각도" in error for error in result.errors)
