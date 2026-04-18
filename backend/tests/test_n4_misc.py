"""N4-C — notifications/distribution/assignments/users/ledger 권한 회귀.

- notifications: send/list 관리자 차단, /my는 본인 알림만
- distribution/assignments: 모두 관리자(TEAM_LEADER/CHIEF_SECRETARY) 전용
- ledger: SECRETARY 이상
- users: GET /{user_id}는 본인 또는 관리자(N4-C에서 차단 추가)
"""

from models.notification_log import NotificationLog
from models.user import UserRole


# ===== notifications =====

def test_reviewer_cannot_send_notification(client, make_reviewer):
    _, _, headers = make_reviewer()
    res = client.post(
        "/api/notifications/send",
        headers=headers,
        json={"recipient_user_ids": [], "title": "x", "message": "y"},
    )
    assert res.status_code == 403


def test_reviewer_cannot_list_all_notifications(client, make_reviewer):
    """관리자 전체 발송 이력 조회는 TEAM_LEADER/CHIEF_SECRETARY만."""
    _, _, headers = make_reviewer()
    res = client.get("/api/notifications", headers=headers)
    assert res.status_code == 403


def test_my_notifications_returns_only_own_recipient(
    client, db_session, make_reviewer, make_user
):
    user_a, _, headers_a = make_reviewer()
    user_b, _, _ = make_reviewer()

    # B에게만 알림 1건 직접 insert
    log = NotificationLog(
        recipient_id=user_b.id,
        channel="kakao",
        template_type="doc_received",
        title="알림",
        message="내용",
        is_sent=True,
    )
    db_session.add(log)
    db_session.commit()

    res = client.get("/api/notifications/my", headers=headers_a)
    assert res.status_code == 200
    assert res.json()["total"] == 0  # A는 받은 알림 0건


# ===== assignments / distribution =====

def test_reviewer_cannot_list_assignments_reviewers(client, make_reviewer):
    _, _, headers = make_reviewer()
    res = client.get("/api/assignments/reviewers", headers=headers)
    assert res.status_code == 403


def test_secretary_cannot_assign_reviewer(client, make_user):
    """배정은 TEAM_LEADER/CHIEF_SECRETARY만 (SECRETARY 차단)."""
    _, headers = make_user(UserRole.SECRETARY)
    res = client.post(
        "/api/assignments/assign",
        headers=headers,
        json={"building_id": 1, "reviewer_id": 1},
    )
    assert res.status_code == 403


def test_reviewer_cannot_call_distribution_receive(client, make_reviewer):
    _, _, headers = make_reviewer()
    res = client.post(
        "/api/distribution/receive",
        headers=headers,
        json={"building_id": 1, "phase": "doc_received"},
    )
    assert res.status_code == 403


# ===== ledger =====

def test_reviewer_cannot_export_ledger(client, make_reviewer):
    _, _, headers = make_reviewer()
    res = client.get("/api/ledger/export", headers=headers)
    assert res.status_code == 403


# ===== users =====

def test_reviewer_cannot_get_other_user_profile(client, make_reviewer):
    """N4-C로 차단 추가: 다른 사용자 상세 조회 → 404."""
    _, _, headers_a = make_reviewer()
    user_b, _, _ = make_reviewer()
    res = client.get(f"/api/users/{user_b.id}", headers=headers_a)
    assert res.status_code == 404


def test_reviewer_can_get_own_user_profile(client, make_reviewer):
    user_a, _, headers_a = make_reviewer()
    res = client.get(f"/api/users/{user_a.id}", headers=headers_a)
    assert res.status_code == 200
    assert res.json()["id"] == user_a.id


def test_team_leader_can_get_any_user_profile(client, make_user, make_reviewer):
    _, headers_lead = make_user(UserRole.TEAM_LEADER)
    target, _, _ = make_reviewer()
    res = client.get(f"/api/users/{target.id}", headers=headers_lead)
    assert res.status_code == 200
