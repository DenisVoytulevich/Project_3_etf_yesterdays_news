from __future__ import annotations

import re
from datetime import datetime

from src.data.models import PortfolioAnalytics
from src.structure.aggregation import StructureAnalysis

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

_IMPORTANCE_TO_STARS = {
    "высокая": 5,
    "высокое": 5,
    "high": 5,
    "средняя": 3,
    "среднее": 3,
    "medium": 3,
    "низкая": 2,
    "низкое": 2,
    "low": 2,
}

MACRO_TABLE_HEADER = (
    "| Дата | Событие | Важность | На что влияет | Потенциальное влияние |\n"
    "|------|---------|----------|---------------|----------------------|"
)

# Бенчмарк-индексы по валюте / типу события
_CURRENCY_INDEX = {
    "USD": "SPX",
    "EUR": "SX5E",
    "GBP": "FTSE",
    "JPY": "N225",
    "CNY": "CSI300",
    "CHF": "SMI",
    "CAD": "TSX",
    "AUD": "ASX200",
}

_EVENT_INDEX_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("non-farm", "SPX"),
    ("nonfarm", "SPX"),
    ("payroll", "SPX"),
    ("jolts", "SPX"),
    ("ism manufacturing", "XLI"),
    ("manufacturing pmi", "XLI"),
    ("services pmi", "XLY"),
    ("cpi", "SX5E"),
    ("hicp", "SX5E"),
    ("inflation", "SX5E"),
    ("fomc", "SPX"),
    ("fed ", "SPX"),
    ("ecb", "SX5E"),
    ("boe", "FTSE"),
    ("boj", "N225"),
    ("tankan", "N225"),
    ("gdp", "SX5E"),
    ("crude", "Brent"),
    ("oil", "Brent"),
    ("api weekly", "Brent"),
)


def format_date_russian(dt: datetime) -> str:
    return f"{dt.day} {_MONTHS_GENITIVE[dt.month - 1]}"


def importance_to_stars(importance: str | int) -> str:
    if isinstance(importance, int):
        count = max(1, min(5, importance))
    else:
        normalized = importance.strip().lower()
        if re.fullmatch(r"[★☆]+", normalized):
            count = normalized.count("★")
            return "★" * count + "☆" * (5 - count)
        digit = re.search(r"(\d)\s*/\s*5", normalized)
        if digit:
            count = int(digit.group(1))
        else:
            count = _IMPORTANCE_TO_STARS.get(normalized, 3)
    return "★" * count + "☆" * (5 - count)


def calendar_importance_to_stars(importance: str) -> str:
    mapping = {"высокая": 4, "средняя": 3, "низкая": 2}
    return importance_to_stars(mapping.get(importance, 3))


def stars_to_move_pct(stars: str) -> str:
    count = stars.count("★")
    return {5: "±2%", 4: "±1.5%", 3: "±1%", 2: "±0.5%", 1: "±0.3%"}.get(count, "±1%")


def stars_to_probability(stars: str) -> int:
    count = stars.count("★")
    return {5: 70, 4: 65, 3: 60, 2: 55, 1: 50}.get(count, 60)


def primary_index_for_event(event_name: str, currency: str = "") -> str:
    text = event_name.lower()
    for keyword, index in _EVENT_INDEX_KEYWORDS:
        if keyword in text:
            if keyword in ("cpi", "hicp", "inflation", "gdp", "ecb") and currency == "USD":
                return "SPX"
            if keyword in ("ism manufacturing", "manufacturing pmi") and currency == "EUR":
                return "SX5E"
            return index
    return _CURRENCY_INDEX.get(currency.upper(), "SPX")


_ETF_NAME_SUFFIXES = (
    " UCITS ETF USD (Acc)",
    " UCITS ETF USD",
    " UCITS ETF",
    " UCITS",
    " USD (Acc)",
    " USD",
)

_ETF_NAME_PREFIXES = ("iShares ", "VanEck ")

_COMPANY_NAME_SUFFIXES = (
    " Corporation",
    " Corp.",
    " Corp",
    " Ltd",
    " Ltd.",
    " NV",
    " SE",
    " SA",
    " Plc",
    " AG",
    " Inc.",
    " Inc",
)

# Тикеры → читаемые названия для колонки «На что влияет» (не для «Потенциальное влияние»)
_STATIC_AFFECTS_NAMES: dict[str, str] = {
    "SPX": "S&P 500",
    "SX5E": "EURO STOXX 50",
    "SXRT": "EURO STOXX 50",
    "SXR8": "S&P 500",
    "QDVE": "S&P 500 IT",
    "NDX": "Nasdaq",
    "N225": "Nikkei 225",
    "WIG20": "WIG20",
    "XLI": "промышленность США",
    "XLB": "материалы США",
    "XLY": "потребительский сектор США",
    "UKX": "FTSE 100",
    "FTSE": "FTSE 100",
    "CSI300": "CSI 300",
    "TSX": "S&P/TSX",
    "ASX200": "ASX 200",
    "SMI": "SMI",
    "BRENT": "нефть Brent",
    "GOLD": "золото",
    "NVDA": "NVIDIA",
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "MU": "Micron",
    "AMD": "AMD",
    "PLTR": "Palantir",
}

_ISIN_RE = re.compile(r"IE00[A-Z0-9]{8,}", re.IGNORECASE)


def short_etf_name(full_name: str) -> str:
    name = full_name.strip()
    for suffix in _ETF_NAME_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    for prefix in _ETF_NAME_PREFIXES:
        if name.startswith(prefix):
            name = name[len(prefix) :].strip()
    return name


def short_company_name(full_name: str) -> str:
    name = full_name.strip()
    for suffix in _COMPANY_NAME_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    return name


def build_macro_affects_name_map(
    analytics: PortfolioAnalytics | None = None,
    structure: StructureAnalysis | None = None,
) -> dict[str, str]:
    """Тикер/ISIN → короткое название для колонки «На что влияет»."""
    mapping = dict(_STATIC_AFFECTS_NAMES)

    if analytics:
        for position in analytics.positions:
            label = short_etf_name(position.name)
            if position.ticker:
                mapping[position.ticker.upper()] = label
            if position.isin:
                mapping[position.isin.upper()] = label

    if structure:
        for holding in (
            *structure.portfolio_holdings,
            *structure.watchlist_tracking_holdings,
        ):
            if holding.symbol and holding.symbol != "—":
                mapping[holding.symbol.upper()] = short_company_name(holding.name)

    return mapping


def normalize_affects_cell(text: str, name_map: dict[str, str] | None = None) -> str:
    if not text or text.strip() in ("—", "-"):
        return text

    result = text
    if name_map:
        for isin in _ISIN_RE.findall(result):
            label = name_map.get(isin.upper())
            if label:
                result = result.replace(isin, label)

        # Защищаем уже записанные названия от частичной замены тикеров (GE → GE Aerospace)
        protected: dict[str, str] = {}
        for i, label in enumerate(
            sorted({v for v in name_map.values() if " " in v}, key=len, reverse=True)
        ):
            if label in result:
                token = f"__AFFECTS_{i}__"
                protected[token] = label
                result = result.replace(label, token)

        for ticker, label in sorted(name_map.items(), key=lambda item: -len(item[0])):
            if len(ticker) < 2:
                continue
            result = re.sub(
                rf"\b{re.escape(ticker)}\b",
                label,
                result,
                flags=re.IGNORECASE,
            )

        for token, label in protected.items():
            result = result.replace(token, label)

    result = re.sub(r"FTSE 100\s+100", "FTSE 100", result)
    result = re.sub(r"(GE Aerospace)\s+\1", r"\1", result)
    result = re.sub(r",\s*,", ",", result)
    result = re.sub(r"\s+", " ", result)

    parts: list[str] = []
    seen: set[str] = set()
    for part in result.split(","):
        part = part.strip()
        key = part.lower()
        if part and key not in seen:
            seen.add(key)
            parts.append(part)
    return ", ".join(parts)


def format_index_impact(event_name: str, stars: str, currency: str = "") -> str:
    """Колонка «Потенциальное влияние»: главный индекс + оценка движения + вероятность."""
    index = primary_index_for_event(event_name, currency)
    move = stars_to_move_pct(stars)
    prob = stars_to_probability(stars)
    return f"{index} {move}, вер. {prob}%"


def ensure_index_impact(impact: str, event_name: str, stars: str, currency: str = "") -> str:
    text = impact.strip()
    if not text or text in {"—", "-"}:
        return text
    if "вер." in text.lower() and "%" in text:
        return text
    if "±" in text and "%" in text:
        prob = stars_to_probability(stars)
        return f"{text}, вер. {prob}%"
    return format_index_impact(event_name, stars, currency)


def extract_macro_table(text: str) -> str:
    """Оставляет только markdown-таблицу из ответа AI."""
    lines = text.strip().splitlines()
    table_lines: list[str] = []
    in_table = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and "Дата" in stripped and "Событие" in stripped:
            in_table = True
            table_lines = [stripped]
            continue
        if in_table:
            if stripped.startswith("|"):
                table_lines.append(stripped)
            elif table_lines:
                break
    if len(table_lines) >= 2:
        return "\n".join(table_lines)
    return text.strip()


def normalize_macro_table_rows(
    table: str,
    name_map: dict[str, str] | None = None,
) -> str:
    """Приводит «Важность» к ★★★☆☆, «На что влияет» — к названиям без тикеров."""
    lines = table.splitlines()
    if len(lines) < 2:
        return table

    result = [lines[0], lines[1]]
    for line in lines[2:]:
        if not line.strip().startswith("|"):
            result.append(line)
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) >= 3:
            cells[2] = importance_to_stars(cells[2])
        if len(cells) >= 4 and name_map:
            cells[3] = normalize_affects_cell(cells[3], name_map)
        if len(cells) >= 5:
            cells[4] = ensure_index_impact(cells[4], cells[1], cells[2])
        result.append("| " + " | ".join(cells) + " |")
    return "\n".join(result)


def format_macro_section(
    text: str,
    *,
    analytics: PortfolioAnalytics | None = None,
    structure: StructureAnalysis | None = None,
) -> str:
    """Финальное форматирование §5.1: таблица, звёзды, названия вместо тикеров."""
    table = extract_macro_table(text)
    if not table:
        return text.strip()
    name_map = build_macro_affects_name_map(analytics, structure)
    return normalize_macro_table_rows(table, name_map)
