"""Утилиты разбора markdown-таблиц и очистки AI-секций."""

from __future__ import annotations

import logging
import re

from src.companies.context import TrackedCompany, build_company_lookup, company_identity_key
from src.pipeline.models import BRIEFING_SECTION_KEYS
from src.report.impact_scale import parse_impact_score
from src.structure.labels import canonical_sector_name, sector_matches

logger = logging.getLogger(__name__)


def clean_ai_section(text: str, key: str) -> str:
    cleaned = (text or "").strip()
    for prefix in (f"#{key}", f"## {key}"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].lstrip("\n")
            break
    cleaned = re.sub(
        rf"^#{{1,2}}\s*{re.escape(key)}\s*$",
        "",
        cleaned,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    for section_key in BRIEFING_SECTION_KEYS:
        cleaned = re.sub(
            rf"^#{{1,2}}\s*{re.escape(section_key)}\s*$",
            "",
            cleaned,
            flags=re.MULTILINE | re.IGNORECASE,
        )
    return cleaned.strip()


def parse_markdown_table_rows(text: str) -> tuple[list[str], list[list[str]]]:
    """Разобрать markdown-таблицу: префикс до заголовка и строки ячеек."""
    lines = text.splitlines()
    prefix: list[str] = []
    rows: list[list[str]] = []
    in_table = False

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            if not in_table:
                prefix.append(line)
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells:
            continue
        if not in_table:
            if cells[0].replace("-", "").replace(":", "").strip() == "":
                continue
            in_table = True
            rows.append(cells)
            continue
        if cells[0].replace("-", "").replace(":", "").strip() == "":
            continue
        rows.append(cells)

    return prefix, rows


def _rebuild_sector_table(prefix: list[str], header: list[str], data_rows: list[list[str]]) -> str:
    table_lines = ["| " + " | ".join(header) + " |"]
    if len(header) >= 4:
        table_lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for cells in data_rows:
        table_lines.append("| " + " | ".join(cells) + " |")
    parts = prefix + [""] + table_lines if prefix else table_lines
    return "\n".join(parts).strip()


def deduplicate_sector_ratings(
    sector_ratings: str,
    required_sectors: list[str],
) -> str:
    """Слить строки §2 с одной отраслью (RU/EN, синонимы) в одну строку."""
    prefix, rows = parse_markdown_table_rows(sector_ratings)
    if len(rows) < 2:
        return sector_ratings

    header = rows[0]
    data_rows = rows[1:]
    kept: list[list[str]] = []

    for cells in data_rows:
        if len(cells) < 4:
            kept.append(list(cells))
            continue
        sector = cells[1].strip()
        if sector.lower() == "отрасль":
            continue

        duplicate_index: int | None = None
        for index, existing in enumerate(kept):
            if len(existing) >= 2 and sector_matches(existing[1], sector):
                duplicate_index = index
                break

        if duplicate_index is None:
            kept.append(list(cells))
            continue

        existing = kept[duplicate_index]
        existing_impact = parse_impact_score(existing[2]) or 0
        new_impact = parse_impact_score(cells[2]) or 0
        winner = list(cells) if abs(new_impact) > abs(existing_impact) else list(existing)
        if abs(new_impact) == abs(existing_impact) and new_impact != 0:
            winner = list(cells)
        winner[1] = canonical_sector_name(existing[1], required_sectors)
        kept[duplicate_index] = winner

    for index, cells in enumerate(kept, start=1):
        cells[0] = str(index)
        if len(cells) >= 2:
            cells[1] = canonical_sector_name(cells[1], required_sectors)

    removed = len(data_rows) - len(kept)
    if removed > 0:
        logger.warning("§2: удалены дубли отраслей (%d строк)", removed)

    return _rebuild_sector_table(prefix, header, kept)


def _canonicalize_sector_table_names(
    sector_ratings: str,
    required_sectors: list[str],
) -> str:
    """Привести все названия в §2 к словарю портфеля."""
    prefix, rows = parse_markdown_table_rows(sector_ratings)
    if len(rows) < 2:
        return sector_ratings

    header = rows[0]
    data_rows: list[list[str]] = []
    for cells in rows[1:]:
        row = list(cells)
        if len(row) >= 2 and row[1].strip().lower() != "отрасль":
            row[1] = canonical_sector_name(row[1], required_sectors)
        data_rows.append(row)
    return _rebuild_sector_table(prefix, header, data_rows)


def finalize_sector_ratings(
    sector_ratings: str,
    required_sectors: list[str],
) -> str:
    """Дедупликация, канонизация имён и покрытие обязательных отраслей."""
    if not required_sectors:
        return sector_ratings or ""

    text = deduplicate_sector_ratings(sector_ratings or "", required_sectors)
    text = _canonicalize_sector_table_names(text, required_sectors)
    text = ensure_sector_ratings_coverage(text, required_sectors)
    text = deduplicate_sector_ratings(text, required_sectors)
    return _canonicalize_sector_table_names(text, required_sectors)


def ensure_sector_ratings_coverage(
    sector_ratings: str,
    required_sectors: list[str],
) -> str:
    """Добавить в §2 отрасли портфеля/watchlist, пропущенные моделью."""
    if not required_sectors:
        return sector_ratings

    prefix, rows = parse_markdown_table_rows(sector_ratings)
    if not rows:
        return sector_ratings

    header = rows[0]
    data_rows = rows[1:]
    existing_sectors = [
        cells[1]
        for cells in data_rows
        if len(cells) >= 4 and cells[1].lower() != "отрасль"
    ]

    missing = [
        sector
        for sector in required_sectors
        if not any(sector_matches(existing, sector) for existing in existing_sectors)
    ]
    if not missing:
        return sector_ratings

    next_no = 1
    for cells in data_rows:
        if len(cells) >= 1 and cells[0].isdigit():
            next_no = max(next_no, int(cells[0]) + 1)

    appended_rows: list[list[str]] = []
    for sector in missing:
        appended_rows.append(
            [str(next_no), sector, "0", "Нет явных драйверов в новостях вчера"]
        )
        next_no += 1

    logger.warning(
        "§2: добавлены пропущенные отрасли (%d): %s",
        len(missing),
        ", ".join(missing),
    )

    return _rebuild_sector_table(prefix, header, data_rows + appended_rows)


_PORTFOLIO_PLACEHOLDER = "значимых новостей по компаниям списка не выявлено"
_ZONE_RANK = {"портфель": 0, "наблюдение": 1, "watchlist": 1}


def _is_portfolio_placeholder_row(cells: list[str]) -> bool:
    return len(cells) >= 4 and _PORTFOLIO_PLACEHOLDER in cells[3].lower()


def _merge_portfolio_company_rows(
    existing: list[str],
    incoming: list[str],
) -> list[str]:
    """Слить две строки §3 по одной компании."""
    merged = list(existing)
    if len(incoming) < 5:
        return merged

    incoming_zone = incoming[1].strip().lower()
    existing_zone = merged[1].strip().lower()
    if _ZONE_RANK.get(incoming_zone, 9) < _ZONE_RANK.get(existing_zone, 9):
        merged[1] = incoming[1].strip()

    existing_impact = parse_impact_score(merged[4]) or 0
    incoming_impact = parse_impact_score(incoming[4]) or 0
    incoming_news = incoming[3].strip()
    existing_news = merged[3].strip()

    if abs(incoming_impact) > abs(existing_impact):
        merged[3] = incoming_news
        merged[4] = incoming[4].strip()
    elif (
        abs(incoming_impact) == abs(existing_impact)
        and incoming_impact < existing_impact
    ):
        merged[3] = incoming_news
        merged[4] = incoming[4].strip()
    elif incoming_news and incoming_news not in existing_news:
        merged[3] = f"{existing_news}; {incoming_news}" if existing_news else incoming_news

    return merged


def finalize_portfolio_companies_news(
    section: str,
    *,
    required_sectors: list[str],
    tracked_companies: list[TrackedCompany],
) -> str:
    """§3: одна строка на компанию, имена и отрасли из списка портфеля."""
    prefix, rows = parse_markdown_table_rows(section)
    if len(rows) < 2:
        return section

    header = rows[0]
    data_rows = rows[1:]
    if any(_is_portfolio_placeholder_row(cells) for cells in data_rows):
        return section

    lookup = build_company_lookup(tracked_companies)
    merged_rows: list[list[str]] = []
    index_by_key: dict[str, int] = {}

    for cells in data_rows:
        if len(cells) < 5 or cells[0].strip() in {"—", ""}:
            continue

        row = list(cells)
        key = company_identity_key(row[0])
        tracked = lookup.get(key)
        if tracked:
            row[0] = tracked.name
            row[1] = tracked.zone
            row[2] = canonical_sector_name(tracked.sector, required_sectors)
        else:
            row[2] = canonical_sector_name(row[2], required_sectors)

        if key not in index_by_key:
            index_by_key[key] = len(merged_rows)
            merged_rows.append(row)
            continue

        existing_index = index_by_key[key]
        merged_rows[existing_index] = _merge_portfolio_company_rows(
            merged_rows[existing_index],
            row,
        )

    removed = len(data_rows) - len(merged_rows)
    if removed > 0:
        logger.warning("§3: удалены дубли компаний (%d строк)", removed)

    return _rebuild_sector_table(prefix, header, merged_rows)
