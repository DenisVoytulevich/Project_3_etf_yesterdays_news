import os
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    google_sheets_id: str = ""
    google_credentials_path: str = "credentials/google_service_account.json"

    openai_api_key: str = ""
    openai_model: str = "gpt-5-nano"

    newsapi_key: str = ""

    timezone: str = "Europe/Warsaw"
    daily_briefing_hour: int = 9
    daily_briefing_minute: int = 0
    off_hours_weekday_start: int = 19
    off_hours_weekday_end: int = 9


def load_yaml_config() -> dict:
    config_path = Path(__file__).resolve().parents[1] / "config" / "settings.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_project_root() -> Path:
    root = os.environ.get("DAILY_BRIEFING_ROOT")
    if root:
        return Path(root)
    return Path(__file__).resolve().parents[1]


def get_data_dir() -> Path:
    """Writable data directory (reports, cache). Separate from code when mounted ro."""
    data = os.environ.get("DAILY_BRIEFING_DATA_DIR")
    if data:
        return Path(data)
    return get_project_root() / "data"


def resolve_data_path(rel: str | Path) -> Path:
    path = Path(rel)
    if path.is_absolute():
        return path
    rel_posix = path.as_posix()
    if rel_posix == "data" or rel_posix.startswith("data/"):
        suffix = path.relative_to("data") if rel_posix != "data" else Path()
        return get_data_dir() / suffix
    return get_project_root() / path
