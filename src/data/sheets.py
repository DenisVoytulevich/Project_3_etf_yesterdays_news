import logging
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from src.config import Settings, load_yaml_config
from src.data.models import (
    EtfPosition,
    InterestZoneItem,
    PortfolioAnalytics,
    SectorInterest,
    SectorShare,
    RegionShare,
    WatchItem,
)

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def _get_client(credentials_path: str) -> gspread.Client:
    path = Path(credentials_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Файл credentials не найден: {path}. "
            "Создайте Service Account в Google Cloud и положите JSON в credentials/"
        )
    creds = Credentials.from_service_account_file(str(path), scopes=SCOPES)
    return gspread.authorize(creds)


def _col_index(headers: list[str], col_name: str, prefix: bool = False) -> int | None:
    if prefix:
        col_lower = col_name.lower()
        for i, h in enumerate(headers):
            if str(h).strip().lower().startswith(col_lower):
                return i
        return None
    try:
        return headers.index(col_name)
    except ValueError:
        return None


def _find_header_row(rows: list[list[str]], marker: str) -> int | None:
    marker_lower = marker.lower()
    for i, row in enumerate(rows):
        if any(marker_lower in str(cell).lower() for cell in row):
            return i
    return None


def _normalize_ticker(raw: str) -> str:
    return raw.split(":")[0].strip().upper()


def _is_section_row(row: list, group_col: int) -> bool:
    if group_col >= len(row):
        return False
    label = str(row[group_col]).strip()
    if not label:
        return False
    rest = "".join(str(c).strip() for i, c in enumerate(row) if i != group_col)
    return not rest


def _cell(row: list, idx: int | None, default: str = "") -> str:
    if idx is None or idx >= len(row):
        return default
    return str(row[idx]).strip()


def _parse_float(value: str) -> float:
    if not value:
        return 0.0
    cleaned = value.replace(" ", "").replace(",", ".")
    if cleaned in ("-", "—", ""):
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _has_portfolio_quantity(raw: str) -> bool:
    """Бумага в портфеле только при наличии количества (QTY > 0)."""
    value = str(raw).strip()
    if not value or value in ("-", "—"):
        return False
    return _parse_float(value) > 0


def _open_spreadsheet(client: gspread.Client, sheet_id: str):
    return client.open_by_key(sheet_id)


def _read_sheet_rows(
    spreadsheet: gspread.Spreadsheet, sheet_name: str
) -> list[list[str]]:
    worksheet = spreadsheet.worksheet(sheet_name)
    return worksheet.get_all_values()


def _read_sheet_rows_optional(
    spreadsheet: gspread.Spreadsheet, sheet_name: str | None
) -> list[list[str]]:
    if not sheet_name or not str(sheet_name).strip():
        return []
    try:
        return _read_sheet_rows(spreadsheet, sheet_name.strip())
    except gspread.exceptions.WorksheetNotFound:
        logger.warning("Лист «%s» не найден — пропускаем", sheet_name)
        return []


def _normalize_decision(value: str) -> str:
    """Нормализация для сравнения (в т.ч. латинская c в «рассматриваю»)."""
    return value.strip().lower().replace("c", "с")


def _is_excluded_decision(value: str, excluded: list[str]) -> bool:
    norm = _normalize_decision(value)
    for phrase in excluded:
        if _normalize_decision(phrase) in norm:
            return True
    return False


def _parse_portfel_table(
    rows: list[list[str]], columns: dict[str, str], sheet_cfg: dict | None = None
) -> tuple[list[EtfPosition], list[InterestZoneItem]]:
    """Портфель (QTY > 0) и зона интереса из Portfel (QTY пусто / 0 / «-»)."""
    sheet_cfg = sheet_cfg or {}
    marker = sheet_cfg.get("header_marker", "Ticker")
    group_col = sheet_cfg.get("group_column", 0)

    header_idx = _find_header_row(rows, marker)
    if header_idx is None:
        logger.warning("Строка заголовков с «%s» не найдена", marker)
        return [], []

    headers = rows[header_idx]
    idx = {
        k: _col_index(headers, v, prefix=(k == "volume"))
        for k, v in columns.items()
    }

    positions: list[EtfPosition] = []
    zero_qty: list[InterestZoneItem] = []
    current_group = ""

    for row in rows[header_idx + 1 :]:
        if not any(str(c).strip() for c in row):
            continue

        if _is_section_row(row, group_col):
            current_group = str(row[group_col]).strip()
            continue

        ticker_raw = _cell(row, idx.get("ticker"))
        if not ticker_raw or ticker_raw in ("-", "—"):
            continue

        isin = _cell(row, idx.get("isin"))
        name = _cell(row, idx.get("name"))
        if not name and not isin:
            continue

        ticker = _normalize_ticker(ticker_raw)
        qty_raw = _cell(row, idx.get("volume"))

        if _has_portfolio_quantity(qty_raw):
            volume = _parse_float(qty_raw)
            positions.append(
                EtfPosition(
                    ticker=ticker,
                    name=name,
                    volume=volume,
                    sector="Прочее",
                    region="Прочее",
                    isin=isin,
                    group=current_group,
                )
            )
        else:
            zero_qty.append(
                InterestZoneItem(
                    sector="—",
                    isin=isin,
                    name=name,
                    ticker=ticker,
                )
            )

    return positions, zero_qty


def _load_portfolio(
    rows: list[list[str]], columns: dict[str, str], sheet_cfg: dict | None = None
) -> list[EtfPosition]:
    positions, _ = _parse_portfel_table(rows, columns, sheet_cfg)
    return positions


def _load_portfel_zero_interest(
    rows: list[list[str]], columns: dict[str, str], sheet_cfg: dict | None = None
) -> list[InterestZoneItem]:
    _, zero_qty = _parse_portfel_table(rows, columns, sheet_cfg)
    return zero_qty


def _load_watchlist_interest(
    rows: list[list[str]],
    columns: dict[str, str],
    sheet_cfg: dict | None = None,
    exclude_decisions: list[str] | None = None,
) -> list[InterestZoneItem]:
    sheet_cfg = sheet_cfg or {}
    exclude_decisions = exclude_decisions or []
    marker = sheet_cfg.get("header_marker", "ISIN")

    header_idx = _find_header_row(rows, marker)
    if header_idx is None:
        logger.warning("Строка заголовков Watchlist с «%s» не найдена", marker)
        return []

    headers = rows[header_idx]
    idx = {k: _col_index(headers, v) for k, v in columns.items()}

    items: list[InterestZoneItem] = []
    for row in rows[header_idx + 1 :]:
        if not any(str(c).strip() for c in row):
            continue

        decision = _cell(row, idx.get("decision"))
        if decision and _is_excluded_decision(decision, exclude_decisions):
            continue

        isin = _cell(row, idx.get("isin"))
        name = _cell(row, idx.get("name"))

        if not isin and not name:
            continue

        if not isin:
            items.append(InterestZoneItem(sector=name, isin="", name=""))
            continue

        items.append(
            InterestZoneItem(
                sector="—",
                isin=isin,
                name=name,
            )
        )

    return items


def _merge_interest_zone(
    from_portfel: list[InterestZoneItem],
    from_watchlist: list[InterestZoneItem],
) -> list[InterestZoneItem]:
    """Объединение зоны интереса; дедупликация по ISIN."""
    by_isin: dict[str, InterestZoneItem] = {}
    sector_rows: list[InterestZoneItem] = []
    seen_sectors: set[str] = set()

    for item in from_portfel:
        if not item.isin:
            continue
        key = item.isin.upper()
        by_isin[key] = item

    for item in from_watchlist:
        if not item.isin:
            sector_key = item.sector.strip().lower()
            if sector_key and sector_key not in seen_sectors:
                seen_sectors.add(sector_key)
                sector_rows.append(item)
            continue

        key = item.isin.upper()
        if key in by_isin:
            existing = by_isin[key]
            by_isin[key] = InterestZoneItem(
                sector=existing.sector if existing.sector != "—" else item.sector,
                isin=key,
                name=item.name or existing.name,
                ticker=existing.ticker or item.ticker,
            )
        else:
            by_isin[key] = InterestZoneItem(
                sector=item.sector,
                isin=key,
                name=item.name,
                ticker=item.ticker,
            )

    instruments = sorted(
        by_isin.values(),
        key=lambda x: (x.sector, x.name, x.isin),
    )
    sectors = sorted(sector_rows, key=lambda x: x.sector)
    return sectors + instruments


def _build_isin_ticker_map(
    portfel_rows: list[list[str]], columns: dict, sheet_cfg: dict
) -> dict[str, str]:
    positions, zero_qty = _parse_portfel_table(portfel_rows, columns, sheet_cfg)
    mapping: dict[str, str] = {}
    for pos in positions:
        if pos.isin and pos.ticker:
            mapping[pos.isin.upper()] = pos.ticker
    for item in zero_qty:
        if item.isin and item.ticker:
            mapping[item.isin.upper()] = item.ticker
    return mapping


def _enrich_interest_tickers(
    items: list[InterestZoneItem], portfel_rows: list[list[str]], columns: dict, sheet_cfg: dict
) -> None:
    """Подставить тикер по ISIN из листа Portfel."""
    isin_to_ticker = _build_isin_ticker_map(portfel_rows, columns, sheet_cfg)
    for item in items:
        if not item.ticker and item.isin:
            item.ticker = isin_to_ticker.get(item.isin.upper(), "")


def _legacy_watch_items(interest_zone: list[InterestZoneItem]) -> list[WatchItem]:
    """Совместимость для новостного агрегатора."""
    items = []
    for zone in interest_zone:
        if not zone.isin:
            continue
        items.append(
            WatchItem(
                ticker=zone.ticker or zone.isin,
                name=zone.name,
                sector=zone.sector if zone.sector != "—" else "Прочее",
                region="Прочее",
            )
        )
    return items


def _load_watchlist(rows: list[list[str]], columns: dict[str, str]) -> list[WatchItem]:
    if len(rows) < 2:
        return []

    headers = rows[0]
    idx = {k: _col_index(headers, v) for k, v in columns.items()}

    items = []
    for row in rows[1:]:
        ticker = _cell(row, idx.get("ticker"))
        if not ticker:
            continue
        items.append(
            WatchItem(
                ticker=ticker.upper(),
                name=_cell(row, idx.get("name")),
                sector=_cell(row, idx.get("sector"), "Прочее"),
                region=_cell(row, idx.get("region"), "Прочее"),
                note=_cell(row, idx.get("note")),
            )
        )
    return items


def _load_sectors(rows: list[list[str]], columns: dict[str, str]) -> list[SectorInterest]:
    if len(rows) < 2:
        return []

    headers = rows[0]
    idx = {k: _col_index(headers, v) for k, v in columns.items()}

    sectors = []
    for row in rows[1:]:
        sector = _cell(row, idx.get("sector"))
        if not sector:
            continue
        priority = int(_parse_float(_cell(row, idx.get("priority"))) or 1)
        sectors.append(SectorInterest(sector=sector, priority=priority))
    return sectors


def _compute_weights(positions: list[EtfPosition]) -> None:
    total = sum(p.volume for p in positions)
    if total <= 0:
        return
    for p in positions:
        if p.weight <= 0:
            p.weight = (p.volume / total) * 100


def _aggregate_sectors(positions: list[EtfPosition]) -> list[SectorShare]:
    totals: dict[str, float] = {}
    for p in positions:
        totals[p.sector] = totals.get(p.sector, 0) + p.volume

    total = sum(totals.values()) or 1
    shares = [
        SectorShare(sector=s, volume=v, share_pct=(v / total) * 100)
        for s, v in totals.items()
    ]
    return sorted(shares, key=lambda x: x.share_pct, reverse=True)


def _aggregate_regions(positions: list[EtfPosition]) -> list[RegionShare]:
    totals: dict[str, float] = {}
    for p in positions:
        totals[p.region] = totals.get(p.region, 0) + p.volume

    total = sum(totals.values()) or 1
    shares = [
        RegionShare(region=r, volume=v, share_pct=(v / total) * 100)
        for r, v in totals.items()
    ]
    return sorted(shares, key=lambda x: x.share_pct, reverse=True)


def load_portfolio_analytics(settings: Settings) -> PortfolioAnalytics:
    yaml_cfg = load_yaml_config()
    sheets_cfg = yaml_cfg["sheets"]
    top_count = yaml_cfg.get("top_portfolio_count", 20)

    client = _get_client(settings.google_credentials_path)
    spreadsheet = _open_spreadsheet(client, settings.google_sheets_id)

    portfolio_sheet = sheets_cfg.get("portfolio", "").strip()
    if not portfolio_sheet:
        raise ValueError("В settings.yaml не задан лист portfolio (портфель)")

    portfolio_rows = _read_sheet_rows(spreadsheet, portfolio_sheet)
    watchlist_rows = _read_sheet_rows_optional(
        spreadsheet, sheets_cfg.get("watchlist")
    )
    sectors_rows = _read_sheet_rows_optional(spreadsheet, sheets_cfg.get("sectors"))

    positions = _load_portfolio(
        portfolio_rows,
        yaml_cfg["portfolio_columns"],
        yaml_cfg.get("portfolio_sheet", {}),
    )
    portfel_zero = _load_portfel_zero_interest(
        portfolio_rows,
        yaml_cfg["portfolio_columns"],
        yaml_cfg.get("portfolio_sheet", {}),
    )
    watchlist_interest = _load_watchlist_interest(
        watchlist_rows,
        yaml_cfg["watchlist_columns"],
        yaml_cfg.get("watchlist_sheet", {}),
        yaml_cfg.get("watchlist_exclude_decisions", []),
    )
    interest_zone = _merge_interest_zone(portfel_zero, watchlist_interest)
    _enrich_interest_tickers(
        interest_zone,
        portfolio_rows,
        yaml_cfg["portfolio_columns"],
        yaml_cfg.get("portfolio_sheet", {}),
    )
    watchlist = _legacy_watch_items(interest_zone)
    sector_interests = _load_sectors(sectors_rows, yaml_cfg["sectors_columns"])

    _compute_weights(positions)

    top_holdings = sorted(positions, key=lambda p: p.volume, reverse=True)[:top_count]
    total_volume = sum(p.volume for p in positions)

    analytics = PortfolioAnalytics(
        positions=positions,
        interest_zone=interest_zone,
        watchlist=watchlist,
        sector_interests=sector_interests,
        top_holdings=top_holdings,
        sector_shares=_aggregate_sectors(positions),
        region_shares=_aggregate_regions(positions),
        total_volume=total_volume,
    )

    logger.info(
        "Загружено: %d позиций, %d в зоне интереса, %d отраслей интереса",
        len(positions),
        len(interest_zone),
        len(sector_interests),
    )
    return analytics
