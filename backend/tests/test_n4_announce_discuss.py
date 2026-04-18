"""N4-B — announcements + discussions 권한 회귀.

정책:
- announcements: 글 CRUD는 SECRETARY 이상, 댓글은 모든 인증 사용자, 댓글 삭제는 본인/팀장/총괄간사
- discussions: 모든 인증 사용자 자유 작성/댓글/첨부, 본인 글/댓글만 수정·삭제(관리자는 모두 가능)

코드 변경 없음. 회귀 테스트로 정책을 고정한다.
"""

from models.user import UserRole


# ===== announcements =====

def test_reviewer_cannot_create_announcement(client, make_reviewer):
    _, _, headers = make_reviewer()
    res = client.post(
        "/api/announcements",
        headers=headers,
        json={"title": "테스트", "content": "본문"},
    )
    assert res.status_code == 403


def test_reviewer_can_comment_on_announcement(client, make_reviewer, make_user):
    _, headers_admin = make_user(UserRole.SECRETARY)
    res_create = client.post(
        "/api/announcements",
        headers=headers_admin,
        json={"title": "공지", "content": "본문"},
    )
    assert res_create.status_code == 201
    ann_id = res_create.json()["id"]

    _, _, headers_r = make_reviewer()
    res = client.post(
        f"/api/announcements/{ann_id}/comments",
        headers=headers_r,
        json={"content": "검토위원 댓글"},
    )
    assert res.status_code == 201


def test_secretary_cannot_delete_others_announcement_comment(
    client, make_user
):
    _, headers_a = make_user(UserRole.SECRETARY)
    _, headers_b = make_user(UserRole.SECRETARY)
    ann = client.post(
        "/api/announcements",
        headers=headers_a,
        json={"title": "T", "content": "C"},
    ).json()
    comment = client.post(
        f"/api/announcements/{ann['id']}/comments",
        headers=headers_a,
        json={"content": "A의 댓글"},
    ).json()

    res = client.delete(
        f"/api/announcements/comments/{comment['id']}", headers=headers_b
    )
    assert res.status_code == 403  # SECRETARY는 다른 사람 댓글 삭제 불가


def test_team_leader_can_delete_any_announcement_comment(
    client, make_user, make_reviewer
):
    _, headers_admin = make_user(UserRole.SECRETARY)
    _, _, headers_r = make_reviewer()
    _, headers_lead = make_user(UserRole.TEAM_LEADER)

    ann = client.post(
        "/api/announcements",
        headers=headers_admin,
        json={"title": "T", "content": "C"},
    ).json()
    comment = client.post(
        f"/api/announcements/{ann['id']}/comments",
        headers=headers_r,
        json={"content": "REVIEWER 댓글"},
    ).json()

    res = client.delete(
        f"/api/announcements/comments/{comment['id']}", headers=headers_lead
    )
    assert res.status_code == 204


# ===== discussions (모든 인증 사용자 자유) =====

def test_reviewer_can_create_discussion(client, make_reviewer):
    _, _, headers = make_reviewer()
    res = client.post(
        "/api/discussions",
        headers=headers,
        json={"title": "검토위원 토론", "content": "내용"},
    )
    assert res.status_code == 201


def test_reviewer_can_comment_on_discussion(client, make_reviewer, make_user):
    _, headers_admin = make_user(UserRole.SECRETARY)
    d = client.post(
        "/api/discussions",
        headers=headers_admin,
        json={"title": "T", "content": "C"},
    ).json()

    _, _, headers_r = make_reviewer()
    res = client.post(
        f"/api/discussions/{d['id']}/comments",
        headers=headers_r,
        json={"content": "댓글"},
    )
    assert res.status_code == 201


def test_reviewer_cannot_edit_others_discussion(client, make_reviewer):
    _, _, headers_a = make_reviewer()
    _, _, headers_b = make_reviewer()
    d = client.post(
        "/api/discussions",
        headers=headers_a,
        json={"title": "A 글", "content": "본문"},
    ).json()

    res = client.patch(
        f"/api/discussions/{d['id']}",
        headers=headers_b,
        json={"title": "변경 시도"},
    )
    assert res.status_code == 403


def test_reviewer_can_edit_own_discussion(client, make_reviewer):
    _, _, headers = make_reviewer()
    d = client.post(
        "/api/discussions",
        headers=headers,
        json={"title": "내 글", "content": "본문"},
    ).json()

    res = client.patch(
        f"/api/discussions/{d['id']}",
        headers=headers,
        json={"title": "수정"},
    )
    assert res.status_code == 200
    assert res.json()["title"] == "수정"


def test_reviewer_cannot_delete_others_discussion(client, make_reviewer):
    _, _, headers_a = make_reviewer()
    _, _, headers_b = make_reviewer()
    d = client.post(
        "/api/discussions",
        headers=headers_a,
        json={"title": "A", "content": "C"},
    ).json()

    res = client.delete(f"/api/discussions/{d['id']}", headers=headers_b)
    assert res.status_code == 403


def test_team_leader_can_delete_any_discussion(client, make_reviewer, make_user):
    _, _, headers_r = make_reviewer()
    _, headers_lead = make_user(UserRole.TEAM_LEADER)

    d = client.post(
        "/api/discussions",
        headers=headers_r,
        json={"title": "REVIEWER 글", "content": "C"},
    ).json()

    res = client.delete(f"/api/discussions/{d['id']}", headers=headers_lead)
    assert res.status_code == 204


# ===== 첨부 권한 (codex 권고 추가) =====

def test_reviewer_cannot_upload_attachment_to_announcement(
    client, make_reviewer, make_user
):
    """공지 첨부 업로드는 SECRETARY 이상만 (require_roles)."""
    import io

    _, headers_admin = make_user(UserRole.SECRETARY)
    ann = client.post(
        "/api/announcements",
        headers=headers_admin,
        json={"title": "T", "content": "C"},
    ).json()

    _, _, headers_r = make_reviewer()
    files = {"file": ("a.txt", io.BytesIO(b"data"), "text/plain")}
    res = client.post(
        f"/api/announcements/{ann['id']}/attachments",
        headers=headers_r,
        files=files,
    )
    assert res.status_code == 403


def test_reviewer_cannot_delete_others_discussion_attachment(
    client, db_session, make_reviewer
):
    """토론방 첨부 삭제는 본인 또는 관리자만."""
    from models.discussion import Discussion, DiscussionAttachment

    user_a, _, headers_a = make_reviewer()
    user_b, _, headers_b = make_reviewer()

    # A가 토론글 작성 + A의 첨부 직접 insert
    discussion = Discussion(
        author_id=user_a.id, author_name=user_a.name, title="T", content="C"
    )
    db_session.add(discussion)
    db_session.commit()
    db_session.refresh(discussion)

    att = DiscussionAttachment(
        discussion_id=discussion.id,
        filename="a.txt",
        s3_key="discussions/test/a.txt",
        file_size=4,
        uploaded_by=user_a.id,
    )
    db_session.add(att)
    db_session.commit()
    db_session.refresh(att)

    # B가 A의 첨부 삭제 시도 → 403
    res = client.delete(
        f"/api/discussions/attachments/{att.id}", headers=headers_b
    )
    assert res.status_code == 403
