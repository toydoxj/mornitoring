"""buildings /my-stats, /my-reviews 회귀 테스트.

N2 변경 후: 담당 매칭은 reviewer_id만 사용. 이름 기반 OR 매칭 제거.
- Reviewer 행이 있고 본인 reviewer_id 매칭 건만 반환
- Reviewer 행이 없으면 빈 결과 (assigned_reviewer_name만 있어도 보이지 않음)
"""

from models.user import UserRole


def test_my_reviews_returns_only_own_buildings(
    client, make_reviewer, make_building
):
    _, reviewer_a, headers_a = make_reviewer()
    _, reviewer_b, _ = make_reviewer()
    own = make_building(reviewer_id=reviewer_a.id, mgmt_no="MY-OWN-001")
    make_building(reviewer_id=reviewer_b.id, mgmt_no="MY-OTHER-001")

    res = client.get("/api/buildings/my-reviews", headers=headers_a)
    assert res.status_code == 200
    payload = res.json()
    assert payload["total"] == 1
    assert payload["items"][0]["mgmt_no"] == own.mgmt_no


def test_my_reviews_ignores_assigned_reviewer_name_match(
    client, db_session, make_user, make_building
):
    """Reviewer 행이 없는 사용자는 assigned_reviewer_name이 일치해도 빈 결과."""
    user, headers = make_user(UserRole.REVIEWER, name="홍길동")
    # 같은 이름이 assigned_reviewer_name에 들어있지만 reviewer_id는 없음
    from models.building import Building

    b = Building(
        mgmt_no="NAME-MATCH-001",
        assigned_reviewer_name="홍길동",
        reviewer_id=None,
    )
    db_session.add(b)
    db_session.commit()

    res = client.get("/api/buildings/my-reviews", headers=headers)
    assert res.status_code == 200
    payload = res.json()
    assert payload["total"] == 0


def test_my_stats_returns_zero_when_no_reviewer_row(
    client, db_session, make_user
):
    user, headers = make_user(UserRole.REVIEWER, name="이순신")
    from models.building import Building

    b = Building(mgmt_no="STATS-NAME-001", assigned_reviewer_name="이순신")
    db_session.add(b)
    db_session.commit()

    res = client.get("/api/buildings/my-stats", headers=headers)
    assert res.status_code == 200
    payload = res.json()
    assert payload["total"] == 0
    assert payload["need_review"] == 0


def test_my_stats_counts_only_own_reviewer_id(
    client, make_reviewer, make_building
):
    _, reviewer_a, headers_a = make_reviewer()
    _, reviewer_b, _ = make_reviewer()
    make_building(reviewer_id=reviewer_a.id)
    make_building(reviewer_id=reviewer_a.id)
    make_building(reviewer_id=reviewer_b.id)

    res = client.get("/api/buildings/my-stats", headers=headers_a)
    assert res.status_code == 200
    payload = res.json()
    assert payload["total"] == 2
