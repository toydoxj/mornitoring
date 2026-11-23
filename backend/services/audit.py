"""감사 로그 기록 서비스"""

from sqlalchemy.orm import Session

from models.audit_log import AuditLog
from models.building import Building


def log_action(
    db: Session,
    user_id: int | None,
    action: str,
    target_type: str,
    target_id: int | None = None,
    before_data: dict | None = None,
    after_data: dict | None = None,
    ip_address: str | None = None,
):
    """감사 로그 기록

    Args:
        action: create / update / delete / upload / assign / advance
        target_type: building / review_stage / user / assignment
    """
    log = AuditLog(
        user_id=user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        before_data=before_data,
        after_data=after_data,
        ip_address=ip_address,
    )
    db.add(log)


# 담당 검토위원 변경 로그. 기존 PATCH /api/buildings/{id} 와 같은 action 을 쓰고,
# 변경 경로는 after_data["source"] 로 구분한다.
REVIEWER_CHANGE_ACTION = "change_reviewer"
REVIEWER_CHANGE_SOURCES = ("assign_api", "unassign_api", "assignment_excel", "building_patch")


def log_reviewer_change(
    db: Session,
    user_id: int | None,
    building: Building,
    *,
    before_reviewer_id: int | None,
    before_reviewer_name: str | None,
    source: str,
    batch_id: str | None = None,
    extra_after: dict | None = None,
) -> bool:
    """담당 변경을 audit_logs 에 기록한다.

    building 은 변경을 반영한 뒤의 객체다. 전·후 reviewer_id 와 assigned_reviewer_name 이
    모두 같으면 기록하지 않고 False 를 돌려준다. 호출자의 트랜잭션 안에서 db.add 만 한다.

    Raises:
        ValueError: source 가 REVIEWER_CHANGE_SOURCES 에 없을 때
    """
    if source not in REVIEWER_CHANGE_SOURCES:
        raise ValueError(f"알 수 없는 담당 변경 source: {source}")

    before = (before_reviewer_id, before_reviewer_name)
    after = (building.reviewer_id, building.assigned_reviewer_name)
    if before == after:
        return False

    after_data: dict = {
        "mgmt_no": building.mgmt_no,
        "reviewer_id": building.reviewer_id,
        "assigned_reviewer_name": building.assigned_reviewer_name,
        "source": source,
    }
    if batch_id is not None:
        after_data["batch_id"] = batch_id
    if extra_after:
        after_data.update(extra_after)

    log_action(
        db,
        user_id,
        REVIEWER_CHANGE_ACTION,
        "building",
        building.id,
        before_data={
            "mgmt_no": building.mgmt_no,
            "reviewer_id": before_reviewer_id,
            "assigned_reviewer_name": before_reviewer_name,
        },
        after_data=after_data,
    )
    return True
