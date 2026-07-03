from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from src.data.models import (
    EtfPosition,
    InterestZoneItem,
    PortfolioAnalytics,
    RegionShare,
    SectorInterest,
    SectorShare,
    position_market_value,
)
from src.structure.collector import HoldingsFetchResult, fetch_holdings_batch
from src.structure.labels import infer_etf_theme_sectors, sector_label
from src.structure.sector_leaders import build_holding_sector_lookup, sector_leaders_as_holdings
from src.structure.models import EtfHolding, EtfHoldings, InstrumentQuote


@dataclass
class WeightedHolding:
    name: str
    symbol: str
    weight_pct: float
    sector: str = "—"


@dataclass
class WatchlistSectorRow:
    isin: str
    instrument_name: str
    sector: str
    weight_pct: float | None


@dataclass
class StructureAnalysis:
    portfolio_holdings: list[WeightedHolding] = field(default_factory=list)
    portfolio_etf_sectors: list[str] = field(default_factory=list)
    watchlist_sectors: list[WatchlistSectorRow] = field(default_factory=list)
    watchlist_tracking_holdings: list[WeightedHolding] = field(default_factory=list)
    fetch_errors: dict[str, str] = field(default_factory=dict)


def _top_sectors(holdings: EtfHoldings | None, limit: int) -> list[tuple[str, float]]:
    if not holdings or not holdings.sectors:
        return []
    return [
        (sector_label(s.name), s.weight_pct)
        for s in holdings.sectors[:limit]
    ]


def _collect_portfolio_etf_sectors(
    positions: list[EtfPosition],
    holdings_map: dict[str, EtfHoldings],
    *,
    sectors_per_etf: int = 5,
) -> list[str]:
    """TOP-N отраслей по каждому ETF портфеля (QTY > 0)."""
    sectors: list[str] = []
    seen: set[str] = set()

    for pos in positions:
        if not pos.isin:
            continue
        for theme in infer_etf_theme_sectors(pos.name, pos.ticker):
            key = theme.lower()
            if key in seen:
                continue
            seen.add(key)
            sectors.append(theme)
        for sector_name, _ in _top_sectors(
            holdings_map.get(pos.isin.upper()),
            sectors_per_etf,
        ):
            key = sector_name.lower()
            if key in seen:
                continue
            seen.add(key)
            sectors.append(sector_name)

    return sectors


def _position_portfolio_value(
    pos: EtfPosition,
    quotes: dict[str, InstrumentQuote],
) -> float:
    """Стоимость позиции в портфеле (QTY × цена EUR); без цены — по QTY."""
    if not pos.isin:
        return pos.volume
    quote = quotes.get(pos.isin.upper())
    if quote and quote.price_eur > 0:
        return pos.volume * quote.price_eur
    return pos.volume


def apply_monetary_weights(
    analytics: PortfolioAnalytics,
    quotes: dict[str, InstrumentQuote],
    *,
    top_count: int,
) -> None:
    """Пересчёт долей, топа и агрегатов портфеля по стоимости (QTY × цена EUR)."""
    positions = analytics.positions
    if not positions:
        return

    for pos in positions:
        pos.value_eur = _position_portfolio_value(pos, quotes)

    total = sum(position_market_value(p) for p in positions)
    analytics.total_volume = total
    if total <= 0:
        return

    for pos in positions:
        pos.weight = (position_market_value(pos) / total) * 100

    analytics.top_holdings = sorted(
        positions,
        key=lambda p: position_market_value(p),
        reverse=True,
    )[:top_count]

    sector_totals: dict[str, float] = {}
    region_totals: dict[str, float] = {}
    for pos in positions:
        value = position_market_value(pos)
        sector_totals[pos.sector] = sector_totals.get(pos.sector, 0) + value
        region_totals[pos.region] = region_totals.get(pos.region, 0) + value

    analytics.sector_shares = [
        SectorShare(sector=s, volume=v, share_pct=(v / total) * 100)
        for s, v in sector_totals.items()
    ]
    analytics.sector_shares.sort(key=lambda x: x.share_pct, reverse=True)

    analytics.region_shares = [
        RegionShare(region=r, volume=v, share_pct=(v / total) * 100)
        for r, v in region_totals.items()
    ]
    analytics.region_shares.sort(key=lambda x: x.share_pct, reverse=True)


def _aggregate_portfolio_holdings(
    positions: list[EtfPosition],
    holdings_map: dict[str, EtfHoldings],
    quotes: dict[str, InstrumentQuote],
    *,
    top_limit: int,
) -> tuple[list[WeightedHolding], dict[str, dict[str, float]]]:
    """TOP-N конечных бумаг, взвешенно по доле позиции ETF в портфеле."""
    total_value = sum(_position_portfolio_value(p, quotes) for p in positions)
    if total_value <= 0:
        return [], {}

    weights: dict[str, float] = defaultdict(float)
    symbols: dict[str, str] = {}
    names: dict[str, str] = {}
    sector_votes: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for pos in positions:
        if not pos.isin:
            continue
        etf_data = holdings_map.get(pos.isin.upper())
        if not etf_data or not etf_data.holdings:
            continue

        etf_share = _position_portfolio_value(pos, quotes) / total_value
        etf_sector = (
            sector_label(etf_data.sectors[0].name)
            if etf_data.sectors
            else None
        )
        for holding in etf_data.holdings:
            key = holding.symbol.upper() if holding.symbol else holding.name.strip().lower()
            if not key:
                continue
            contribution = (holding.weight_pct / 100.0) * etf_share * 100.0
            weights[key] += contribution
            symbols[key] = holding.symbol or "—"
            names[key] = holding.name
            if etf_sector:
                sector_votes[key][etf_sector] += contribution

    ranked = sorted(
        weights.items(),
        key=lambda item: (-item[1], names[item[0]].lower()),
    )
    holdings = [
        WeightedHolding(
            name=names[key],
            symbol=symbols[key],
            weight_pct=weight,
        )
        for key, weight in ranked[:top_limit]
    ]
    return holdings, {key: dict(votes) for key, votes in sector_votes.items()}


def _fill_portfolio_holding_sectors(
    holdings: list[WeightedHolding],
    sector_lookup: dict[str, str],
    sector_votes: dict[str, dict[str, float]],
) -> None:
    for holding in holdings:
        symbol = holding.symbol.strip().upper() if holding.symbol and holding.symbol != "—" else ""
        if symbol and symbol in sector_lookup:
            holding.sector = sector_lookup[symbol]
            continue
        name_key = holding.name.strip().lower()
        if name_key in sector_lookup:
            holding.sector = sector_lookup[name_key]
            continue
        normalized = _normalize_company_name(holding.name)
        if normalized and normalized in sector_lookup:
            holding.sector = sector_lookup[normalized]
            continue
        key = _holding_key(holding.symbol, holding.name)
        votes = sector_votes.get(key, {})
        if votes:
            holding.sector = max(votes.items(), key=lambda item: item[1])[0]


def _build_watchlist_sector_rows(
    interest_zone: list[InterestZoneItem],
    portfolio_isins: set[str],
    holdings_map: dict[str, EtfHoldings],
    *,
    sectors_per_etf: int,
) -> list[WatchlistSectorRow]:
    rows: list[WatchlistSectorRow] = []

    for item in interest_zone:
        if item.isin and item.isin.upper() in portfolio_isins:
            continue

        if not item.isin:
            rows.append(
                WatchlistSectorRow(
                    isin="—",
                    instrument_name="—",
                    sector=item.sector,
                    weight_pct=None,
                )
            )
            continue

        isin = item.isin.upper()
        name = item.name or "—"
        sectors = _top_sectors(holdings_map.get(isin), sectors_per_etf)
        if not sectors:
            rows.append(
                WatchlistSectorRow(
                    isin=isin,
                    instrument_name=name,
                    sector="—",
                    weight_pct=None,
                )
            )
            continue

        sector_text = ", ".join(sector_name for sector_name, _ in sectors)
        rows.append(
            WatchlistSectorRow(
                isin=isin,
                instrument_name=name,
                sector=sector_text,
                weight_pct=None,
            )
        )

    return rows


def _normalize_company_name(name: str) -> str:
    cleaned = name.strip().lower()
    for suffix in (
        " inc",
        " corp",
        " corporation",
        " ltd",
        " plc",
        " sa",
        " ag",
        " se",
        " co",
    ):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
    return re.sub(r"[^a-z0-9]", "", cleaned)


def _holding_key(symbol: str, name: str) -> str:
    if symbol and symbol.strip() and symbol != "—":
        return symbol.strip().upper()
    return name.strip().lower()


def _holding_exclusion_keys(symbol: str, name: str) -> set[str]:
    keys = {_holding_key(symbol, name)}
    normalized = _normalize_company_name(name)
    if normalized:
        keys.add(normalized)
    return keys


def _portfolio_exclude_keys(portfolio_holdings: list[WeightedHolding]) -> set[str]:
    excluded: set[str] = set()
    for holding in portfolio_holdings:
        excluded.update(_holding_exclusion_keys(holding.symbol, holding.name))
    return excluded


def _is_excluded(symbol: str, name: str, excluded: set[str], collected: dict[str, WeightedHolding]) -> bool:
    if _holding_exclusion_keys(symbol, name) & excluded:
        return True
    key = _holding_key(symbol, name)
    if key in collected:
        return True
    normalized = _normalize_company_name(name)
    if not normalized:
        return False
    return any(_normalize_company_name(item.name) == normalized for item in collected.values())


def _unique_sectors_from_watchlist_rows(rows: list[WatchlistSectorRow]) -> list[str]:
    """Уникальные отрасли из колонки «Отрасль» таблицы §4."""
    sectors: list[str] = []
    seen: set[str] = set()

    for row in rows:
        parts = [row.sector] if row.isin == "—" else row.sector.split(",")
        for part in parts:
            sector = part.strip()
            if not sector or sector == "—":
                continue
            key = sector.lower()
            if key in seen:
                continue
            seen.add(key)
            sectors.append(sector)

    return sectors


def _collect_tracking_sectors(
    watchlist_sector_rows: list[WatchlistSectorRow],
    interest_zone: list[InterestZoneItem],
    sector_interests: list[SectorInterest] | None = None,
) -> list[str]:
    """Все отрасли для §4.1: из таблицы §4, строк Watchlist без ISIN и листа sectors."""
    sectors = _unique_sectors_from_watchlist_rows(watchlist_sector_rows)
    seen = {s.lower() for s in sectors}

    for item in interest_zone:
        if item.isin:
            continue
        sector = item.sector.strip()
        if not sector or sector == "—":
            continue
        key = sector.lower()
        if key not in seen:
            seen.add(key)
            sectors.append(sector)

    for entry in sector_interests or []:
        sector = entry.sector.strip()
        if not sector:
            continue
        key = sector.lower()
        if key not in seen:
            seen.add(key)
            sectors.append(sector)

    return sectors


def _watchlist_etf_isins_from_rows(rows: list[WatchlistSectorRow]) -> list[str]:
    """ISIN ETF из колонки таблицы §4 (без строк только с отраслью)."""
    isins: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if row.isin == "—":
            continue
        isin = row.isin.upper()
        if isin in seen:
            continue
        seen.add(isin)
        isins.append(isin)
    return isins


def _etf_sector_by_isin(rows: list[WatchlistSectorRow]) -> dict[str, str]:
    return {
        row.isin.upper(): row.sector
        for row in rows
        if row.isin != "—"
    }


def _take_top_holdings(
    collected: dict[str, WeightedHolding],
    holdings: list[EtfHolding],
    limit: int,
    excluded: set[str],
    *,
    sector: str = "—",
) -> None:
    added = 0
    for holding in holdings:
        if added >= limit:
            break
        key = _holding_key(holding.symbol, holding.name)
        if not key or _is_excluded(holding.symbol, holding.name, excluded, collected):
            continue
        collected[key] = WeightedHolding(
            name=holding.name,
            symbol=holding.symbol or "—",
            weight_pct=holding.weight_pct,
            sector=sector,
        )
        added += 1


def _sectors_from_table4(watchlist_sector_rows: list[WatchlistSectorRow]) -> list[str]:
    """Уникальные отрасли только из колонки «Отрасль» таблицы §4."""
    return _unique_sectors_from_watchlist_rows(watchlist_sector_rows)


def _sector_cell(sector: str, *, max_count: int = 3) -> str:
    if not sector or sector.strip() == "—":
        return "—"
    parts = [part.strip() for part in sector.split(",") if part.strip()]
    return ", ".join(parts[:max_count]) if parts else "—"


def _build_watchlist_tracking_holdings(
    interest_zone: list[InterestZoneItem],
    portfolio_isins: set[str],
    holdings_map: dict[str, EtfHoldings],
    portfolio_holdings: list[WeightedHolding],
    watchlist_sector_rows: list[WatchlistSectorRow],
    *,
    top_per_source: int,
    sectors_per_etf: int,
    sector_interests: list[SectorInterest] | None = None,
) -> list[WeightedHolding]:
    """TOP-N для §4.1: мировые лидеры по каждой отрасли §4 + TOP-N входящих по каждому ETF."""
    excluded = _portfolio_exclude_keys(portfolio_holdings)
    collected: dict[str, WeightedHolding] = {}

    # 1) TOP-N мировых компаний для каждой отрасли из колонки «Отрасль» таблицы §4
    for sector in _sectors_from_table4(watchlist_sector_rows):
        picks = sector_leaders_as_holdings(sector, top_per_source)
        _take_top_holdings(collected, picks, top_per_source, excluded, sector=sector)

    # 2) TOP-N входящих бумаг для каждого ETF из колонок ISIN / «Название инструмента»
    sector_by_isin = _etf_sector_by_isin(watchlist_sector_rows)
    for row in watchlist_sector_rows:
        if row.isin == "—":
            continue
        isin = row.isin.upper()
        etf_data = holdings_map.get(isin)
        if not etf_data or not etf_data.holdings:
            continue
        _take_top_holdings(
            collected,
            etf_data.holdings,
            top_per_source,
            excluded,
            sector=_sector_cell(sector_by_isin.get(isin, "—")),
        )

    return sorted(collected.values(), key=lambda h: (-h.weight_pct, h.name.lower()))


def analyze_structure(
    analytics: PortfolioAnalytics,
    holdings_result: HoldingsFetchResult,
    *,
    portfolio_holdings_top: int = 20,
    watchlist_sectors_per_etf: int = 3,
    watchlist_holdings_per_source: int = 3,
) -> StructureAnalysis:
    portfolio_isins = {p.isin.upper() for p in analytics.positions if p.isin}
    holdings_map = holdings_result.holdings

    portfolio_holdings, sector_votes = _aggregate_portfolio_holdings(
        analytics.positions,
        holdings_map,
        holdings_result.quotes,
        top_limit=portfolio_holdings_top,
    )

    watchlist_sectors = _build_watchlist_sector_rows(
        analytics.interest_zone,
        portfolio_isins,
        holdings_map,
        sectors_per_etf=watchlist_sectors_per_etf,
    )

    from src.structure.sector_leaders_generator import (
        generate_sector_leaders_from_google,
        write_sector_leaders_yaml,
    )
    from src.structure.sector_leaders import set_runtime_sector_leaders

    generated_leaders = generate_sector_leaders_from_google(
        analytics,
        watchlist_sectors,
        holdings_map,
        sectors_per_etf=watchlist_sectors_per_etf,
        top_per_sector=watchlist_holdings_per_source,
    )
    write_sector_leaders_yaml(generated_leaders)
    set_runtime_sector_leaders(generated_leaders)
    _fill_portfolio_holding_sectors(
        portfolio_holdings,
        build_holding_sector_lookup(),
        sector_votes,
    )

    watchlist_tracking_holdings = _build_watchlist_tracking_holdings(
        analytics.interest_zone,
        portfolio_isins,
        holdings_map,
        portfolio_holdings,
        watchlist_sectors,
        top_per_source=watchlist_holdings_per_source,
        sectors_per_etf=watchlist_sectors_per_etf,
        sector_interests=analytics.sector_interests,
    )

    portfolio_etf_sectors = _collect_portfolio_etf_sectors(
        analytics.positions,
        holdings_map,
        sectors_per_etf=max(watchlist_sectors_per_etf, 5),
    )

    return StructureAnalysis(
        portfolio_holdings=portfolio_holdings,
        portfolio_etf_sectors=portfolio_etf_sectors,
        watchlist_sectors=watchlist_sectors,
        watchlist_tracking_holdings=watchlist_tracking_holdings,
        fetch_errors=dict(holdings_result.errors),
    )


async def load_structure_analysis(analytics: PortfolioAnalytics) -> StructureAnalysis:
    from src.config import load_yaml_config

    yaml_cfg = load_yaml_config()
    cfg = yaml_cfg.get("structure", {})
    portfolio_holdings_top = int(cfg.get("portfolio_holdings_top", 20))
    watchlist_per_etf = int(cfg.get("watchlist_sectors_per_etf", 3))
    watchlist_holdings_per = int(cfg.get("watchlist_holdings_per_source", 3))
    top_count = yaml_cfg.get("top_portfolio_count", 20)

    portfolio_isins = [p.isin for p in analytics.positions if p.isin]
    watchlist_isins = [
        i.isin
        for i in analytics.interest_zone
        if i.isin and i.isin.upper() not in {p.isin.upper() for p in analytics.positions if p.isin}
    ]
    isins = list(dict.fromkeys(portfolio_isins + watchlist_isins))

    holdings_result = await fetch_holdings_batch(isins)
    apply_monetary_weights(
        analytics,
        holdings_result.quotes,
        top_count=top_count,
    )
    return analyze_structure(
        analytics,
        holdings_result,
        portfolio_holdings_top=portfolio_holdings_top,
        watchlist_sectors_per_etf=watchlist_per_etf,
        watchlist_holdings_per_source=watchlist_holdings_per,
    )
