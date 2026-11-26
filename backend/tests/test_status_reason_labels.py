"""화면이 사유 문구로 표시하는 상태값이 '일치'·'동의'로 분류되지 않는지 확인한다.

프론트엔드 라벨(비교 불가(보완대장 제출 기록 없음), 비교 불가(로그인 UUID 없음))은
아래 분기 결과에 붙는다. 분기가 바뀌면 라벨의 사유도 다시 맞춰야 한다.
"""
from types import SimpleNamespace

from engines.ledger_phase_compare import _resolve_excel_phase, _status_for
from services.kakao import get_kakao_identity_status


def test_blank_supplement_row_has_no_excel_phase():
    result = _resolve_excel_phase(tuple([None] * 60))
    assert result["phase"] is None


def test_missing_excel_phase_is_not_matched():
    building = SimpleNamespace(current_phase="supplement_1")
    assert _status_for(building, None) == "excel_phase_missing"


def test_missing_db_building_is_reported_separately():
    assert _status_for(None, None) == "missing_db"


def test_identity_without_login_uuid_is_unknown_not_matched():
    user = SimpleNamespace(kakao_id="1", kakao_uuid="friend-uuid", kakao_login_uuid=None)
    assert get_kakao_identity_status(user) == "unknown"
