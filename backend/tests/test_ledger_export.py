from openpyxl import load_workbook

from engines.ledger_export import export_ledger


def test_export_ledger_marks_related_tech_target_and_cooperation(db_session, make_building):
    target_missing = make_building(mgmt_no="EXPORT-001")
    target_missing.floors_above = 6

    target_done = make_building(mgmt_no="EXPORT-002")
    target_done.is_special_structure = True
    target_done.struct_eng_name = "홍길동"

    not_target = make_building(mgmt_no="EXPORT-003")
    not_target.floors_above = 2

    db_session.commit()

    output = export_ledger(db_session)
    wb = load_workbook(output, data_only=True)
    ws = wb["통합 관리대장"]

    assert ws["AC2"].value == "협력대상"
    assert ws["AD2"].value == "협력여부"
    assert ws["AC3"].value == "Y"
    assert ws["AD3"].value == "N"
    assert ws["AC4"].value == "Y"
    assert ws["AD4"].value == "Y"
    assert ws["AC5"].value == "N"
    assert ws["AD5"].value == "N"

    wb.close()
