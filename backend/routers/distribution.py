"""도서 접수/배포 라우터"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models.building import Building
from models.review_stage import ReviewStage, PhaseType
from models.user import User, UserRole
from routers.auth import require_roles

router = APIRouter()


class DocReceiveRequest(BaseModel):
    mgmt_nos: list[str]
    received_date: date | None = None  # 미입력 시 오늘


class DocReceiveResponse(BaseModel):
    updated: int
    not_found: list[str]
    notifications: list[dict]


@router.post("/receive", response_model=DocReceiveResponse)
def receive_documents(
    body: DocReceiveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """예비도서 접수 처리

    - 해당 관리번호의 현재 단계를 'doc_received'로 변경
    - review_stages에 도서접수일 기록
    - 검토위원별 알림 데이터 생성
    """
    received = body.received_date or date.today()
    updated = 0
    not_found = []
    notifications: dict[str, list[str]] = {}

    # 1. 건축물 일괄 조회 (1000건씩 분할)
    building_map: dict[str, Building] = {}
    for i in range(0, len(body.mgmt_nos), 1000):
        chunk = body.mgmt_nos[i:i+1000]
        buildings = db.query(Building).filter(Building.mgmt_no.in_(chunk)).all()
        for b in buildings:
            building_map[b.mgmt_no] = b

    # 2. 기존 예비검토 stage 일괄 조회
    building_ids = [b.id for b in building_map.values()]
    existing_stages: dict[int, ReviewStage] = {}
    if building_ids:
        for i in range(0, len(building_ids), 1000):
            chunk = building_ids[i:i+1000]
            stages = db.query(ReviewStage).filter(
                ReviewStage.building_id.in_(chunk),
                ReviewStage.phase == PhaseType.PRELIMINARY,
            ).all()
            for s in stages:
                existing_stages[s.building_id] = s

    # 3. 일괄 처리
    batch_count = 0
    for mgmt_no in body.mgmt_nos:
        building = building_map.get(mgmt_no)
        if not building:
            not_found.append(mgmt_no)
            continue

        building.current_phase = "doc_received"

        stage = existing_stages.get(building.id)
        if stage:
            stage.doc_received_at = received
        else:
            db.add(ReviewStage(
                building_id=building.id,
                phase=PhaseType.PRELIMINARY,
                phase_order=0,
                doc_received_at=received,
            ))

        reviewer_name = building.assigned_reviewer_name
        if reviewer_name:
            if reviewer_name not in notifications:
                notifications[reviewer_name] = []
            notifications[reviewer_name].append(mgmt_no)

        updated += 1
        batch_count += 1
        if batch_count % 500 == 0:
            db.flush()

    db.commit()

    # 알림 목록 생성
    notif_list = []
    for name, mgmt_nos_list in notifications.items():
        notif_list.append({
            "reviewer_name": name,
            "count": len(mgmt_nos_list),
            "mgmt_nos": mgmt_nos_list,
            "message": f"예비검토서로 {len(mgmt_nos_list)}건이 웹하드에 업로드되었습니다. (관리번호 {', '.join(mgmt_nos_list)})",
        })

    return DocReceiveResponse(
        updated=updated,
        not_found=not_found,
        notifications=notif_list,
    )


@router.post("/notify")
async def send_notifications(
    body: list[dict],
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.TEAM_LEADER, UserRole.CHIEF_SECRETARY)
    ),
):
    """검토위원에게 카카오톡 알림 발송.

    - 검토위원 이름 → User 테이블에서 매칭 → user.kakao_uuid로 발송
    - 본인에게 발송하는 경우 "나에게 보내기" API 사용 (UUID 불필요)
    - kakao_uuid 미등록 사용자는 /kakao-match 페이지에서 매칭 안내
    """
    from datetime import datetime, timezone
    from models.notification_log import NotificationLog
    from services.kakao import (
        ensure_valid_token,
        send_message_to_friends,
        send_message_to_self,
    )

    # 발신자 카카오 토큰 유효성 체크 (자동 갱신 포함)
    try:
        access_token = await ensure_valid_token(current_user, db)
    except ValueError as exc:
        for notif in body:
            log = NotificationLog(
                recipient_id=None,
                channel="kakao",
                template_type="doc_received",
                title="예비검토서 접수 알림",
                message=notif.get("message", ""),
                is_sent=False,
                error_message=f"발신자 카카오 토큰 오류: {exc}",
            )
            db.add(log)
        db.commit()
        return {
            "sent": 0,
            "failed": len(body),
            "total": len(body),
            "error": str(exc),
        }

    # 수신자 이름 → User 인덱스 생성 (한 번의 쿼리)
    names = [notif.get("reviewer_name", "") for notif in body if notif.get("reviewer_name")]
    user_by_name: dict[str, User] = {}
    if names:
        matched_users = db.query(User).filter(User.name.in_(names), User.is_active.is_(True)).all()
        user_by_name = {u.name: u for u in matched_users}

    sent = 0
    failed = 0

    def _log(is_sent: bool, message: str, recipient_id: int | None, channel: str, error: str | None):
        db.add(NotificationLog(
            recipient_id=recipient_id,
            channel=channel,
            template_type="doc_received",
            title="예비검토서 접수 알림",
            message=message,
            is_sent=is_sent,
            sent_at=datetime.now(timezone.utc) if is_sent else None,
            error_message=error,
        ))

    for notif in body:
        reviewer_name = notif.get("reviewer_name", "")
        message = notif.get("message", "")

        user = user_by_name.get(reviewer_name)
        if not user:
            _log(False, message, None, "kakao",
                 f"'{reviewer_name}' 사용자가 등록되어 있지 않습니다")
            failed += 1
            continue

        # 본인에게는 "나에게 보내기" API 사용
        if user.id == current_user.id:
            try:
                result = await send_message_to_self(
                    access_token=access_token,
                    title="예비검토서 접수 알림",
                    description=message,
                )
            except Exception as e:
                _log(False, message, user.id, "kakao_memo", f"발송 오류: {e}")
                failed += 1
                continue
            if "error" not in result:
                _log(True, message, user.id, "kakao_memo", None)
                sent += 1
            else:
                _log(False, message, user.id, "kakao_memo", str(result))
                failed += 1
            continue

        # 그 외에는 kakao_uuid 필요
        if not user.kakao_uuid:
            _log(False, message, user.id, "kakao",
                 f"'{reviewer_name}' 카카오 친구 매칭이 안 되어 있습니다 (카카오 매칭 페이지에서 매칭 필요)")
            failed += 1
            continue

        try:
            result = await send_message_to_friends(
                access_token=access_token,
                receiver_uuids=[user.kakao_uuid],
                title="예비검토서 접수 알림",
                description=message,
            )
        except Exception as e:
            _log(False, message, user.id, "kakao", f"발송 오류: {e}")
            failed += 1
            continue

        if "error" not in result and user.kakao_uuid in (result.get("successful_receiver_uuids") or []):
            _log(True, message, user.id, "kakao", None)
            sent += 1
        else:
            _log(False, message, user.id, "kakao", str(result))
            failed += 1

    db.commit()
    return {"sent": sent, "failed": failed, "total": len(body)}
