"""Версия агента сервиса Daily Briefing.

Дата задаётся в _release_date.txt в корне проекта при обновлении логики сервиса
или через DAILY_BRIEFING_RELEASE_DATE.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path


def _parse_release_date(raw: str) -> date:
    raw = raw.strip()
    if "." in raw:
        day_s, month_s, year_s = raw.split(".", 2)
        return date(int(year_s), int(month_s), int(day_s))
    if "-" in raw:
        parts = raw.split("-")
        if len(parts[0]) == 4:
            year_s, month_s, day_s = parts
            return date(int(year_s), int(month_s), int(day_s))
        day_s, month_s, year_s = parts
        return date(int(year_s), int(month_s), int(day_s))
    raise ValueError(f"DAILY_BRIEFING_RELEASE_DATE: неверный формат: {raw!r}")


_RELEASE_DATE_FILE = Path(__file__).resolve().parents[1] / "_release_date.txt"


def get_agent_release_date() -> date | None:
    raw = os.environ.get("DAILY_BRIEFING_RELEASE_DATE", "").strip()
    if raw:
        return _parse_release_date(raw)
    if not _RELEASE_DATE_FILE.is_file():
        return None
    raw = _RELEASE_DATE_FILE.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    return _parse_release_date(raw)


def agent_version() -> str:
    release = get_agent_release_date()
    if release is None:
        return "v-dev"
    return f"v{release:%d.%m.%Y}"
