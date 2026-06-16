from openpyxl import Workbook

from engines.ledger_import_selection import import_ledger_selection
from models.building import Building
from routers.ledger import _detect_format


def test_detect_format_selection_result(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "3차수 대상선정"
    ws.append(["관리번호", None, "건축구분", "시도명"])
    ws.append(["2026-0363", "강정임", "신축", "강원특별자치도"])
    path = tmp_path / "selection.xlsx"
    wb.save(path)

    assert _detect_format(path) == "selection"


def test_import_ledger_selection_reads_header_based_format(db_session, tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "3차수 대상선정"
    ws.append([
        "관리번호",
        None,
        "건축구분",
        "대장구분",
        "시도명",
        "시군구명",
        "법정동명",
        "대지구분",
        "본번",
        "부번",
        "특수지번",
        "건물명",
        "연면적",
        "주구조",
        "기타구조",
        "주용도",
        "기타용도",
        "주지붕",
        "기타지붕",
        "높이",
        "지상층수",
        "지하층수",
        "설계자",
        "설계사무소",
        "공사(건물)명",
        "특수구조물 여부",
        "고층",
        "다중이용",
        "고위험",
        "준다중이용",
    ])
    ws.append([
        "2026-0363",
        "강정임",
        "신축",
        "일반",
        "강원특별자치도",
        "평창군",
        "미탄면 회동리",
        "대지",
        "1",
        "1",
        None,
        "은하수전망대 주건축물제1동",
        "639.63",
        "철골철근콘크리트구조",
        "철골철근콘크리트조",
        "관광휴게시설",
        None,
        "(철근)콘크리트",
        None,
        "13.15",
        "1",
        "0",
        "주식회사네임리스건축사사무소",
        "(주) 네임리스 건축사사무소",
        "은하수전망대",
        "O",
        None,
        None,
        "O",
        "O",
    ])
    path = tmp_path / "selection.xlsx"
    wb.save(path)

    result = import_ledger_selection(path, db_session)

    assert result == {
        "imported": 1,
        "skipped": 0,
        "errors": [],
        "sheet": "3차수 대상선정",
    }
    building = db_session.query(Building).filter_by(mgmt_no="2026-0363").one()
    assert building.building_type == "신축"
    assert building.sido == "강원특별자치도"
    assert building.sigungu == "평창군"
    assert float(building.gross_area) == 639.63
    assert float(building.height) == 13.15
    assert building.floors_above == 1
    assert building.floors_below == 0
    assert building.architect_name == "주식회사네임리스건축사사무소"
    assert building.architect_firm == "(주) 네임리스 건축사사무소"
    assert building.remarks == "은하수전망대"
    assert building.is_special_structure is True
    assert building.is_high_rise is None
    assert building.is_multi_use is None
    assert building.is_quasi_multi_use is True
    assert building.high_risk_type == "고위험"
