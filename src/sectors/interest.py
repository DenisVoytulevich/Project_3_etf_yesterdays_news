"""Отрасли интереса из Portfel и Watchlist для обязательного скрининга новостей."""

from __future__ import annotations

from src.data.models import PortfolioAnalytics
from src.structure.aggregation import StructureAnalysis
from src.structure.labels import infer_etf_theme_sectors, sector_label


def _add_sector(sectors: list[str], seen: set[str], raw: str) -> None:
    """Добавить отрасль; составные значения «A, B, C» разбиваются по запятой."""
    for part in (raw or "").split(","):
        name = sector_label(part.strip())
        if not name or name == "—":
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        sectors.append(name)


def _add_portfolio_position_themes(
    analytics: PortfolioAnalytics,
    sectors: list[str],
    seen: set[str],
) -> None:
    """Тематические отрасли ETF портфеля по названию (Defense → Оборона)."""
    for pos in analytics.positions:
        for theme in infer_etf_theme_sectors(pos.name, pos.ticker):
            _add_sector(sectors, seen, theme)


def collect_portfolio_sectors(
    analytics: PortfolioAnalytics,
    structure: StructureAnalysis | None = None,
) -> list[str]:
    """Отрасли портфеля: тематика ETF + TOP-секторы + отрасли конечных бумаг."""
    sectors: list[str] = []
    seen: set[str] = set()

    _add_portfolio_position_themes(analytics, sectors, seen)

    if not structure:
        return sectors

    for sector in structure.portfolio_etf_sectors:
        _add_sector(sectors, seen, sector)

    for holding in structure.portfolio_holdings:
        _add_sector(sectors, seen, holding.sector)

    return sectors


def collect_screening_sectors(
    analytics: PortfolioAnalytics,
    structure: StructureAnalysis | None = None,
) -> list[str]:
    """
    Все отрасли, которые обязаны участвовать в скрининге новостей.

    Источники (как в Project_3_etf_news):
    - лист sectors (если настроен);
    - строки Watchlist без ISIN (чистые отрасли);
    - топ-отрасли ETF из Portfel (QTY=0) и Watchlist (через structure.watchlist_sectors);
    - тематика и TOP-секторы ETF портфеля (QTY > 0);
    - отрасли конечных бумаг портфеля (structure.portfolio_holdings).
    """
    sectors: list[str] = []
    seen: set[str] = set()

    for item in analytics.sector_interests:
        _add_sector(sectors, seen, item.sector)

    for sector in analytics.interest_sectors:
        _add_sector(sectors, seen, sector)

    _add_portfolio_position_themes(analytics, sectors, seen)

    if structure:
        for row in structure.watchlist_sectors:
            _add_sector(sectors, seen, row.sector)

        for sector in structure.portfolio_etf_sectors:
            _add_sector(sectors, seen, sector)

        for holding in structure.portfolio_holdings:
            _add_sector(sectors, seen, holding.sector)

        for holding in structure.watchlist_tracking_holdings:
            _add_sector(sectors, seen, holding.sector)

    return sectors


def format_interest_sectors_for_prompt(
    analytics: PortfolioAnalytics,
    structure: StructureAnalysis | None,
    screening_sectors: list[str] | None = None,
) -> str:
    """Контекст отраслей для промпта и логов."""
    sectors = screening_sectors or collect_screening_sectors(analytics, structure)
    portfolio_sectors = collect_portfolio_sectors(analytics, structure)
    portfolio_keys = {s.lower() for s in portfolio_sectors}
    watchlist_sectors = [s for s in sectors if s.lower() not in portfolio_keys]

    lines = [
        f"**Отраслей в обязательном скрининге:** {len(sectors)}",
        "",
    ]
    if not sectors:
        lines.append(
            "— не удалось определить отрасли; проверьте листы Portfel и Watchlist"
        )
        return "\n".join(lines)

    if portfolio_sectors:
        lines.append(
            "**Отрасли портфеля (обязательны в §2 — каждая отдельной строкой):**"
        )
        for sector in portfolio_sectors:
            lines.append(f"- {sector}")
        lines.append("")

    if watchlist_sectors:
        lines.append("**Отрасли watchlist / зоны интереса:**")
        for sector in watchlist_sectors:
            lines.append(f"- {sector}")
        lines.append("")

    portfel_n = len([i for i in analytics.interest_zone if i.isin])
    sector_rows = len([i for i in analytics.interest_zone if not i.isin])
    lines.extend(
        [
            f"_Портфель: {len(analytics.positions)} ETF · зона интереса: "
            f"{portfel_n} инструментов, {sector_rows} строк-отраслей_",
        ]
    )
    if structure:
        lines.append(
            f"_Структура: {len(structure.portfolio_etf_sectors)} отраслей ETF портфеля, "
            f"{len(structure.portfolio_holdings)} бумаг портфеля, "
            f"{len(structure.watchlist_sectors)} строк Watchlist_"
        )
    return "\n".join(lines)
