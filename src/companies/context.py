"""Общий список компаний из портфеля (§3.1) и watchlist (§4.1)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.structure.aggregation import StructureAnalysis, WeightedHolding

_ISIN_SYMBOL_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9,11}$")

_COMPANY_NAME_SUFFIXES = (
    " Corporation",
    " Corp.",
    " Corp",
    " Co Ltd",
    " Co., Ltd.",
    " Co.",
    " Ltd.",
    " Ltd",
    " NV",
    " SE",
    " SA",
    " Plc",
    " AG",
    " Inc.",
    " Inc",
    " O.N.",
    " SpA",
    " ADR",
    " VNA",
)


@dataclass(slots=True)
class TrackedCompany:
    name: str
    symbol: str
    sector: str
    zone: str
    weight_pct: float | None = None


@dataclass(slots=True)
class CompanySearchTerm:
    query: str
    company: TrackedCompany


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


def _is_isin_like(symbol: str) -> bool:
    return bool(_ISIN_SYMBOL_RE.match(symbol.strip().upper()))


def _is_valid_ticker_for_newsapi(symbol: str) -> bool:
    value = symbol.strip().upper()
    if not value or value == "—":
        return False
    if _is_isin_like(value):
        return False
    if value.isdigit():
        return False
    if len(value) > 12:
        return False
    return True


def short_company_name_for_query(name: str) -> str:
    short = name.strip()
    short = re.sub(r"\s+Class\s+[A-Z].*$", "", short, flags=re.IGNORECASE)
    for suffix in _COMPANY_NAME_SUFFIXES:
        if short.endswith(suffix):
            short = short[: -len(suffix)].strip()
            break
    return short.strip()


def company_search_query_term(company: TrackedCompany) -> str | None:
    """Поисковый термин для NewsAPI: тикер или короткое название."""
    if _is_valid_ticker_for_newsapi(company.symbol):
        return company.symbol.strip().upper()

    short = short_company_name_for_query(company.name)
    if len(short) >= 3:
        return short
    return None


def build_company_search_terms(
    companies: list[TrackedCompany],
) -> list[CompanySearchTerm]:
    """Уникальные поисковые термины для батчевого скрининга (портфель → watchlist)."""
    grouped: dict[str, CompanySearchTerm] = {}
    order: list[str] = []

    for company in companies:
        term = company_search_query_term(company)
        if not term:
            continue
        norm = _normalize_company_name(short_company_name_for_query(company.name)) or term.lower()
        if norm not in grouped:
            order.append(norm)
            grouped[norm] = CompanySearchTerm(query=term, company=company)
            continue

        existing = grouped[norm]
        existing_ticker = _is_valid_ticker_for_newsapi(existing.company.symbol)
        current_ticker = _is_valid_ticker_for_newsapi(company.symbol)
        if current_ticker and not existing_ticker:
            grouped[norm] = CompanySearchTerm(query=term, company=company)
        elif current_ticker == existing_ticker and len(term) < len(existing.query):
            grouped[norm] = CompanySearchTerm(query=term, company=company)

    return [grouped[key] for key in order]


def _holding_key(symbol: str, name: str) -> str:
    if symbol and symbol.strip() and symbol != "—":
        return symbol.strip().upper()
    return name.strip().lower()


def _limit_sectors_display(sector: str, max_count: int = 2) -> str:
    if not sector or sector.strip() == "—":
        return "—"
    parts = [part.strip() for part in sector.split(",") if part.strip()]
    if len(parts) <= max_count:
        return ", ".join(parts)
    return ", ".join(parts[:max_count])


def _to_tracked(
    holding: WeightedHolding,
    *,
    zone: str,
) -> TrackedCompany:
    symbol = holding.symbol if holding.symbol and holding.symbol != "—" else "—"
    return TrackedCompany(
        name=holding.name,
        symbol=symbol,
        sector=_limit_sectors_display(holding.sector),
        zone=zone,
        weight_pct=holding.weight_pct if zone == "Портфель" else None,
    )


def build_unified_company_list(
    structure: StructureAnalysis | None,
) -> list[TrackedCompany]:
    """
    Объединённый список бумаг из TOP портфеля и watchlist без дублей.

  Портфельные позиции идут первыми (по убыванию доли); watchlist — после,
  исключая компании, уже попавшие в портфель.
    """
    if not structure:
        return []

    result: list[TrackedCompany] = []
    seen_keys: set[str] = set()
    seen_names: set[str] = set()

    portfolio = sorted(
        structure.portfolio_holdings,
        key=lambda item: (-item.weight_pct, item.name.lower()),
    )
    for holding in portfolio:
        key = _holding_key(holding.symbol, holding.name)
        normalized = _normalize_company_name(holding.name)
        if key in seen_keys or (normalized and normalized in seen_names):
            continue
        seen_keys.add(key)
        if normalized:
            seen_names.add(normalized)
        result.append(_to_tracked(holding, zone="Портфель"))

    for holding in structure.watchlist_tracking_holdings:
        key = _holding_key(holding.symbol, holding.name)
        normalized = _normalize_company_name(holding.name)
        if key in seen_keys or (normalized and normalized in seen_names):
            continue
        seen_keys.add(key)
        if normalized:
            seen_names.add(normalized)
        result.append(_to_tracked(holding, zone="Наблюдение"))

    return result


def format_companies_table(companies: list[TrackedCompany]) -> str:
    if not companies:
        return "_Список компаний пуст — проверьте Portfel, Watchlist и загрузку состава ETF_"
    lines = [
        "| # | Компания | Тикер | Зона | Отрасль | Доля |",
        "|---|----------|-------|------|---------|:--:|",
    ]
    for index, company in enumerate(companies, 1):
        weight = f"{company.weight_pct:.2f}%" if company.weight_pct is not None else "—"
        lines.append(
            f"| {index} | {company.name} | {company.symbol} | {company.zone} | "
            f"{company.sector} | {weight} |"
        )
    return "\n".join(lines)


def format_companies_for_prompt(
    structure: StructureAnalysis | None,
    companies: list[TrackedCompany] | None = None,
) -> str:
    """Контекст списка компаний для промпта AI (§3)."""
    items = companies if companies is not None else build_unified_company_list(structure)
    lines = [
        "**Компании для анализа (портфель + watchlist, без дублей):**",
        f"Всего: {len(items)}",
        "",
        format_companies_table(items),
    ]
    if structure and structure.fetch_errors:
        lines.extend(
            [
                "",
                "_Предупреждение: не для всех ETF удалось загрузить состав._",
            ]
        )
    return "\n".join(lines)
