"""Даты торгового брифинга."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.pipeline.models import BriefingDates

_MONTHS_GENITIVE = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def format_russian_date(dt: datetime) -> str:
    return f"{dt.day} {_MONTHS_GENITIVE[dt.month - 1]} {dt.year}"


def briefing_dates(now: datetime, tz_name: str) -> BriefingDates:
    local = now.astimezone(ZoneInfo(tz_name))
    yesterday = local - timedelta(days=1)
    return BriefingDates(
        local=local,
        trading_date=format_russian_date(local),
        yesterday_date=format_russian_date(yesterday),
        report_datetime=f"{format_russian_date(local)}, {local:%H:%M}",
        tz_name=tz_name,
    )
