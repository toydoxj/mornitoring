"""감사 로그 기록 서비스"""

from sqlalchemy.orm import Session

from models.audit_log import AuditLog


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
