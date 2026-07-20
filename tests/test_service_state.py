"""Tests for Daily Briefing enable flag and report delete."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_service_enabled_defaults_true(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DAILY_BRIEFING_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DAILY_BRIEFING_ENABLED", raising=False)

    from src.service_state import is_service_enabled, set_service_enabled

    assert is_service_enabled() is True
    assert set_service_enabled(False) is False
    assert is_service_enabled() is False
    assert (tmp_path / "service_state.json").is_file()
    assert set_service_enabled(True) is True
    assert is_service_enabled() is True


def test_service_enabled_env_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DAILY_BRIEFING_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DAILY_BRIEFING_ENABLED", "false")

    from src.service_state import is_service_enabled

    assert is_service_enabled() is False


def test_list_and_delete_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DAILY_BRIEFING_DATA_DIR", str(tmp_path))

    from src.report.storage import (
        ReportMetadata,
        delete_report,
        list_reports,
        reports_base_dir,
        save_report,
    )

    base = reports_base_dir()
    meta = ReportMetadata(
        id="2026-07-20_120000",
        created_at="2026-07-20T10:00:00+00:00",
        trading_date="20 июля 2026",
        yesterday_date="19 июля 2026",
        ai_model="test",
        portfolio_count=1,
        news_total=0,
    )
    saved = save_report("# test\n", meta, save_pdf=False)
    assert saved.directory.is_dir()
    assert len(list_reports()) == 1
    assert delete_report(meta.id) is True
    assert list_reports() == []
    assert not saved.directory.exists()
    assert delete_report(meta.id) is False
    index = json.loads((base / "index.json").read_text(encoding="utf-8"))
    assert index == []
