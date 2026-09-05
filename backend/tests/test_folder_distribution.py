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


def test_folder_distribution_accepts_multiple_source_dirs(
    client, db_session, make_user, make_reviewer, make_building, tmp_path
):
    """접수 폴더를 여러 개 지정하면 모두 한 번에 분배된다."""
    headers = _admin_headers(make_user)
    _, reviewer, _ = make_reviewer(group_no=5)

    b1 = make_building(mgmt_no="2026-0010")
    b1.assigned_reviewer_name = "박검토"
    make_building(mgmt_no="2026-0011", reviewer_id=reviewer.id)
    db_session.commit()

    source_a = tmp_path / "접수A"
    source_b = tmp_path / "접수B"
    target = tmp_path / "target"
    source_a.mkdir()
    source_b.mkdir()
    (source_a / "2026-0010_구조도서").mkdir()
    (source_b / "2026-0011_보완자료").mkdir()
    (source_b / "참고자료").mkdir()

    res = client.post(
        "/api/distribution/folder-distribution",
        headers=headers,
        json={
            "source_dirs": [str(source_a), str(source_b)],
            "target_dir": str(target),
            "dry_run": False,
            "operation": "move",
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["classified"] == 2
    assert body["skipped"] == 1
    assert body["source_dir_names"] == ["접수A", "접수B"]
    assert sorted(body["classified_mgmt_nos"]) == ["2026-0010", "2026-0011"]
    assert (target / "조미정-박검토" / "2026-0010_구조도서").exists()
    assert (target / "5조-검토위원1" / "2026-0011_보완자료").exists()
    # 출처 접수 폴더가 상세에 기록된다
    by_item = {d["item_name"]: d["source_dir_name"] for d in body["details"]}
    assert by_item["2026-0010_구조도서"] == "접수A"
    assert by_item["2026-0011_보완자료"] == "접수B"
    # 분배 대상이 아닌 항목은 원위치에 남는다
    assert (source_b / "참고자료").exists()


def test_folder_distribution_requires_at_least_one_source(
    client, db_session, make_user, make_building, tmp_path
):
    """접수 폴더를 하나도 지정하지 않으면 400을 낸다."""
    headers = _admin_headers(make_user)
    b1 = make_building(mgmt_no="2026-0012")
    b1.assigned_reviewer_name = "최검토"
    db_session.commit()

    res = client.post(
        "/api/distribution/folder-distribution",
        headers=headers,
        json={
            "target_dir": str(tmp_path / "target"),
            "dry_run": True,
        },
    )

    assert res.status_code == 400, res.text
    assert "접수 폴더" in res.json()["detail"]


def test_folder_distribution_preview_detects_cross_source_name_conflict(
    client, db_session, make_user, make_building, tmp_path
):
    """서로 다른 접수 폴더에 같은 이름이 있으면 미리보기에서도 충돌로 잡는다."""
    headers = _admin_headers(make_user)
    b1 = make_building(mgmt_no="2026-0020")
    b1.assigned_reviewer_name = "정검토"
    db_session.commit()

    source_a = tmp_path / "접수A"
    source_b = tmp_path / "접수B"
    source_a.mkdir()
    source_b.mkdir()
    (source_a / "2026-0020_구조도서").mkdir()
    (source_b / "2026-0020_구조도서").mkdir()

    payload = {
        "source_dirs": [str(source_a), str(source_b)],
        "target_dir": str(tmp_path / "target"),
        "operation": "move",
    }

    preview = client.post(
        "/api/distribution/folder-distribution",
        headers=headers,
        json={**payload, "dry_run": True},
    ).json()
    executed = client.post(
        "/api/distribution/folder-distribution",
        headers=headers,
        json={**payload, "dry_run": False},
    ).json()

    # 미리보기와 실제 실행의 성공/스킵 건수가 어긋나면 안 된다
    assert preview["classified"] == executed["classified"] == 1
    assert preview["skipped"] == executed["skipped"] == 1


def test_folder_distribution_rejects_overlapping_source_dirs(
    client, db_session, make_user, make_building, tmp_path
):
    """접수 폴더끼리 상하위로 겹치면 파일을 건드리기 전에 400을 낸다."""
    headers = _admin_headers(make_user)
    b1 = make_building(mgmt_no="2026-0021")
    b1.assigned_reviewer_name = "한검토"
    db_session.commit()

    parent = tmp_path / "접수"
    child = parent / "2026-0021_구조도서"
    child.mkdir(parents=True)

    res = client.post(
        "/api/distribution/folder-distribution",
        headers=headers,
        json={
            "source_dirs": [str(parent), str(child)],
            "target_dir": str(tmp_path / "target"),
            "dry_run": False,
            "operation": "move",
        },
    )

    assert res.status_code == 400, res.text
    assert "겹칩니다" in res.json()["detail"]
    assert child.exists()  # 아무것도 옮기지 않았다


def test_folder_distribution_rejects_blank_source_dir(
    client, db_session, make_user, make_building, tmp_path
):
    """빈 문자열 경로는 서버 작업 디렉터리로 해석되지 않고 400이 된다."""
    headers = _admin_headers(make_user)
    b1 = make_building(mgmt_no="2026-0022")
    b1.assigned_reviewer_name = "서검토"
    db_session.commit()

    res = client.post(
        "/api/distribution/folder-distribution",
        headers=headers,
        json={
            "source_dirs": ["   "],
            "target_dir": str(tmp_path / "target"),
            "dry_run": True,
        },
    )

    assert res.status_code == 400, res.text
    assert "비어 있습니다" in res.json()["detail"]
