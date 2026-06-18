"""폴더명 기반 검토위원별 분배 API 회귀 테스트."""

from models.user import UserRole


def _admin_headers(make_user):
    _, headers = make_user(UserRole.CHIEF_SECRETARY)
    return headers


def test_folder_distribution_preview_uses_db_assignments(
    client, db_session, make_user, make_reviewer, make_building, tmp_path
):
    headers = _admin_headers(make_user)
    _, reviewer, _ = make_reviewer(group_no=3)

    b1 = make_building(mgmt_no="2026-0001")
    b1.assigned_reviewer_name = "김검토"
    make_building(mgmt_no="2026-0002", reviewer_id=reviewer.id)
    db_session.commit()

    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    (source / "2026-0001_구조도서").mkdir()
    (source / "2026-0002_보완자료").mkdir()
    (source / "참고자료").mkdir()

    res = client.post(
        "/api/distribution/folder-distribution",
        headers=headers,
        json={
            "source_dir": str(source),
            "target_dir": str(target),
            "dry_run": True,
            "operation": "move",
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["dry_run"] is True
    assert body["classified"] == 2
    assert body["skipped"] == 1
    assert body["assignment_count"] == 2
    assert body["classified_mgmt_nos"] == ["2026-0001", "2026-0002"]
    assert body["reviewer_counts"]["조미정-김검토"] == 1
    assert body["reviewer_counts"]["3조-검토위원1"] == 1
    assert not target.exists()
    assert (source / "2026-0001_구조도서").exists()


def test_folder_assignment_map_returns_db_assignments(
    client, db_session, make_user, make_reviewer, make_building
):
    headers = _admin_headers(make_user)
    _, reviewer, _ = make_reviewer(group_no=4)

    b1 = make_building(mgmt_no="2026-0003")
    b1.assigned_reviewer_name = "이검토"
    make_building(mgmt_no="2026-0004", reviewer_id=reviewer.id)
    make_building(mgmt_no="2026-0005")
    db_session.commit()

    res = client.get("/api/distribution/folder-assignment-map", headers=headers)

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["assignment_count"] == 2
    assert body["unassigned_building_count"] == 1
    assert body["assignment"]["2026-0003"]["reviewer_name"] == "이검토"
    assert body["assignment"]["2026-0003"]["group_no"] is None
    assert body["assignment"]["2026-0003"]["folder_name"] == "조미정-이검토"
    assert body["assignment"]["2026-0004"]["reviewer_name"] == "검토위원1"
    assert body["assignment"]["2026-0004"]["group_no"] == 4
    assert body["assignment"]["2026-0004"]["folder_name"] == "4조-검토위원1"


def test_folder_distribution_execute_moves_items_by_reviewer(
    client, db_session, make_user, make_building, tmp_path
):
    headers = _admin_headers(make_user)

    b1 = make_building(mgmt_no="2026-0101")
    b1.assigned_reviewer_name = "박검토"
    db_session.commit()

    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    item = source / "2026-0101_예비검토도서"
    item.mkdir()
    (item / "도면.pdf").write_text("test", encoding="utf-8")

    res = client.post(
        "/api/distribution/folder-distribution",
        headers=headers,
        json={
            "source_dir": str(source),
            "target_dir": str(target),
            "dry_run": False,
            "operation": "move",
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["classified"] == 1
    assert body["skipped"] == 0
    assert body["classified_mgmt_nos"] == ["2026-0101"]
    assert not item.exists()
    assert (target / "조미정-박검토" / "2026-0101_예비검토도서" / "도면.pdf").exists()
