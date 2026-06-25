"""업무 기준 날짜 유틸리티."""

from datetime import date, datetime, timedelta, timezone


BUSINESS_TIMEZONE = timezone(timedelta(hours=9), "Asia/Seoul")


def business_today(now: datetime | None = None) -> date:
    """한국 업무일 기준의 오늘 날짜를 반환한다."""
    if now is None:
        return datetime.now(BUSINESS_TIMEZONE).date()
    if now.tzinfo is None:
        now = now.replace(tzinfo=BUSINESS_TIMEZONE)
    return now.astimezone(BUSINESS_TIMEZONE).date()
