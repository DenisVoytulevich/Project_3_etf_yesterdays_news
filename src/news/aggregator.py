import logging
import re
from datetime import datetime, timedelta, timezone
from time import struct_time
from typing import Any
from zoneinfo import ZoneInfo

import feedparser
import httpx

from src.companies.context import (
    CompanySearchTerm,
    TrackedCompany,
    build_company_search_terms,
    build_unified_company_list,
    company_search_query_term,
    short_company_name_for_query,
)
from src.config import Settings, load_yaml_config
from src.data.models import PortfolioAnalytics
from src.news.models import NewsItem, NewsPriority
from src.sectors.interest import collect_screening_sectors
from src.structure.aggregation import StructureAnalysis

logger = logging.getLogger(__name__)


def _parse_published(entry: dict[str, Any]) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed: struct_time | None = entry.get(key)
        if parsed:
            return datetime(*parsed[:6], tzinfo=timezone.utc)
    return None


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


def _build_keyword_map(analytics: PortfolioAnalytics) -> dict[str, dict]:
    """Маппинг ключевых слов → метаданные для приоритизации."""
    mapping: dict[str, dict] = {}

    for pos in analytics.top_holdings:
        for kw in filter(None, [pos.ticker, pos.name]):
            mapping[kw.lower()] = {
                "priority": NewsPriority.PORTFOLIO,
                "tickers": [pos.ticker],
                "sectors": [pos.sector],
            }

    for item in analytics.interest_zone:
        if not item.isin:
            sector = item.sector.strip()
            if sector and sector != "—":
                mapping[sector.lower()] = {
                    "priority": NewsPriority.SECTOR,
                    "tickers": [],
                    "sectors": [sector],
                }
            continue

        for kw in filter(None, [item.ticker, item.name]):
            existing = mapping.get(kw.lower())
            if existing and existing["priority"] <= NewsPriority.WATCHLIST:
                continue
            mapping[kw.lower()] = {
                "priority": NewsPriority.WATCHLIST,
                "tickers": [item.ticker] if item.ticker else [],
                "sectors": [item.sector] if item.sector != "—" else [],
            }

    for item in analytics.watchlist:
        for kw in filter(None, [item.ticker, item.name]):
            existing = mapping.get(kw.lower())
            if existing and existing["priority"] <= NewsPriority.WATCHLIST:
                continue
            mapping[kw.lower()] = {
                "priority": NewsPriority.WATCHLIST,
                "tickers": [item.ticker],
                "sectors": [item.sector],
            }

    for sector in analytics.interest_sectors:
        mapping[sector.lower()] = {
            "priority": NewsPriority.SECTOR,
            "tickers": [],
            "sectors": [sector],
        }

    return mapping


def extend_keyword_map_with_structure(
    keyword_map: dict[str, dict],
    structure: StructureAnalysis | None,
) -> dict[str, dict]:
    """Добавляет ключевые слова из §3.1, §4 и §4.1 для приоритизации новостей."""
    if not structure:
        return keyword_map

    def _add(
        keyword: str,
        *,
        priority: NewsPriority,
        tickers: list[str],
        sectors: list[str],
    ) -> None:
        kw = keyword.strip().lower()
        if not kw or kw == "—":
            return
        existing = keyword_map.get(kw)
        if existing and existing["priority"] <= priority:
            return
        keyword_map[kw] = {
            "priority": priority,
            "tickers": tickers,
            "sectors": sectors,
        }

    for holding in structure.portfolio_holdings:
        tickers = [holding.symbol] if holding.symbol and holding.symbol != "—" else []
        _add(holding.name, priority=NewsPriority.PORTFOLIO, tickers=tickers, sectors=[])
        if tickers:
            _add(tickers[0], priority=NewsPriority.PORTFOLIO, tickers=tickers, sectors=[])

    for holding in structure.watchlist_tracking_holdings:
        tickers = [holding.symbol] if holding.symbol and holding.symbol != "—" else []
        _add(holding.name, priority=NewsPriority.WATCHLIST, tickers=tickers, sectors=[])
        if tickers:
            _add(tickers[0], priority=NewsPriority.WATCHLIST, tickers=tickers, sectors=[])

    for row in structure.watchlist_sectors:
        if row.instrument_name and row.instrument_name != "—":
            _add(
                row.instrument_name,
                priority=NewsPriority.WATCHLIST,
                tickers=[],
                sectors=[],
            )
        if row.isin and row.isin != "—":
            _add(row.isin, priority=NewsPriority.WATCHLIST, tickers=[], sectors=[])
        for part in (row.sector or "").split(","):
            sector = part.strip()
            if sector and sector != "—":
                _add(
                    sector,
                    priority=NewsPriority.SECTOR,
                    tickers=[],
                    sectors=[sector],
                )

    return keyword_map


def extend_keyword_map_with_companies(
    keyword_map: dict[str, dict],
    companies: list[TrackedCompany],
) -> dict[str, dict]:
    """Добавляет поисковые термины компаний для классификации новостей."""

    def _add(
        keyword: str,
        *,
        priority: NewsPriority,
        tickers: list[str],
        sectors: list[str],
    ) -> None:
        kw = keyword.strip().lower()
        if not kw or kw == "—":
            return
        existing = keyword_map.get(kw)
        if existing and existing["priority"] <= priority:
            return
        keyword_map[kw] = {
            "priority": priority,
            "tickers": tickers,
            "sectors": sectors,
        }

    for company in companies:
        priority = (
            NewsPriority.PORTFOLIO
            if company.zone == "Портфель"
            else NewsPriority.WATCHLIST
        )
        tickers = (
            [company.symbol.strip().upper()]
            if company.symbol and company.symbol != "—"
            else []
        )
        sectors = [company.sector] if company.sector and company.sector != "—" else []

        for keyword in filter(
            None,
            [
                company.name,
                company.symbol if company.symbol != "—" else None,
                company_search_query_term(company),
                short_company_name_for_query(company.name),
            ],
        ):
            _add(
                keyword,
                priority=priority,
                tickers=tickers,
                sectors=sectors,
            )

    return keyword_map


def _classify_news(
    title: str, summary: str, keyword_map: dict[str, dict]
) -> tuple[NewsPriority, list[str], list[str], list[str]]:
    text = _normalize_text(f"{title} {summary}")
    best_priority = NewsPriority.GENERAL
    matched: list[str] = []
    tickers: set[str] = set()
    sectors: set[str] = set()

    for keyword, meta in keyword_map.items():
        if keyword in text or re.search(rf"\b{re.escape(keyword)}\b", text):
            matched.append(keyword)
            tickers.update(meta["tickers"])
            sectors.update(meta["sectors"])
            if meta["priority"] < best_priority:
                best_priority = meta["priority"]

    return best_priority, matched, sorted(tickers), sorted(sectors)


def _fetch_rss(source: dict) -> list[dict[str, Any]]:
    try:
        feed = feedparser.parse(source["url"])
        if feed.bozo and not feed.entries:
            logger.warning("RSS ошибка для %s: %s", source["name"], feed.bozo_exception)
            return []
        return feed.entries
    except Exception as e:
        logger.error("Не удалось загрузить RSS %s: %s", source["name"], e)
        return []


async def _fetch_newsapi(
    settings: Settings,
    query: str,
    limit: int = 20,
    *,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
) -> list[dict[str, Any]]:
    if not settings.newsapi_key:
        return []

    url = "https://newsapi.org/v2/everything"
    params: dict[str, Any] = {
        "q": query,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": limit,
        "apiKey": settings.newsapi_key,
    }
    if from_dt is not None:
        params["from"] = from_dt.strftime("%Y-%m-%dT%H:%M:%S")
    if to_dt is not None:
        params["to"] = to_dt.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json().get("articles", [])
    except Exception as e:
        logger.error("NewsAPI ошибка: %s", e)
        return []


def _rss_to_news_item(
    entry: dict[str, Any],
    source_name: str,
    keyword_map: dict[str, dict],
) -> NewsItem | None:
    title = entry.get("title", "").strip()
    if not title:
        return None

    summary = entry.get("summary", entry.get("description", ""))
    summary = re.sub(r"<[^>]+>", "", summary)[:500]

    link = entry.get("link", "")
    priority, matched, tickers, sectors = _classify_news(title, summary, keyword_map)

    return NewsItem(
        title=title,
        summary=summary,
        url=link,
        source=source_name,
        published=_parse_published(entry),
        priority=priority,
        matched_keywords=matched,
        related_tickers=tickers,
        related_sectors=sectors,
    )


def _newsapi_to_news_item(
    article: dict[str, Any], keyword_map: dict[str, dict]
) -> NewsItem | None:
    title = article.get("title", "").strip()
    if not title or title == "[Removed]":
        return None

    summary = article.get("description", "") or ""
    priority, matched, tickers, sectors = _classify_news(title, summary, keyword_map)

    published = None
    if article.get("publishedAt"):
        try:
            published = datetime.fromisoformat(
                article["publishedAt"].replace("Z", "+00:00")
            )
        except ValueError:
            pass

    return NewsItem(
        title=title,
        summary=summary[:500],
        url=article.get("url", ""),
        source=article.get("source", {}).get("name", "NewsAPI"),
        published=published,
        priority=priority,
        matched_keywords=matched,
        related_tickers=tickers,
        related_sectors=sectors,
    )


async def _fetch_mandatory_sector_news(
    settings: Settings,
    sectors: list[str],
    keyword_map: dict[str, dict],
    seen_titles: set[str],
    items: list[NewsItem],
    *,
    batch_size: int = 3,
    per_batch: int = 15,
) -> int:
    """Обязательный NewsAPI-скрининг по каждой отрасли интереса (батчами)."""
    if not settings.newsapi_key or not sectors:
        return 0

    added = 0
    for i in range(0, len(sectors), batch_size):
        batch = sectors[i : i + batch_size]
        terms = " OR ".join(f'"{sector}"' for sector in batch)
        query = f"({terms}) AND (market OR stocks OR earnings OR sector)"
        articles = await _fetch_newsapi(settings, query, limit=per_batch)
        for article in articles:
            item = _newsapi_to_news_item(article, keyword_map)
            if not item or item.title in seen_titles:
                continue
            seen_titles.add(item.title)
            if item.priority == NewsPriority.GENERAL and batch:
                item.priority = NewsPriority.SECTOR
                item.related_sectors = sorted(
                    {s for s in batch if s.lower() in _normalize_text(f"{item.title} {item.summary}")}
                    or batch[:1]
                )
            items.append(item)
            added += 1
    return added


def _yesterday_range_utc(tz_name: str) -> tuple[datetime, datetime]:
    local = datetime.now(ZoneInfo(tz_name))
    yesterday = (local - timedelta(days=1)).date()
    start = datetime(
        yesterday.year,
        yesterday.month,
        yesterday.day,
        0,
        0,
        0,
        tzinfo=ZoneInfo(tz_name),
    )
    end = datetime(
        yesterday.year,
        yesterday.month,
        yesterday.day,
        23,
        59,
        59,
        tzinfo=ZoneInfo(tz_name),
    )
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _newsapi_query_term(term: str) -> str:
    if " " in term or "." in term:
        return f'"{term}"'
    return term


def _company_news_query(terms: list[CompanySearchTerm]) -> str:
    joined = " OR ".join(_newsapi_query_term(item.query) for item in terms)
    return (
        f"({joined}) AND "
        "(stock OR shares OR earnings OR company OR CEO OR guidance OR deal OR "
        "merger OR dividend OR profit OR revenue OR forecast OR outlook OR analyst)"
    )


async def _fetch_mandatory_company_news(
    settings: Settings,
    companies: list[TrackedCompany],
    keyword_map: dict[str, dict],
    seen_titles: set[str],
    items: list[NewsItem],
    *,
    from_dt: datetime,
    to_dt: datetime,
    batch_size: int = 5,
    per_batch: int = 10,
) -> int:
    """Целевой NewsAPI-скрининг компаний портфеля и watchlist (батчами)."""
    search_terms = build_company_search_terms(companies)
    if not settings.newsapi_key or not search_terms:
        return 0

    added = 0
    for i in range(0, len(search_terms), batch_size):
        batch = search_terms[i : i + batch_size]
        query = _company_news_query(batch)
        articles = await _fetch_newsapi(
            settings,
            query,
            limit=per_batch,
            from_dt=from_dt,
            to_dt=to_dt,
        )
        for article in articles:
            item = _newsapi_to_news_item(article, keyword_map)
            if not item or item.title in seen_titles:
                continue

            text = _normalize_text(f"{item.title} {item.summary}")
            matched_batch = [
                entry
                for entry in batch
                if entry.query.lower() in text
                or re.search(rf"\b{re.escape(entry.query.lower())}\b", text)
            ]
            if not matched_batch:
                continue

            seen_titles.add(item.title)
            if item.priority >= NewsPriority.WATCHLIST:
                company = matched_batch[0].company
                item.priority = (
                    NewsPriority.PORTFOLIO
                    if company.zone == "Портфель"
                    else NewsPriority.WATCHLIST
                )
                if company.symbol and company.symbol != "—":
                    item.related_tickers = sorted(
                        {company.symbol.upper(), *item.related_tickers}
                    )
                if company.sector and company.sector != "—":
                    item.related_sectors = sorted(
                        {company.sector, *item.related_sectors}
                    )
            item.matched_keywords = sorted(
                {*item.matched_keywords, *[entry.query for entry in matched_batch]}
            )
            items.append(item)
            added += 1

    return added


async def collect_news(
    analytics: PortfolioAnalytics,
    settings: Settings,
    structure: StructureAnalysis | None = None,
) -> list[NewsItem]:
    yaml_cfg = load_yaml_config()
    sources = yaml_cfg.get("news_sources", [])
    per_source = yaml_cfg.get("news_per_source", 15)
    news_cfg = yaml_cfg.get("news", {})
    tz_name = yaml_cfg.get("timezone", settings.timezone)
    companies = build_unified_company_list(structure)
    keyword_map = _build_keyword_map(analytics)
    keyword_map = extend_keyword_map_with_structure(keyword_map, structure)
    keyword_map = extend_keyword_map_with_companies(keyword_map, companies)

    screening_sectors = collect_screening_sectors(analytics, structure)
    for sector in screening_sectors:
        kw = sector.strip().lower()
        if kw and kw not in keyword_map:
            keyword_map[kw] = {
                "priority": NewsPriority.SECTOR,
                "tickers": [],
                "sectors": [sector],
            }

    items: list[NewsItem] = []
    seen_titles: set[str] = set()

    for source in sources:
        entries = _fetch_rss(source)[:per_source]
        for entry in entries:
            item = _rss_to_news_item(entry, source["name"], keyword_map)
            if item and item.title not in seen_titles:
                seen_titles.add(item.title)
                items.append(item)

    if settings.newsapi_key:
        tickers_query = " OR ".join(analytics.tickers[:10])
        sectors_query = " OR ".join(f'"{s}"' for s in screening_sectors[:8])
        if tickers_query and sectors_query:
            query = f"({tickers_query}) OR ({sectors_query})"
        elif sectors_query:
            query = sectors_query
        else:
            query = f"ETF ({tickers_query})" if tickers_query else ""
        if query:
            articles = await _fetch_newsapi(settings, query, limit=30)
            for article in articles:
                item = _newsapi_to_news_item(article, keyword_map)
                if item and item.title not in seen_titles:
                    seen_titles.add(item.title)
                    items.append(item)

        if news_cfg.get("mandatory_sector_screening", True) and screening_sectors:
            batch_size = int(news_cfg.get("sector_query_batch_size", 3))
            per_batch = int(news_cfg.get("sector_query_per_batch", 15))
            sector_added = await _fetch_mandatory_sector_news(
                settings,
                screening_sectors,
                keyword_map,
                seen_titles,
                items,
                batch_size=batch_size,
                per_batch=per_batch,
            )
            logger.info(
                "Обязательный скрининг отраслей: %d отраслей, +%d новостей",
                len(screening_sectors),
                sector_added,
            )

        if news_cfg.get("mandatory_company_screening", True) and companies:
            from_dt, to_dt = _yesterday_range_utc(tz_name)
            company_batch_size = int(news_cfg.get("company_query_batch_size", 5))
            company_per_batch = int(news_cfg.get("company_query_per_batch", 10))
            search_terms = build_company_search_terms(companies)
            company_added = await _fetch_mandatory_company_news(
                settings,
                companies,
                keyword_map,
                seen_titles,
                items,
                from_dt=from_dt,
                to_dt=to_dt,
                batch_size=company_batch_size,
                per_batch=company_per_batch,
            )
            batch_count = (
                (len(search_terms) + company_batch_size - 1) // company_batch_size
                if search_terms
                else 0
            )
            logger.info(
                "Обязательный скрининг компаний: %d компаний, %d батч(ей), +%d новостей",
                len(search_terms),
                batch_count,
                company_added,
            )

    company_term_count = len(build_company_search_terms(companies))
    items.sort(key=lambda x: (x.priority, x.published or datetime.min.replace(tzinfo=timezone.utc)))
    logger.info(
        "Собрано %d новостей (портфель: %d, наблюдение: %d, отрасли: %d); "
        "отраслей в скрининге: %d; компаний в скрининге: %d",
        len(items),
        sum(1 for i in items if i.priority == NewsPriority.PORTFOLIO),
        sum(1 for i in items if i.priority == NewsPriority.WATCHLIST),
        sum(1 for i in items if i.priority == NewsPriority.SECTOR),
        len(screening_sectors),
        company_term_count,
    )
    return items


def format_news_for_prompt(items: list[NewsItem]) -> str:
    sections = {
        NewsPriority.PORTFOLIO: [],
        NewsPriority.WATCHLIST: [],
        NewsPriority.SECTOR: [],
        NewsPriority.GENERAL: [],
    }
    for item in items:
        if item.priority in sections:
            sections[item.priority].append(item)

    lines = []
    labels = {
        NewsPriority.PORTFOLIO: "Портфель",
        NewsPriority.WATCHLIST: "Наблюдение",
        NewsPriority.SECTOR: "Отрасли",
        NewsPriority.GENERAL: "Прочее",
    }
    for priority, label in labels.items():
        group = sections[priority]
        lines.append(f"### {label} ({len(group)} новостей)")
        if not group:
            lines.append("— нет релевантных новостей")
            continue
        for n in group[:15]:
            tickers = ", ".join(n.related_tickers) or "—"
            lines.append(f"- **{n.title}** [{n.source}]")
            lines.append(f"  Тикеры: {tickers} | {n.summary[:200]}")
            if n.url:
                lines.append(f"  URL: {n.url}")

    return "\n".join(lines)
