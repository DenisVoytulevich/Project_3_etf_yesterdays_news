from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from html import unescape

import httpx

from src.calendar.models import EconomicEvent
from src.calendar.macro_format import (
    MACRO_TABLE_HEADER,
    calendar_importance_to_stars,
    format_date_russian,
    format_index_impact,
)
from src.calendar.categories import (
    CATEGORY_LABELS,
    MANDATORY_CATEGORY_IDS,
    classify_macro_text,
    extract_macro_news,
    select_diverse_events,
)
from src.config import load_yaml_config

logger = logging.getLogger(__name__)

CALENDAR_URL = "https://www.investing.com/economic-calendar/Service/getCalendarFilteredData"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Referer": "https://www.investing.com/economic-calendar/",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://www.investing.com",
}

# Investing.com country IDs — основные экономики портфеля (США, Еврозона, UK, Япония и др.)
DEFAULT_COUNTRY_IDS = [5, 6, 37, 72, 35, 4, 17, 12, 26, 10, 22, 43]

_EVENT_ROW_RE = re.compile(
    r'<tr id="eventRowId_\d+".*?</tr>',
    re.DOTALL,
)
_DATETIME_RE = re.compile(r'data-event-datetime="([^"]+)"')
_COUNTRY_RE = re.compile(r'ceFlags\s+([^"\s]+)')
_CURRENCY_RE = re.compile(r'ceFlags[^>]+>\s*&nbsp;\s*</span>\s*([A-Z]{3})')
_EVENT_NAME_RE = re.compile(
    r'class="left event"[^>]*>.*?<a[^>]*>\s*(.*?)\s*</a>',
    re.DOTALL,
)
_ACTUAL_RE = re.compile(r'class="[^"]*event-\d+-actual[^"]*"[^>]*>([^<]*)<')
_FORECAST_RE = re.compile(r'class="[^"]*event-\d+-forecast[^"]*"[^>]*>([^<]*)<')
_PREVIOUS_RE = re.compile(r'class="[^"]*event-\d+-previous[^"]*"[^>]*>.*?<span[^>]*>([^<]*)</span>')


def _importance_from_bulls(html: str) -> str:
    bulls = len(re.findall(r"grayFullBullishIcon", html))
    if bulls >= 3:
        return "высокая"
    if bulls == 2:
        return "средняя"
    return "низкая"


def _clean_cell(text: str) -> str | None:
    cleaned = unescape(re.sub(r"<[^>]+>", "", text)).strip()
    return cleaned or None


def _parse_event_row(row_html: str) -> EconomicEvent | None:
    dt_match = _DATETIME_RE.search(row_html)
    name_match = _EVENT_NAME_RE.search(row_html)
    if not dt_match or not name_match:
        return None

    try:
        event_at = datetime.strptime(dt_match.group(1), "%Y/%m/%d %H:%M:%S")
    except ValueError:
        return None

    country_match = _COUNTRY_RE.search(row_html)
    currency_match = _CURRENCY_RE.search(row_html)
    actual_match = _ACTUAL_RE.search(row_html)
    forecast_match = _FORECAST_RE.search(row_html)
    previous_match = _PREVIOUS_RE.search(row_html)

    return EconomicEvent(
        event_at=event_at,
        country=(country_match.group(1).replace("_", " ") if country_match else "—"),
        currency=currency_match.group(1) if currency_match else "—",
        name=_clean_cell(name_match.group(1)) or "—",
        importance=_importance_from_bulls(row_html),
        actual=_clean_cell(actual_match.group(1)) if actual_match else None,
        forecast=_clean_cell(forecast_match.group(1)) if forecast_match else None,
        previous=_clean_cell(previous_match.group(1)) if previous_match else None,
    )


def _parse_calendar_html(html: str) -> list[EconomicEvent]:
    events: list[EconomicEvent] = []
    for row in _EVENT_ROW_RE.findall(html):
        event = _parse_event_row(row)
        if event:
            event.category = classify_macro_text(event.name)
            events.append(event)
    return events


async def collect_economic_calendar(
    *,
    now: datetime | None = None,
    days_ahead: int | None = None,
) -> list[EconomicEvent]:
    """Загружает макро-календарь Investing.com на текущую неделю."""
    yaml_cfg = load_yaml_config()
    cal_cfg = yaml_cfg.get("economic_calendar", {})
    if cal_cfg.get("enabled", True) is False:
        return []

    now = now or datetime.now()
    days_ahead = days_ahead or cal_cfg.get("days_ahead", 7)
    country_ids = cal_cfg.get("country_ids", DEFAULT_COUNTRY_IDS)
    min_importance = cal_cfg.get("min_importance", "средняя")

    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=days_ahead)

    body: dict = {
        "dateFrom": start.strftime("%Y-%m-%d"),
        "dateTo": end.strftime("%Y-%m-%d"),
        "timeZone": cal_cfg.get("timezone_id", 18),
        "timeFilter": "timeRemain",
        "currentTab": "custom",
        "limit_from": 0,
    }
    for cid in country_ids:
        body.setdefault("country[]", [])
        if isinstance(body["country[]"], list):
            body["country[]"].append(cid)
    for imp in (3, 2, 1):
        body.setdefault("importance[]", [])
        if isinstance(body["importance[]"], list):
            body["importance[]"].append(imp)

    try:
        async with httpx.AsyncClient(timeout=30, headers=DEFAULT_HEADERS) as client:
            response = await client.post(CALENDAR_URL, data=body)
            response.raise_for_status()
            payload = response.json()
    except Exception as e:
        logger.error("Не удалось загрузить экономический календарь: %s", e)
        return []

    html = payload.get("data", "")
    if not html:
        logger.warning("Экономический календарь вернул пустые данные")
        return []

    events = _parse_calendar_html(html)
    importance_rank = {"высокая": 3, "средняя": 2, "низкая": 1}
    min_rank = importance_rank.get(min_importance, 2)
    filtered = [e for e in events if importance_rank.get(e.importance, 0) >= min_rank]
    filtered.sort(key=lambda e: (e.event_at, -importance_rank.get(e.importance, 0)))

    logger.info(
        "Загружено %d макро-событий (из %d, фильтр ≥%s)",
        len(filtered),
        len(events),
        min_importance,
    )
    return filtered


def format_calendar_for_prompt(
    events: list[EconomicEvent],
    news_items: list | None = None,
) -> str:
    if not events and not news_items:
        return "_Календарь макро-событий не загружен или пуст_"

    lines = [
        "Календарь предстоящих макро-событий (источник: Investing.com).",
        "",
        "**Обязательные категории для §5.1** — в таблице должны быть представлены все релевантные:",
    ]
    for cat_id in MANDATORY_CATEGORY_IDS:
        lines.append(f"- {CATEGORY_LABELS[cat_id]}")

    lines.append("")
    lines.append("Покрытие категорий в календаре на неделю:")
    for cat_id in MANDATORY_CATEGORY_IDS:
        count = sum(1 for e in events if e.category == cat_id)
        status = f"{count} событ." if count else "нет в календаре — дополни из новостей"
        lines.append(f"- {CATEGORY_LABELS[cat_id]}: {status}")

    lines.append("")
    lines.append(f"События по категориям ({len(events)} шт.):")
    for cat_id in MANDATORY_CATEGORY_IDS:
        cat_events = [e for e in events if e.category == cat_id]
        if not cat_events:
            continue
        lines.append(f"")
        lines.append(f"### {CATEGORY_LABELS[cat_id]}")
        for event in cat_events[:12]:
            date_str = event.event_at.strftime("%d.%m %H:%M")
            values = []
            if event.forecast:
                values.append(f"прогноз: {event.forecast}")
            if event.previous:
                values.append(f"пред.: {event.previous}")
            if event.actual:
                values.append(f"факт: {event.actual}")
            extra = f" ({'; '.join(values)})" if values else ""
            lines.append(
                f"- **{date_str}** | {event.country} ({event.currency}) | "
                f"важность: {event.importance} | {event.name}{extra}"
            )

    macro_news = extract_macro_news(news_items or [])
    if macro_news:
        lines.append("")
        lines.append("### Дополнение из новостей (геополитика, санкции, решения правительств)")
        for item in macro_news:
            lines.append(
                f"- **{item.date_str}** | {CATEGORY_LABELS[item.category]} | "
                f"{item.title} | {item.summary}"
            )

    return "\n".join(lines)


def format_calendar_as_table(
    events: list[EconomicEvent],
    *,
    limit: int = 10,
    news_items: list | None = None,
) -> str:
    """Fallback-таблица §5.1 из календаря без AI."""
    selected = select_diverse_events(events, limit=limit)
    macro_news = extract_macro_news(news_items or [])

    if not selected and not macro_news:
        return (
            f"{MACRO_TABLE_HEADER}\n"
            "| — | Значимых событий не выявлено | — | — | — |"
        )

    currency_affects = {
        "USD": "Рынки США, облигации",
        "EUR": "Еврозона, банки",
        "GBP": "Великобритания, промышленность",
        "JPY": "Япония, экспорт",
        "CNY": "Китай, сырьё",
    }

    lines = [MACRO_TABLE_HEADER]
    for event in selected:
        date_str = format_date_russian(event.event_at)
        affects = currency_affects.get(event.currency, event.country)
        stars = calendar_importance_to_stars(event.importance)
        impact = format_index_impact(event.name, stars, event.currency)
        lines.append(
            f"| {date_str} | {event.name} | {stars} | {affects} | {impact} |"
        )

    for item in macro_news:
        if len(lines) - 1 >= limit:
            break
        stars = "★★★★☆"
        impact = format_index_impact(item.title, stars)
        lines.append(
            f"| {item.date_str} | {item.title} | {stars} | Глобальные рынки | {impact} |"
        )

    return "\n".join(lines)
