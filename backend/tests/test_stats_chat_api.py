"""통계 분석 챗봇 API 권한·기본 동작 테스트."""

from models.user import UserRole


def test_reviewer_cannot_access_chat(client, make_user):
    """검토위원은 통계 챗봇에 접근할 수 없다."""
    _, headers = make_user(UserRole.REVIEWER)
    assert client.get("/api/stats-chat/status", headers=headers).status_code == 403
    assert client.get("/api/stats-chat/conversations", headers=headers).status_code == 403
    response = client.post(
        "/api/stats-chat/ask", json={"question": "총 건수는?"}, headers=headers
    )
    assert response.status_code == 403


def test_unauthenticated_rejected(client):
    assert client.get("/api/stats-chat/status").status_code == 401


def test_secretary_can_read_status(client, make_user):
    """간사도 통계자료 화면과 같은 범위로 접근할 수 있다."""
    _, headers = make_user(UserRole.SECRETARY)
    response = client.get("/api/stats-chat/status", headers=headers)
    assert response.status_code == 200
    # 테스트 환경에는 OPENAI_API_KEY 가 없으므로 비활성 상태로 나온다.
    assert response.json()["enabled"] is False


def test_ask_returns_503_without_api_key(client, make_user):
    _, headers = make_user(UserRole.TEAM_LEADER)
    response = client.post(
        "/api/stats-chat/ask", json={"question": "총 건수는?"}, headers=headers
    )
    assert response.status_code == 503


def test_history_is_chief_secretary_only(client, make_user, db_session):
    """이력 조회·삭제는 총괄간사 전용이다. 간사·팀장·관리원도 볼 수 없다."""
    from models.stats_chat import StatsChatConversation

    owner, _ = make_user(UserRole.SECRETARY)
    conversation = StatsChatConversation(user_id=owner.id, title="간사 질문")
    db_session.add(conversation)
    db_session.commit()

    for role in (UserRole.SECRETARY, UserRole.TEAM_LEADER, UserRole.MANAGER):
        _, headers = make_user(role)
        assert client.get("/api/stats-chat/conversations", headers=headers).status_code == 403
        assert client.get(
            f"/api/stats-chat/conversations/{conversation.id}", headers=headers
        ).status_code == 403
        assert client.delete(
            f"/api/stats-chat/conversations/{conversation.id}", headers=headers
        ).status_code == 403


def test_chief_secretary_sees_all_users_history(client, make_user, db_session):
    """총괄간사는 다른 사용자의 대화까지 작성자 이름과 함께 볼 수 있다."""
    from models.stats_chat import StatsChatConversation, StatsChatMessage, StatsChatRole

    owner, _ = make_user(UserRole.SECRETARY)
    _, chief_headers = make_user(UserRole.CHIEF_SECRETARY)

    conversation = StatsChatConversation(user_id=owner.id, title="간사 질문")
    db_session.add(conversation)
    db_session.flush()
    db_session.add(
        StatsChatMessage(
            conversation_id=conversation.id,
            role=StatsChatRole.USER,
            content="조별 제출률은?",
        )
    )
    db_session.commit()

    rows = client.get("/api/stats-chat/conversations", headers=chief_headers).json()
    assert [(r["title"], r["user_name"]) for r in rows] == [("간사 질문", owner.name)]

    detail = client.get(
        f"/api/stats-chat/conversations/{conversation.id}", headers=chief_headers
    ).json()
    assert detail["user_id"] == owner.id
    assert detail["user_name"] == owner.name
    assert [m["content"] for m in detail["messages"]] == ["조별 제출률은?"]


def test_viewing_others_conversation_is_audited(client, make_user, db_session):
    """남의 대화 열람은 감사 로그에 남는다."""
    from models.audit_log import AuditLog
    from models.stats_chat import StatsChatConversation

    owner, _ = make_user(UserRole.SECRETARY)
    chief, chief_headers = make_user(UserRole.CHIEF_SECRETARY)
    conversation = StatsChatConversation(user_id=owner.id, title="간사 질문")
    db_session.add(conversation)
    db_session.commit()

    client.get(
        f"/api/stats-chat/conversations/{conversation.id}", headers=chief_headers
    )

    logs = (
        db_session.query(AuditLog)
        .filter(AuditLog.target_type == "stats_chat_conversation")
        .all()
    )
    assert [(log.user_id, log.action) for log in logs] == [(chief.id, "view")]


def test_own_conversation_view_is_not_audited(client, make_user, db_session):
    """본인 대화 열람까지 기록하면 감사 로그가 의미 없이 불어난다."""
    from models.audit_log import AuditLog
    from models.stats_chat import StatsChatConversation

    chief, chief_headers = make_user(UserRole.CHIEF_SECRETARY)
    conversation = StatsChatConversation(user_id=chief.id, title="내 질문")
    db_session.add(conversation)
    db_session.commit()

    client.get(
        f"/api/stats-chat/conversations/{conversation.id}", headers=chief_headers
    )

    assert (
        db_session.query(AuditLog)
        .filter(AuditLog.target_type == "stats_chat_conversation")
        .count()
        == 0
    )
