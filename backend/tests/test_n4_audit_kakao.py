"""N4-A — audit.py + kakao.py 권한 회귀 테스트.

두 라우터 모두 이미 require_roles로 보호되어 있다(코드 변경 없음).
회귀 테스트로 REVIEWER 차단을 고정한다.

- audit.py: 모든 엔드포인트 TEAM_LEADER/CHIEF_SECRETARY 전용
- kakao.py: 모든 엔드포인트 관리자(REVIEWER 절대 차단)
"""

from models.user import UserRole


# ----- audit.py -----

def test_reviewer_cannot_list_audit_logs(client, make_reviewer):
    _, _, headers = make_reviewer()
    res = client.get("/api/audit-logs", headers=headers)
    assert res.status_code == 403


def test_secretary_cannot_list_audit_logs(client, make_user):
    """SECRETARY도 감사 로그는 차단(팀장/총괄간사 전용)."""
    _, headers = make_user(UserRole.SECRETARY)
    res = client.get("/api/audit-logs", headers=headers)
    assert res.status_code == 403


def test_team_leader_can_list_audit_logs(client, make_user):
    _, headers = make_user(UserRole.TEAM_LEADER)
    res = client.get("/api/audit-logs", headers=headers)
    assert res.status_code == 200


# ----- kakao.py -----

def test_reviewer_cannot_get_my_kakao_scopes(client, make_reviewer):
    _, _, headers = make_reviewer()
    res = client.get("/api/kakao/me/scopes", headers=headers)
    assert res.status_code == 403


def test_reviewer_cannot_list_kakao_friends(client, make_reviewer):
    _, _, headers = make_reviewer()
    res = client.get("/api/kakao/friends", headers=headers)
    assert res.status_code == 403


def test_reviewer_cannot_match_kakao(client, make_reviewer, make_user):
    _, _, headers = make_reviewer()
    target, _ = make_user(UserRole.SECRETARY)
    res = client.post(
        "/api/kakao/match",
        headers=headers,
        json={"user_id": target.id, "kakao_uuid": "any-uuid"},
    )
    assert res.status_code == 403


def test_reviewer_cannot_unmatch_kakao(client, make_reviewer, make_user):
    _, _, headers = make_reviewer()
    target, _ = make_user(UserRole.SECRETARY)
    res = client.delete(f"/api/kakao/match/{target.id}", headers=headers)
    assert res.status_code == 403


def test_reviewer_cannot_list_users_match_status(client, make_reviewer):
    _, _, headers = make_reviewer()
    res = client.get("/api/kakao/reviewers", headers=headers)
    assert res.status_code == 403


def test_reviewer_cannot_diagnose_other_kakao_scopes(
    client, make_reviewer, make_user
):
    _, _, headers = make_reviewer()
    target, _ = make_user(UserRole.SECRETARY)
    res = client.get(f"/api/kakao/user/{target.id}/scopes", headers=headers)
    assert res.status_code == 403


# ----- 정책 경계 (SECRETARY 허용/차단 명시) -----

def test_secretary_can_list_users_match_status(client, make_user):
    """SECRETARY는 사용자 매칭 상태 목록은 허용 (관리자 협업 도구)."""
    _, headers = make_user(UserRole.SECRETARY)
    res = client.get("/api/kakao/reviewers", headers=headers)
    assert res.status_code == 200


def test_secretary_cannot_list_kakao_friends(client, make_user):
    """SECRETARY는 친구 목록은 차단 (TEAM_LEADER/CHIEF_SECRETARY 전용)."""
    _, headers = make_user(UserRole.SECRETARY)
    res = client.get("/api/kakao/friends", headers=headers)
    assert res.status_code == 403
