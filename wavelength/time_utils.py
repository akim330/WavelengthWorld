from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

APP_TZ = ZoneInfo("America/New_York")


def today_bounds_app_tz() -> tuple[datetime, datetime]:
    now = datetime.now(APP_TZ)
    start = datetime.combine(now.date(), time.min, tzinfo=APP_TZ)
    end = datetime.combine(now.date(), time.max, tzinfo=APP_TZ)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def week_bounds_app_tz() -> tuple[datetime, datetime]:
    now = datetime.now(APP_TZ)
    week_start_date = now.date().fromordinal(now.date().toordinal() - now.weekday())
    week_end_date = week_start_date.fromordinal(week_start_date.toordinal() + 6)
    start = datetime.combine(week_start_date, time.min, tzinfo=APP_TZ)
    end = datetime.combine(week_end_date, time.max, tzinfo=APP_TZ)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)
