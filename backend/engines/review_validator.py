"""검토서 유효성 검증 엔진

3종 검증:
1. 파일명이 관리번호 형식인지 (예: 2026-0001.xlsm)
2. 파일 내부 관리번호와 파일명 관리번호 일치
3. 파일 내부 검토자 이름과 로그인 사용자 이름 일치
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import load_workbook


@dataclass
class ValidationResult:
    is_valid: bool = True
    mgmt_no: str = ""
    reviewer_name: str = ""
    errors: list[str] = field(default_factory=list)

    def add_error(self, msg: str):
        self.errors.append(msg)
        self.is_valid = False


# 검토서 내부 셀 위치 (설정으로 분리하여 양식 변경 대응)
# 실제 양식 확인 후 조정 필요
REVIEW_CELL_CONFIG = {
    "mgmt_no_cell": "B2",        # 관리번호 셀 위치
    "reviewer_name_cell": "B3",  # 검토자 이름 셀 위치
}

# 관리번호 패턴: YYYY-NNNN
MGMT_NO_PATTERN = re.compile(r"^\d{4}-\d{4}$")


def extract_mgmt_no_from_filename(filename: str) -> str | None:
    """파일명에서 관리번호를 추출

    지원 형식:
    - 2026-0001.xlsm
    - 2026-0001.xlsx
    - 2026-0001_홍길동.xlsm
    """
    stem = Path(filename).stem  # 확장자 제거
    # 언더스코어로 분리하여 첫 부분이 관리번호인지 확인
    parts = stem.split("_")
    candidate = parts[0].strip()
    if MGMT_NO_PATTERN.match(candidate):
        return candidate
    return None


def validate_review_file(
    file_path: str | Path,
    filename: str,
    expected_mgmt_no: str | None,
    submitter_name: str,
) -> ValidationResult:
    """검토서 파일 유효성 검증

    Args:
        file_path: 업로드된 파일의 로컬 경로
        filename: 원본 파일명
        expected_mgmt_no: URL에서 전달된 관리번호 (선택)
        submitter_name: 로그인 사용자 이름

    Returns:
        ValidationResult
    """
    result = ValidationResult()

    # 1단계: 파일 확장자 검증
    suffix = Path(filename).suffix.lower()
    if suffix not in (".xlsm", ".xlsx", ".xls"):
        result.add_error(f"지원하지 않는 파일 형식입니다: {suffix} (xlsm/xlsx만 가능)")
        return result

    # 2단계: 파일명에서 관리번호 추출
    file_mgmt_no = extract_mgmt_no_from_filename(filename)
    if not file_mgmt_no:
        result.add_error(
            f"파일명에서 관리번호를 인식할 수 없습니다: '{filename}'. "
            "파일명은 '관리번호.xlsm' 또는 '관리번호_검토자.xlsm' 형식이어야 합니다."
        )
        return result

    result.mgmt_no = file_mgmt_no

    # URL의 관리번호와 파일명 관리번호 비교
    if expected_mgmt_no and file_mgmt_no != expected_mgmt_no:
        result.add_error(
            f"파일명의 관리번호({file_mgmt_no})가 "
            f"검토 대상 관리번호({expected_mgmt_no})와 일치하지 않습니다."
        )

    # 3단계: 파일 내부 검증
    try:
        wb = load_workbook(str(file_path), data_only=True, read_only=True)
        ws = wb.active
        if ws is None:
            result.add_error("엑셀 파일에 시트가 없습니다.")
            wb.close()
            return result

        # 내부 관리번호 읽기
        internal_mgmt_no_cell = ws[REVIEW_CELL_CONFIG["mgmt_no_cell"]]
        internal_mgmt_no = str(internal_mgmt_no_cell.value).strip() if internal_mgmt_no_cell.value else None

        if internal_mgmt_no and MGMT_NO_PATTERN.match(internal_mgmt_no):
            if internal_mgmt_no != file_mgmt_no:
                result.add_error(
                    f"검토서 내부 관리번호({internal_mgmt_no})가 "
                    f"파일명의 관리번호({file_mgmt_no})와 일치하지 않습니다."
                )

        # 내부 검토자 이름 읽기
        internal_reviewer_cell = ws[REVIEW_CELL_CONFIG["reviewer_name_cell"]]
        internal_reviewer = str(internal_reviewer_cell.value).strip() if internal_reviewer_cell.value else None
        result.reviewer_name = internal_reviewer or ""

        if internal_reviewer and internal_reviewer != submitter_name:
            result.add_error(
                f"검토서 내부 검토자({internal_reviewer})가 "
                f"로그인 사용자({submitter_name})와 일치하지 않습니다."
            )

        wb.close()

    except Exception as e:
        result.add_error(f"엑셀 파일을 읽는 중 오류가 발생했습니다: {str(e)}")

    return result
