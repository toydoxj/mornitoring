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


def test_reviewer_cannot_unlink_kakao_oauth(client, make_reviewer, make_user):
    _, _, headers = make_reviewer()
    target, _ = make_user(UserRole.SECRETARY)
    res = client.delete(f"/api/kakao/oauth/{target.id}", headers=headers)
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


def test_team_leader_can_unlink_kakao_oauth_without_unmatching(
    client, db_session, make_user
):
    """로그인 연동 해제는 토큰/kakao_id만 지우고 친구 매칭은 유지한다."""
    _, headers = make_user(UserRole.TEAM_LEADER)
    target, _ = make_user(
        UserRole.REVIEWER,
        kakao_id="wrong-kakao-id",
        kakao_uuid="matched-friend-uuid",
        kakao_login_uuid="login-uuid",
        kakao_access_token="access-token",
        kakao_refresh_token="refresh-token",
        kakao_scopes_ok=True,
    )

    res = client.delete(f"/api/kakao/oauth/{target.id}", headers=headers)
    assert res.status_code == 200

    db_session.expire_all()
    from models.user import User as UserModel

    refreshed = db_session.query(UserModel).filter(UserModel.id == target.id).first()
    assert refreshed.kakao_id is None
    assert refreshed.kakao_uuid == "matched-friend-uuid"
    assert refreshed.kakao_login_uuid is None
    assert refreshed.kakao_access_token is None
    assert refreshed.kakao_refresh_token is None
    assert refreshed.kakao_scopes_ok is None


def test_list_users_match_status_reports_kakao_identity_status(client, make_user):
    """친구 매칭 uuid와 로그인 uuid의 일치 여부를 목록에 표시한다."""
    _, headers = make_user(UserRole.TEAM_LEADER)
    matched, _ = make_user(
        UserRole.REVIEWER,
        email="identity-matched@example.com",
        kakao_id="matched-id",
        kakao_uuid="same-uuid",
        kakao_login_uuid="same-uuid",
    )
    mismatch, _ = make_user(
        UserRole.REVIEWER,
        email="identity-mismatch@example.com",
        kakao_id="mismatch-id",
        kakao_uuid="friend-uuid",
        kakao_login_uuid="login-uuid",
    )

    res = client.get("/api/kakao/reviewers", headers=headers)
    assert res.status_code == 200
    by_id = {item["user_id"]: item for item in res.json()}
    assert by_id[matched.id]["kakao_identity_status"] == "matched"
    assert by_id[mismatch.id]["kakao_identity_status"] == "mismatch"


def test_match_kakao_rejects_uuid_different_from_login_uuid(client, make_user):
    """로그인 uuid가 확인된 사용자는 다른 친구 uuid로 매칭할 수 없다."""
    _, headers = make_user(UserRole.TEAM_LEADER)
    target, _ = make_user(
        UserRole.REVIEWER,
        kakao_id="login-linked-id",
        kakao_login_uuid="real-login-uuid",
    )

    res = client.post(
        "/api/kakao/match",
        headers=headers,
        json={"user_id": target.id, "kakao_uuid": "other-friend-uuid"},
    )

    assert res.status_code == 409
    assert "다릅니다" in res.json()["detail"]
