from datetime import date
from pathlib import Path

import pytest

import src.agent_version as agent_version_mod
from src.agent_version import agent_version, get_agent_release_date


def test_agent_version_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DAILY_BRIEFING_RELEASE_DATE", "12.07.2026")
    assert agent_version() == "v12.07.2026"


def test_get_agent_release_date_from_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("DAILY_BRIEFING_RELEASE_DATE", raising=False)
    release_file = tmp_path / "_release_date.txt"
    release_file.write_text("01.06.2026\n", encoding="utf-8")
    monkeypatch.setattr(agent_version_mod, "_RELEASE_DATE_FILE", release_file)
    assert get_agent_release_date() == date(2026, 6, 1)
    assert agent_version() == "v01.06.2026"
