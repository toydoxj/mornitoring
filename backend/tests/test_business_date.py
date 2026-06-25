from datetime import date, datetime, timezone

from services.business_date import business_today


def test_business_today_uses_korean_date_when_utc_is_previous_day():
    now = datetime(2026, 6, 24, 15, 30, tzinfo=timezone.utc)

    assert business_today(now) == date(2026, 6, 25)


def test_business_today_keeps_korean_date_before_midnight():
    now = datetime(2026, 6, 24, 14, 59, tzinfo=timezone.utc)

    assert business_today(now) == date(2026, 6, 24)
