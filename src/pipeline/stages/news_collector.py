"""News Collector: сбор, дедупликация, фильтр по времени."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from src.config import Settings, load_yaml_config
from src.news.aggregator import collect_news
from src.news.models import NewsItem
from src.pipeline.models import FocusContext, NewsBatch

logger = logging.getLogger(__name__)


def _normalize_title(text: str) -> str:
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _yesterday_window(tz_name: str) -> tuple[datetime, datetime]:
    local = datetime.now(ZoneInfo(tz_name))
    yesterday = (local - timedelta(days=1)).date()
    start = datetime(
        yesterday.year, yesterday.month, yesterday.day, tzinfo=ZoneInfo(tz_name)
    )
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _deduplicate_news(items: list[NewsItem]) -> tuple[list[NewsItem], int]:
    seen_exact: set[str] = set()
    seen_normalized: set[str] = set()
    unique: list[NewsItem] = []
    removed = 0

    for item in items:
        if item.title in seen_exact:
            removed += 1
            continue
        norm = _normalize_title(item.title)
        if norm in seen_normalized:
            removed += 1
            continue
        seen_exact.add(item.title)
        seen_normalized.add(norm)
        unique.append(item)

    return unique, removed


def _filter_by_time(
    items: list[NewsItem],
    *,
    tz_name: str,
    lookback_hours: int,
) -> tuple[list[NewsItem], int]:
    tz = ZoneInfo(tz_name)
    yesterday = (datetime.now(tz) - timedelta(days=1)).date()
    start_utc, end_utc = _yesterday_window(tz_name)
    lookback_start = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    window_start = min(start_utc, lookback_start)

    kept: list[NewsItem] = []
    removed = 0
    for item in items:
        published = item.published
        if published is None:
            kept.append(item)
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        pub_local_date = published.astimezone(tz).date()
        if pub_local_date == yesterday or window_start <= published < end_utc:
            kept.append(item)
        else:
            removed += 1

    return kept, removed


async def run_news_collector(
    focus: FocusContext,
    settings: Settings,
) -> NewsBatch:
    yaml_cfg = load_yaml_config()
    tz_name = yaml_cfg.get("timezone", settings.timezone)
    lookback_hours = int(yaml_cfg.get("news", {}).get("lookback_hours", 36))

    raw = await collect_news(
        focus.analytics,
        settings,
        structure=focus.structure,
    )
    deduped, dup_removed = _deduplicate_news(raw)
    filtered, time_removed = _filter_by_time(
        deduped,
        tz_name=tz_name,
        lookback_hours=lookback_hours,
    )
    filtered.sort(
        key=lambda item: (
            item.priority,
            item.published or datetime.min.replace(tzinfo=timezone.utc),
        )
    )

    logger.info(
        "News Collector: %d → %d (дубли: %d, вне окна: %d)",
        len(raw),
        len(filtered),
        dup_removed,
        time_removed,
    )
    if len(filtered) < 8 and not settings.newsapi_key:
        logger.error(
            "Мало новостей (%d): задайте NEWSAPI_KEY в .env на сервере — "
            "без него остаются только RSS-материалы за вчера",
            len(filtered),
        )
    elif len(filtered) < 8:
        logger.warning(
            "Мало новостей после фильтра (%d) — проверьте NewsAPI и RSS",
            len(filtered),
        )
    return NewsBatch(
        items=filtered,
        removed_duplicates=dup_removed,
        removed_by_time=time_removed,
    )
