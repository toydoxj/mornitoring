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


def test_conversation_list_is_per_user(client, make_user, db_session):
    """다른 사용자의 대화는 목록에도, 상세 조회에도 나오지 않는다."""
    from models.stats_chat import StatsChatConversation

    owner, owner_headers = make_user(UserRole.SECRETARY)
    _, other_headers = make_user(UserRole.SECRETARY)

    conversation = StatsChatConversation(user_id=owner.id, title="내 질문")
    db_session.add(conversation)
    db_session.commit()

    mine = client.get("/api/stats-chat/conversations", headers=owner_headers).json()
    assert [c["title"] for c in mine] == ["내 질문"]

    others = client.get("/api/stats-chat/conversations", headers=other_headers).json()
    assert others == []

    detail = client.get(
        f"/api/stats-chat/conversations/{conversation.id}", headers=other_headers
    )
    assert detail.status_code == 404
