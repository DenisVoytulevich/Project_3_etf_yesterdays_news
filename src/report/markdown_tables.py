"""Утилиты разбора markdown-таблиц и очистки AI-секций."""

from __future__ import annotations

import logging
import re

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
