"""Автогенерация sector_leaders.yaml из Google Sheets + состава ETF."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from src.config import get_project_root, load_yaml_config
from src.data.models import InterestZoneItem, PortfolioAnalytics, SectorInterest
from src.structure.labels import (
    holding_keywords_for_sector,
    sector_aliases,
    sector_label,
)
from src.structure.models import EtfHolding, EtfHoldings

logger = logging.getLogger(__name__)

_AUTO_HEADER = (
    "# АВТОГЕНЕРАЦИЯ — не редактировать вручную.\n"
    "# Источник: Google Таблица (Watchlist, отрасли) + состав ETF (Investing.com).\n"
    "# Пересоздаётся при каждом запуске пайплайна.\n\n"
)


def generated_leaders_path() -> Path:
    cfg = load_yaml_config().get("structure", {})
    rel = cfg.get("sector_leaders_file", "data/generated/sector_leaders.yaml")
    path = Path(rel)
    if not path.is_absolute():
        path = get_project_root() / path
    return path


def _sectors_match(interest_sector: str, etf_sector: str) -> bool:
    interest_aliases = set(sector_aliases(interest_sector))
    etf_aliases = set(sector_aliases(etf_sector))
    if interest_aliases & etf_aliases:
        return True
    for left in interest_aliases:
        for right in etf_aliases:
            if left in right or right in left:
                return True
    return False


def _holding_key(symbol: str, name: str) -> str:
    if symbol and symbol.strip() and symbol != "—":
        return symbol.strip().upper()
    return name.strip().lower()


def _collect_sectors(
    watchlist_sector_rows: list,
    interest_zone: list[InterestZoneItem],
    sector_interests: list[SectorInterest] | None,
) -> list[str]:
    from src.structure.aggregation import _collect_tracking_sectors

    return _collect_tracking_sectors(
        watchlist_sector_rows, interest_zone, sector_interests
    )



def _score_holding(
    scored: dict[str, tuple[float, str, str]],
    holding: EtfHolding,
    score: float,
) -> None:
    key = _holding_key(holding.symbol, holding.name)
    if not key:
        return
    symbol = holding.symbol.strip() if holding.symbol else "—"
    prev = scored.get(key)
    if prev is None or score > prev[0]:
        scored[key] = (score, holding.name, symbol or "—")


def _etf_name_matches_sector(etf_name: str, sector: str) -> bool:
    keywords = holding_keywords_for_sector(sector)
    if not keywords:
        return False
    text = etf_name.lower()
    return any(keyword in text for keyword in keywords)


def _interest_zone_etf_name(analytics: PortfolioAnalytics, isin: str) -> str:
    key = isin.upper()
    for item in analytics.interest_zone:
        if item.isin and item.isin.upper() == key:
            return item.name
    return ""


def _is_sector_only_interest(sector: str, watchlist_sector_rows: list) -> bool:
    """Отрасль из Watchlist без привязанного ETF (строка §4 с ISIN «—»)."""
    key = sector.strip().lower()
    for row in watchlist_sector_rows:
        if row.isin != "—":
            continue
        if row.sector.strip().lower() == key:
            return True
    return False


def _all_loaded_etf_isins(holdings_map: dict[str, EtfHoldings]) -> list[str]:
    """Все ETF с загруженным составом: портфель + watchlist."""
    return list(holdings_map.keys())


def _etf_sector_weight(
    etf: EtfHoldings,
    sector: str,
    *,
    sectors_per_etf: int,
    all_sectors: bool,
) -> float:
    allocations = etf.sectors or []
    if not all_sectors:
        allocations = allocations[:sectors_per_etf]
    sector_weight = 0.0
    for alloc in allocations:
        raw = alloc.name
        label = sector_label(raw)
        if _sectors_match(sector, label) or _sectors_match(sector, raw):
            sector_weight = max(sector_weight, alloc.weight_pct)
    return sector_weight


def _holding_matches_keywords(holding: EtfHolding, keywords: list[str]) -> bool:
    if not keywords:
        return False
    text = f"{holding.name} {holding.symbol}".lower()
    return any(keyword in text for keyword in keywords)


def _pick_leaders_for_sector(
    sector: str,
    etf_isins: list[str],
    holdings_map: dict[str, EtfHoldings],
    analytics: PortfolioAnalytics,
    *,
    sectors_per_etf: int,
    limit: int,
    sector_only: bool = False,
) -> list[dict[str, str]]:
    scored: dict[str, tuple[float, str, str]] = {}
    keywords = holding_keywords_for_sector(sector)

    if sector_only:
        if keywords:
            for etf in holdings_map.values():
                if not etf.holdings:
                    continue
                for holding in etf.holdings:
                    if _holding_matches_keywords(holding, keywords):
                        _score_holding(scored, holding, holding.weight_pct)
    else:
        for isin in etf_isins:
            etf = holdings_map.get(isin)
            if not etf or not etf.holdings:
                continue

            sector_weight = _etf_sector_weight(
                etf,
                sector,
                sectors_per_etf=sectors_per_etf,
                all_sectors=False,
            )

            if sector_weight > 0:
                for holding in etf.holdings:
                    _score_holding(scored, holding, holding.weight_pct * sector_weight)
            elif _etf_name_matches_sector(_interest_zone_etf_name(analytics, isin), sector):
                for holding in etf.holdings:
                    _score_holding(scored, holding, holding.weight_pct * 100)
            elif keywords:
                for holding in etf.holdings:
                    if _holding_matches_keywords(holding, keywords):
                        _score_holding(scored, holding, holding.weight_pct)

        if not scored and keywords:
            for etf in holdings_map.values():
                if not etf.holdings:
                    continue
                for holding in etf.holdings:
                    if _holding_matches_keywords(holding, keywords):
                        _score_holding(scored, holding, holding.weight_pct)

    ranked = sorted(scored.values(), key=lambda item: (-item[0], item[1].lower()))
    return [
        {"name": name, "symbol": symbol}
        for _, name, symbol in ranked[:limit]
    ]


def generate_sector_leaders_from_google(
    analytics: PortfolioAnalytics,
    watchlist_sector_rows: list,
    holdings_map: dict[str, EtfHoldings],
    *,
    sectors_per_etf: int,
    top_per_sector: int,
) -> dict[str, list[dict[str, str]]]:
    """Строит справочник лидеров по отраслям из Watchlist Google и состава ETF."""
    sectors = _collect_sectors(
        watchlist_sector_rows,
        analytics.interest_zone,
        analytics.sector_interests,
    )
    etf_isins = _all_loaded_etf_isins(holdings_map)

    leaders: dict[str, list[dict[str, str]]] = {}
    for sector in sectors:
        rows = _pick_leaders_for_sector(
            sector,
            etf_isins,
            holdings_map,
            analytics,
            sectors_per_etf=sectors_per_etf,
            limit=top_per_sector,
            sector_only=_is_sector_only_interest(sector, watchlist_sector_rows),
        )
        if rows:
            leaders[sector] = rows
        else:
            logger.warning(
                "Не удалось подобрать бумаги для отрасли «%s» "
                "(нет совпадений в составе ETF портфеля и watchlist)",
                sector,
            )

    logger.info(
        "Сгенерирован sector_leaders: %d отраслей, %d ETF в выборке",
        len(leaders),
        len(etf_isins),
    )
    return leaders


def write_sector_leaders_yaml(
    leaders: dict[str, list[dict[str, str]]],
    path: Path | None = None,
) -> Path:
    out = path or generated_leaders_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.dump(
        {"leaders": leaders},
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    out.write_text(_AUTO_HEADER + body, encoding="utf-8")
    logger.info("Записан %s (%d отраслей)", out.resolve(), len(leaders))
    return out.resolve()
