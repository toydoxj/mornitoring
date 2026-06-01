"""상세체크리스트 의견 API 회귀 테스트."""

from models.user import UserRole


def test_reviewer_can_create_and_list_checklist_opinion(client, make_reviewer):
    _, _, headers = make_reviewer()

    res = client.post(
        "/api/checklist/items/1-1/opinions",
        headers=headers,
        json={"content": "고정하중 확인사항 문구 보완이 필요합니다."},
    )

    assert res.status_code == 201
    data = res.json()
    assert data["item_key"] == "1-1"
    assert data["content"] == "고정하중 확인사항 문구 보완이 필요합니다."

    list_res = client.get("/api/checklist/items/1-1/opinions", headers=headers)
    assert list_res.status_code == 200
    assert len(list_res.json()) == 1
    assert list_res.json()[0]["id"] == data["id"]


def test_checklist_opinion_summary_counts_by_item(client, make_reviewer):
    _, _, headers = make_reviewer()
    client.post(
        "/api/checklist/items/1-1/opinions",
        headers=headers,
        json={"content": "첫 번째 의견"},
    )
    client.post(
        "/api/checklist/items/1-2/opinions",
        headers=headers,
        json={"content": "두 번째 의견"},
    )
    client.post(
        "/api/checklist/items/1-1/opinions",
        headers=headers,
        json={"content": "세 번째 의견"},
    )

    res = client.get("/api/checklist/opinions/summary", headers=headers)

    assert res.status_code == 200
    counts = {item["item_key"]: item["count"] for item in res.json()}
    assert counts["1-1"] == 2
    assert counts["1-2"] == 1


def test_empty_checklist_opinion_is_rejected(client, make_reviewer):
    _, _, headers = make_reviewer()

    res = client.post(
        "/api/checklist/items/1-1/opinions",
        headers=headers,
        json={"content": "   "},
    )

    assert res.status_code == 400


def test_reviewer_cannot_delete_others_checklist_opinion(client, make_reviewer):
    _, _, headers_a = make_reviewer()
    _, _, headers_b = make_reviewer()
    opinion = client.post(
        "/api/checklist/items/1-1/opinions",
        headers=headers_a,
        json={"content": "작성자만 삭제할 수 있어야 합니다."},
    ).json()

    res = client.delete(
        f"/api/checklist/opinions/{opinion['id']}",
        headers=headers_b,
    )

    assert res.status_code == 403


def test_team_leader_can_delete_any_checklist_opinion(
    client,
    make_reviewer,
    make_user,
):
    _, _, headers_reviewer = make_reviewer()
    _, headers_leader = make_user(UserRole.TEAM_LEADER)
    opinion = client.post(
        "/api/checklist/items/1-1/opinions",
        headers=headers_reviewer,
        json={"content": "관리자가 정리할 수 있어야 합니다."},
    ).json()

    res = client.delete(
        f"/api/checklist/opinions/{opinion['id']}",
        headers=headers_leader,
    )

    assert res.status_code == 204
