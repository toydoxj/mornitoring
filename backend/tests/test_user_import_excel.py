"""사용자 엑셀 일괄등록 회귀 테스트."""

import io

from openpyxl import Workbook

from models.reviewer import Reviewer
from models.user import User, UserRole


def _workbook_bytes(rows: list[list[object]]) -> io.BytesIO:
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    wb.close()
    buf.seek(0)
    return buf


def test_import_users_excel_supports_2026_reviewer_roster(
    client, db_session, make_user
):
    """2026 검토위원 명단의 헤더 구조를 읽어 REVIEWER/조/특수분야를 저장한다."""
    _, headers = make_user(UserRole.TEAM_LEADER)
    payload = _workbook_bytes([
        [
            "조",
            "회원명",
            "회 소속 \n(예: 본회 / 지회) ",
            "소속 \n(사무실명)",
            "휴대전화번호",
            "자격 취득 후 경력 \n(예: OO년) ",
            "소속 조직 규모\n(예:대표 포함 O명) ",
            "특수분야(선택) \n(예: 목구조, 대공간구조, 기타 등)",
            "이메일",
        ],
        [
            "6조 ",
            "김용인",
            "호남지회",
            "(주)아이원구조엔지니어링",
            "010-5266-2040 ",
            "9년",
            "대표 포함 5명",
            "철근콘크리트구조, 철골구조",
            "ioeng19@daum.net ",
        ],
    ])
    files = {
        "file": (
            "reviewers.xlsx",
            payload,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }

    res = client.post("/api/users/import-excel", headers=headers, files=files)

    assert res.status_code == 200
    body = res.json()
    assert body["created"] == 1
    assert body["skipped"] == 0
    assert body["errors"] == []

    db_session.expire_all()
    user = db_session.query(User).filter(User.email == "ioeng19@daum.net").one()
    assert user.name == "김용인"
    assert user.role == UserRole.REVIEWER
    assert user.phone == "010-5266-2040"

    reviewer = db_session.query(Reviewer).filter(Reviewer.user_id == user.id).one()
    assert reviewer.group_no == 6
    assert reviewer.specialty == "철근콘크리트구조, 철골구조"


def test_import_users_excel_keeps_legacy_template_compatible(
    client, db_session, make_user
):
    """기존 이름/이메일/역할/전화번호 템플릿도 계속 등록된다."""
    _, headers = make_user(UserRole.TEAM_LEADER)
    payload = _workbook_bytes([
        ["이름", "이메일", "역할", "전화번호"],
        ["박간사", "secretary-new@example.com", "간사", "010-1111-2222"],
    ])
    files = {
        "file": (
            "users.xlsx",
            payload,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }

    res = client.post("/api/users/import-excel", headers=headers, files=files)

    assert res.status_code == 200
    body = res.json()
    assert body["created"] == 1
    assert body["skipped"] == 0

    db_session.expire_all()
    user = (
        db_session.query(User)
        .filter(User.email == "secretary-new@example.com")
        .one()
    )
    assert user.name == "박간사"
    assert user.role == UserRole.SECRETARY
    assert user.phone == "010-1111-2222"
