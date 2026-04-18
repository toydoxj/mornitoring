"""파일 업로드 크기 제한 회귀."""

import io

from models.user import UserRole


def test_upload_excel_oversized_returns_413(client, make_user):
    """import-excel에 11MB 이상 파일 업로드 시 413 (제한 10MB)."""
    _, headers = make_user(UserRole.TEAM_LEADER)
    big_payload = b"x" * (11 * 1024 * 1024)  # 11MB
    files = {
        "file": (
            "big.xlsx",
            io.BytesIO(big_payload),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }
    res = client.post("/api/users/import-excel", headers=headers, files=files)
    assert res.status_code == 413
    assert "10MB" in res.json()["detail"]


def test_upload_oversized_for_attachment_returns_413(
    client, db_session, make_user
):
    """공지 첨부에 21MB 업로드 시 413 (제한 20MB)."""
    _, headers = make_user(UserRole.TEAM_LEADER)
    # 공지 먼저 생성
    ann = client.post(
        "/api/announcements",
        headers=headers,
        json={"title": "T", "content": "C"},
    ).json()

    big = b"x" * (21 * 1024 * 1024)
    files = {"file": ("big.bin", io.BytesIO(big), "application/octet-stream")}
    res = client.post(
        f"/api/announcements/{ann['id']}/attachments",
        headers=headers,
        files=files,
    )
    assert res.status_code == 413
    assert "20MB" in res.json()["detail"]
