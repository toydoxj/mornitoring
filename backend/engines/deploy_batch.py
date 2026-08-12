"""배포차수 판별 — 관리번호 일련번호 구간으로 설계도서 배포 배치를 구분한다.

관리번호는 `YYYY-NNNN` 형식(연도 4자리 + '-' + 일련번호 4자리 제로패딩)이며,
배포차수는 연도와 무관하게 **일련번호 구간**으로만 결정된다.

주의: 여기서 말하는 "배포차수"는 예비검토/보완 1~5차를 뜻하는 `ReviewStage`의
차수(`PhaseType`)와 전혀 다른 개념이다. 설계도서를 몇 번째 배치로 내려보냈는지를
가리킨다.
"""

from sqlalchemy import and_, case, func

# (배포차수, 일련번호 시작, 일련번호 끝) — 끝이 None이면 상한 없음
DEPLOY_BATCH_RANGES: tuple[tuple[int, int, int | None], ...] = (
    (1, 1, 262),
    (2, 263, 362),
    (3, 363, 2668),
    (4, 2669, 5046),
    (5, 5047, None),   # 5차수 이후 — 현재 미접수
)

DEPLOY_BATCH_NUMBERS: tuple[int, ...] = tuple(no for no, _, _ in DEPLOY_BATCH_RANGES)

# 관리번호 정규 형식(`YYYY-NNNN`) 기준값
MGMT_NO_LENGTH = 9
MGMT_NO_SERIAL_START = 6   # SQL substr은 1-based — 6번째 문자부터가 일련번호
MGMT_NO_SERIAL_WIDTH = 4


def parse_mgmt_serial(mgmt_no: str | None) -> int | None:
    """관리번호에서 일련번호(정수)를 추출. 정규 형식이 아니면 None."""
    if not mgmt_no:
        return None
    parts = str(mgmt_no).split("-")
    if len(parts) != 2:
        return None
    year, serial = parts
    if not (year.isdigit() and len(year) == 4):
        return None
    if not (serial.isdigit() and len(serial) == MGMT_NO_SERIAL_WIDTH):
        return None
    return int(serial)


def deploy_batch_of(mgmt_no: str | None) -> int | None:
    """관리번호 → 배포차수(1~5). 정규 형식이 아니거나 구간 밖이면 None."""
    serial = parse_mgmt_serial(mgmt_no)
    if serial is None:
        return None
    for batch_no, start, end in DEPLOY_BATCH_RANGES:
        if serial >= start and (end is None or serial <= end):
            return batch_no
    return None


def deploy_batch_label(batch_no: int | None) -> str:
    """배포차수 표시 라벨."""
    return f"{batch_no}차수" if batch_no else "미분류"


def _serial_col(mgmt_no_col):
    """관리번호 컬럼에서 일련번호 부분만 잘라내는 SQL 표현식.

    SQLite/PostgreSQL 공통으로 동작하도록 `substr`만 사용한다. 일련번호가
    4자리 제로패딩이므로 문자열 사전순 비교가 곧 숫자 크기 비교가 된다.
    """
    return func.substr(mgmt_no_col, MGMT_NO_SERIAL_START, MGMT_NO_SERIAL_WIDTH)


def _is_standard_mgmt_no(mgmt_no_col):
    """`YYYY-NNNN` 정규 형식인지 확인하는 SQL 조건.

    길이와 구분자 위치만 검사한다. 정규식은 SQLite에서 쓸 수 없어 제외했다.
    """
    return and_(
        func.length(mgmt_no_col) == MGMT_NO_LENGTH,
        func.substr(mgmt_no_col, 5, 1) == "-",
    )


def deploy_batch_filter(mgmt_no_col, batch_no: int):
    """특정 배포차수만 남기는 SQL 조건. 알 수 없는 차수면 ValueError."""
    for no, start, end in DEPLOY_BATCH_RANGES:
        if no != batch_no:
            continue
        serial = _serial_col(mgmt_no_col)
        if end is None:
            range_cond = serial >= f"{start:0{MGMT_NO_SERIAL_WIDTH}d}"
        else:
            range_cond = serial.between(
                f"{start:0{MGMT_NO_SERIAL_WIDTH}d}",
                f"{end:0{MGMT_NO_SERIAL_WIDTH}d}",
            )
        return and_(_is_standard_mgmt_no(mgmt_no_col), range_cond)
    raise ValueError(f"알 수 없는 배포차수: {batch_no}")


def deploy_batch_expr(mgmt_no_col):
    """배포차수를 계산하는 SQL 표현식 (정렬/GROUP BY용). 구간 밖이면 NULL."""
    return case(
        *[
            (deploy_batch_filter(mgmt_no_col, no), no)
            for no in DEPLOY_BATCH_NUMBERS
        ],
        else_=None,
    )
