"""간사가 같은 조에만 알림 발송 가능한지 회귀.

- POST /api/notifications/send: 같은 조 검토위원 OK, 다른 조 포함 시 403
- POST /api/notifications/review-reminder: SECRETARY 권한 + recipient_user_ids 가시성
- GET /api/notifications: SECRETARY 권한 + 같은 조 알림만 노출
- collect_targets(sender=...): SECRETARY 의 자동 수집도 같은 조 검토위원만
"""

from datetime import date, timedelta

from models.notification_log import NotificationLog
from models.review_stage import PhaseType, ReviewStage
from models.user import UserRole
from services.review_reminder import collect_targets


def _setup(make_user, make_reviewer, make_building, db_session):
    """간사(조1) + 같은 조 검토위원 + 다른 조 검토위원 + 각자 건물."""
    sec, sec_h = make_user(UserRole.SECRETARY)
    sec.group_no = 1

    same_user, same_rev, _ = make_reviewer()
    same_rev.group_no = 1
    same_user.kakao_uuid = "uuid-same"

    other_user, other_rev, _ = make_reviewer()
    other_rev.group_no = 2
    other_user.kakao_uuid = "uuid-other"

    db_session.commit()

    b_same = make_building(mgmt_no="NS-G1", reviewer_id=same_rev.id)
    b_other = make_building(mgmt_no="NS-G2", reviewer_id=other_rev.id)
    return sec, sec_h, same_user, other_user, b_same, b_other


# ===== /send =====

def test_secretary_send_to_same_group_allowed_then_blocked_for_other(
    client, db_session, make_user, make_reviewer, make_building
):
    sec, sec_h, same_user, other_user, *_ = _setup(
        make_user, make_reviewer, make_building, db_session
    )
    # 같은 조 user 만 → 발신자 카카오 토큰 미설정으로 401(외부 호출 단계 진입은 OK).
    # 가드는 403 이전에 통과한다 — 우리 관심사는 가드 자체이므로 응답 코드와 body 만 확인.
    res = client.post(
        "/api/notifications/send", headers=sec_h,
        json={"recipient_ids": [same_user.id], "title": "t", "message": "m"},
    )
    # 가드 통과 → 발신자 카카오 토큰 미설정으로 400
    assert res.status_code == 400
    assert "카카오" in res.json().get("detail", "") or "token" in res.json().get("detail", "").lower()

    # 다른 조 포함 → 403, invalid_recipient_ids 에 다른 조 user_id 포함
    res = client.post(
        "/api/notifications/send", headers=sec_h,
        json={
            "recipient_ids": [same_user.id, other_user.id],
            "title": "t", "message": "m",
        },
    )
    assert res.status_code == 403
    detail = res.json()["detail"]
    assert detail["invalid_recipient_ids"] == [other_user.id]


def test_chief_secretary_send_unrestricted(
    client, db_session, make_user, make_reviewer, make_building
):
    """총괄간사는 가시성 무제한 — 가드를 통과해야 한다."""
    _, _, _, other_user, *_ = _setup(
        make_user, make_reviewer, make_building, db_session
    )
    _, h = make_user(UserRole.CHIEF_SECRETARY)
    res = client.post(
        "/api/notifications/send", headers=h,
        json={"recipient_ids": [other_user.id], "title": "t", "message": "m"},
    )
    # 가드는 통과 → 발신자 카카오 토큰 미설정으로 400
    assert res.status_code == 400


# ===== /review-reminder =====

def test_secretary_review_reminder_recipient_guard(
    client, db_session, make_user, make_reviewer, make_building
):
    sec, sec_h, same_user, other_user, *_ = _setup(
        make_user, make_reviewer, make_building, db_session
    )
    res = client.post(
        "/api/notifications/review-reminder", headers=sec_h,
        json={
            "trigger": "within_n_days",
            "dry_run": True,
            "recipient_user_ids": [other_user.id],
        },
    )
    assert res.status_code == 403
    assert res.json()["detail"]["invalid_recipient_ids"] == [other_user.id]


def test_secretary_review_reminder_dry_run_filters_by_group(
    client, db_session, make_user, make_reviewer, make_building
):
    sec, sec_h, same_user, other_user, b_same, b_other = _setup(
        make_user, make_reviewer, make_building, db_session
    )
    # 양쪽 건물에 미제출 stage 생성
    today = date.today()
    db_session.add(ReviewStage(
        building_id=b_same.id, phase=PhaseType.PRELIMINARY, phase_order=0,
        report_due_date=today + timedelta(days=1),
    ))
    db_session.add(ReviewStage(
        building_id=b_other.id, phase=PhaseType.PRELIMINARY, phase_order=0,
        report_due_date=today + timedelta(days=1),
    ))
    db_session.commit()

    res = client.post(
        "/api/notifications/review-reminder", headers=sec_h,
        json={"trigger": "within_n_days", "dry_run": True, "days_ahead": 3},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    # 같은 조만 1건
    assert body["target_count"] == 1
    reviewers = body["by_reviewer"]
    assert len(reviewers) == 1
    assert reviewers[0]["reviewer_user_id"] == same_user.id


# ===== /api/notifications list =====

def test_secretary_list_notifications_filters_by_group(
    client, db_session, make_user, make_reviewer, make_building
):
    sec, sec_h, same_user, other_user, b_same, b_other = _setup(
        make_user, make_reviewer, make_building, db_session
    )
    db_session.add(NotificationLog(
        recipient_id=same_user.id, channel="kakao", template_type="t",
        title="g1", message="g1", is_sent=True,
    ))
    db_session.add(NotificationLog(
        recipient_id=other_user.id, channel="kakao", template_type="t",
        title="g2", message="g2", is_sent=True,
    ))
    db_session.commit()

    res = client.get("/api/notifications", headers=sec_h)
    assert res.status_code == 200
    titles = [it["title"] for it in res.json()["items"]]
    assert "g1" in titles
    assert "g2" not in titles


# ===== /send self 발송 + self+타인 혼합 =====

def test_secretary_send_to_self_allowed(
    client, db_session, make_user, make_reviewer, make_building
):
    """간사가 자기 자신에게 발송 — 가시 reviewer 셋과 별개로 항상 허용."""
    sec, sec_h, *_ = _setup(make_user, make_reviewer, make_building, db_session)
    res = client.post(
        "/api/notifications/send", headers=sec_h,
        json={"recipient_ids": [sec.id], "title": "self", "message": "m"},
    )
    # 가드 통과 → 발신자 카카오 토큰 미설정으로 400
    assert res.status_code == 400


def test_secretary_send_self_with_other_group_member_blocked(
    client, db_session, make_user, make_reviewer, make_building
):
    """본인 + 다른 조 위원 혼합 시 다른 조 user_id 만 invalid 로 표기."""
    sec, sec_h, _, other_user, *_ = _setup(
        make_user, make_reviewer, make_building, db_session
    )
    res = client.post(
        "/api/notifications/send", headers=sec_h,
        json={"recipient_ids": [sec.id, other_user.id], "title": "t", "message": "m"},
    )
    assert res.status_code == 403
    assert res.json()["detail"]["invalid_recipient_ids"] == [other_user.id]


# ===== /api/notifications related_building_id OR 경로 =====

def test_secretary_list_notifications_includes_related_building_match(
    client, db_session, make_user, make_reviewer, make_building
):
    """수신자가 가시 셋 외여도 related_building 이 같은 조면 노출."""
    sec, sec_h, _, other_user, b_same, b_other = _setup(
        make_user, make_reviewer, make_building, db_session
    )
    # 다른 조 위원에게 발송됐지만 related_building 은 같은 조 건물 → 노출돼야 함
    db_session.add(NotificationLog(
        recipient_id=other_user.id, channel="kakao", template_type="t",
        title="rel-g1", message="m", related_building_id=b_same.id, is_sent=True,
    ))
    # 다른 조 건물 + 다른 조 위원 → 노출 안 됨
    db_session.add(NotificationLog(
        recipient_id=other_user.id, channel="kakao", template_type="t",
        title="rel-g2", message="m", related_building_id=b_other.id, is_sent=True,
    ))
    db_session.commit()

    res = client.get("/api/notifications", headers=sec_h)
    titles = [it["title"] for it in res.json()["items"]]
    assert "rel-g1" in titles
    assert "rel-g2" not in titles


# ===== collect_targets sender 단위 =====

def test_collect_targets_with_secretary_sender_filters(
    db_session, make_user, make_reviewer, make_building
):
    sec, _, same_user, other_user, b_same, b_other = _setup(
        make_user, make_reviewer, make_building, db_session
    )
    today = date.today()
    db_session.add(ReviewStage(
        building_id=b_same.id, phase=PhaseType.PRELIMINARY, phase_order=0,
        report_due_date=today + timedelta(days=2),
    ))
    db_session.add(ReviewStage(
        building_id=b_other.id, phase=PhaseType.PRELIMINARY, phase_order=0,
        report_due_date=today + timedelta(days=2),
    ))
    db_session.commit()

    # sender=None → 두 건 모두 (cron 호환)
    all_targets = collect_targets(db_session, "within_n_days", today=today, days_ahead=3)
    assert {t.mgmt_no for t in all_targets} == {"NS-G1", "NS-G2"}

    # sender=같은 조 간사 → 같은 조 1건
    scoped = collect_targets(
        db_session, "within_n_days", today=today, days_ahead=3, sender=sec,
    )
    assert {t.mgmt_no for t in scoped} == {"NS-G1"}
