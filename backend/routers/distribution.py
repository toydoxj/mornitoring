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
    notifications: dict[str, list[str]] = {}  # {검토위원이름: [관리번호, ...]}

    # 일괄 조회
    buildings = db.query(Building).filter(Building.mgmt_no.in_(body.mgmt_nos)).all()
    building_map = {b.mgmt_no: b for b in buildings}

    for mgmt_no in body.mgmt_nos:
        building = building_map.get(mgmt_no)
        if not building:
            not_found.append(mgmt_no)
            continue

        # 현재 단계 업데이트
        building.current_phase = "doc_received"

        # 예비검토 stage 생성/업데이트
        stage = (
            db.query(ReviewStage)
            .filter(
                ReviewStage.building_id == building.id,
                ReviewStage.phase == PhaseType.PRELIMINARY,
            )
            .first()
        )
        if not stage:
            stage = ReviewStage(
                building_id=building.id,
                phase=PhaseType.PRELIMINARY,
                phase_order=0,
                doc_received_at=received,
            )
            db.add(stage)
        else:
            stage.doc_received_at = received

        # 알림 데이터 수집
        reviewer_name = building.assigned_reviewer_name
        if reviewer_name:
            if reviewer_name not in notifications:
                notifications[reviewer_name] = []
            notifications[reviewer_name].append(mgmt_no)

        updated += 1

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
    """검토위원에게 카카오톡 알림 발송

    발신자(현재 로그인 사용자)의 카카오 토큰으로 친구에게 메시지를 보냅니다.
    """
    from datetime import datetime, timezone
    from models.notification_log import NotificationLog
    from services.kakao import get_friends, send_message_to_friends

    # 발신자 카카오 토큰 확인
    if not current_user.kakao_access_token:
        return {
            "sent": 0,
            "failed": len(body),
            "total": len(body),
            "error": "카카오 로그인이 필요합니다. 로그인 페이지에서 카카오 로그인을 해주세요.",
        }

    # 카카오 친구 목록 조회
    friends = await get_friends(current_user.kakao_access_token)
    # 닉네임 → UUID 매핑
    friend_map: dict[str, str] = {}
    for f in friends:
        nickname = f.get("profile_nickname", "")
        uuid = f.get("uuid", "")
        if nickname and uuid:
            friend_map[nickname] = uuid

    sent = 0
    failed = 0

    for notif in body:
        reviewer_name = notif.get("reviewer_name", "")
        message = notif.get("message", "")

        # 친구 UUID 찾기
        friend_uuid = friend_map.get(reviewer_name)

        if not friend_uuid:
            log = NotificationLog(
                recipient_id=None,
                channel="kakao",
                template_type="doc_received",
                title="예비검토서 접수 알림",
                message=message,
                is_sent=False,
                error_message=f"카카오 친구 목록에 '{reviewer_name}'이 없습니다",
            )
            db.add(log)
            failed += 1
            continue

        # 카카오 메시지 발송 (5명씩 분할)
        result = await send_message_to_friends(
            access_token=current_user.kakao_access_token,
            receiver_uuids=[friend_uuid],
            title="예비검토서 접수 알림",
            description=message,
        )

        if "error" not in result:
            log = NotificationLog(
                recipient_id=None,
                channel="kakao",
                template_type="doc_received",
                title="예비검토서 접수 알림",
                message=message,
                is_sent=True,
                sent_at=datetime.now(timezone.utc),
            )
            db.add(log)
            sent += 1
        else:
            log = NotificationLog(
                recipient_id=None,
                channel="kakao",
                template_type="doc_received",
                title="예비검토서 접수 알림",
                message=message,
                is_sent=False,
                error_message=str(result),
            )
            db.add(log)
            failed += 1

    db.commit()
    return {"sent": sent, "failed": failed, "total": len(body)}
