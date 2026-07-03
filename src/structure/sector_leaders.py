from __future__ import annotations

import logging
from functools import lru_cache

import yaml

from src.structure.labels import sector_aliases
from src.structure.models import EtfHolding
from src.structure.sector_leaders_generator import generated_leaders_path

logger = logging.getLogger(__name__)

_runtime_leaders: dict[str, list[dict[str, str]]] | None = None
_CANDIDATE_POOL_MULTIPLIER = 8


@lru_cache(maxsize=1)
def _load_yaml_leaders_map() -> dict[str, list[dict[str, str]]]:
    path = generated_leaders_path()
    if not path.is_file():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    leaders = data.get("leaders") or {}
    if not isinstance(leaders, dict):
        return {}
    return leaders


def set_runtime_sector_leaders(leaders: dict[str, list[dict[str, str]]]) -> None:
    global _runtime_leaders
    _runtime_leaders = leaders
    _load_yaml_leaders_map.cache_clear()
    build_holding_sector_lookup.cache_clear()


def clear_runtime_sector_leaders() -> None:
    global _runtime_leaders
    _runtime_leaders = None
    build_holding_sector_lookup.cache_clear()


def _active_leaders_map() -> dict[str, list[dict[str, str]]]:
    """Автогенерация из Portfel + Watchlist + состав ETF."""
    leaders = _runtime_leaders if _runtime_leaders is not None else _load_yaml_leaders_map()
    if not leaders:
        logger.warning(
            "Справочник лидеров пуст — проверьте Portfel/Watchlist и загрузку состава ETF"
        )
    return leaders


def _resolve_sector_key(sector: str, leaders: dict[str, list]) -> str | None:
    if sector in leaders:
        return sector

    interest_aliases = set(sector_aliases(sector))
    for key, items in leaders.items():
        if not items:
            continue
        key_aliases = set(sector_aliases(key))
        if interest_aliases & key_aliases:
            return key
        for interest in interest_aliases:
            for alias in key_aliases:
                if interest in alias or alias in interest:
                    return key
    return None


def sector_leaders_as_holdings(sector: str, limit: int) -> list[EtfHolding]:
    """Лидеры отрасли из автогенерированного справочника."""
    leaders = _active_leaders_map()
    key = _resolve_sector_key(sector, leaders)
    if not key:
        logger.warning("Лидеры отрасли не найдены: %s", sector)
        return []

    pool = max(limit, limit * _CANDIDATE_POOL_MULTIPLIER)
    rows = leaders[key][:pool]
    holdings: list[EtfHolding] = []
    for index, row in enumerate(rows):
        name = (row.get("name") or "").strip()
        symbol = (row.get("symbol") or "").strip()
        if not name:
            continue
        holdings.append(
            EtfHolding(
                name=name,
                symbol=symbol or "—",
                weight_pct=float(limit - index),
            )
        )
    return holdings


@lru_cache(maxsize=1)
def build_holding_sector_lookup() -> dict[str, str]:
    """Тикер / название бумаги → отрасль (из автогенерированного справочника)."""
    lookup: dict[str, str] = {}
    for sector, rows in _active_leaders_map().items():
        for row in rows:
            symbol = (row.get("symbol") or "").strip().upper()
            name = (row.get("name") or "").strip()
            if symbol:
                lookup[symbol] = sector
            if name:
                lookup[name.lower()] = sector
    return lookup


def reload_sector_leaders_cache() -> None:
    _load_yaml_leaders_map.cache_clear()
    clear_runtime_sector_leaders()
