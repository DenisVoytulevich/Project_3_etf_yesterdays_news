"""Обработчик первичных данных: портфель, структура, зоны интереса."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from src.companies.context import format_companies_for_prompt
from src.config import Settings, load_yaml_config
from src.data.sheets import load_portfolio_analytics
from src.pipeline.dates import briefing_dates
from src.pipeline.models import FocusContext
from src.sectors.interest import (
    collect_screening_sectors,
    format_interest_sectors_for_prompt,
)
from src.structure.aggregation import StructureAnalysis, load_structure_analysis

logger = logging.getLogger(__name__)


def _format_calendar_for_today(calendar, *, now: datetime, tz_name: str) -> str:
    from src.calendar.models import EconomicEvent
    from src.pipeline.dates import format_russian_date

    local = now.astimezone(ZoneInfo(tz_name))
    today = local.date()
    today_events: list[EconomicEvent] = [
        event for event in calendar if event.event_at.date() == today
    ]
    today_events.sort(key=lambda event: event.event_at)

    lines = [
        f"**Календарь на {format_russian_date(local)} (Europe/Warsaw):**",
        f"Событий сегодня: {len(today_events)}",
        "",
    ]
    if not today_events:
        lines.append("_На сегодня в календаре Investing.com нет событий средней+ важности._")
        return "\n".join(lines)

    for event in today_events[:25]:
        time_str = event.event_at.strftime("%H:%M")
        values = []
        if event.forecast:
            values.append(f"прогноз: {event.forecast}")
        if event.previous:
            values.append(f"пред.: {event.previous}")
        extra = f" ({'; '.join(values)})" if values else ""
        lines.append(
            f"- **{time_str}** | {event.country} ({event.currency}) | "
            f"важность: {event.importance} | {event.name}{extra}"
        )
    return "\n".join(lines)


async def build_focus_context(
    settings: Settings,
    *,
    calendar=None,
) -> FocusContext:
    yaml_cfg = load_yaml_config()
    tz_name = yaml_cfg.get("timezone", settings.timezone)
    dates = briefing_dates(datetime.now(ZoneInfo(tz_name)), tz_name)

    analytics = load_portfolio_analytics(settings)
    structure = await load_structure_analysis(analytics)
    screening_sectors = collect_screening_sectors(analytics, structure)

    if not structure or (
        not structure.portfolio_holdings
        and not structure.watchlist_sectors
        and not structure.watchlist_tracking_holdings
    ):
        logger.warning(
            "Структура ETF пуста или не загружена — анализ без входящих бумаг"
        )

    return FocusContext(
        analytics=analytics,
        structure=structure,
        screening_sectors=screening_sectors,
        companies_context=format_companies_for_prompt(structure),
        interest_sectors_context=format_interest_sectors_for_prompt(
            analytics, structure, screening_sectors
        ),
        calendar_context=_format_calendar_for_today(
            calendar or [],
            now=dates.local,
            tz_name=tz_name,
        ),
        dates=dates,
        calendar_events=list(calendar or []),
    )
