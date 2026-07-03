"""Параметры глубины загрузки состава ETF."""

from __future__ import annotations

from src.config import load_yaml_config

DEFAULT_HOLDINGS_TOP_LIMIT = 25


def holdings_top_limit() -> int:
    value = load_yaml_config().get("structure", {}).get(
        "holdings_top_limit", DEFAULT_HOLDINGS_TOP_LIMIT
    )
    return max(10, int(value))
