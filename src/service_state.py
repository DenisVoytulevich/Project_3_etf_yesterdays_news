"""Runtime enable/disable for Daily Briefing (cabinet + bot share this file)."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from src.config import get_data_dir

logger = logging.getLogger(__name__)

STATE_FILENAME = "service_state.json"
DISABLED_MESSAGE = (
    "Функция отключена с Рабочего кабинета микросервисов."
)


def _state_path() -> Path:
    return get_data_dir() / STATE_FILENAME


def _env_default_enabled() -> bool:
    raw = os.environ.get("DAILY_BRIEFING_ENABLED", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _read_state() -> dict[str, Any]:
    path = _state_path()
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Не удалось прочитать %s: %s", path, exc)
        return {}


def is_service_enabled() -> bool:
    """True if Daily Briefing may run (manual button + scheduled job)."""
    state = _read_state()
    if "enabled" in state:
        return bool(state["enabled"])
    return _env_default_enabled()


def set_service_enabled(enabled: bool) -> bool:
    """Persist enable flag for bot and cabinet. Returns the stored value."""
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"enabled": bool(enabled)}
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("Daily Briefing enabled=%s (%s)", enabled, path)
    return bool(enabled)
