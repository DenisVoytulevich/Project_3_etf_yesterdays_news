"""Хранение торговых брифингов."""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.config import load_yaml_config, resolve_data_path
from src.report.pdf import export_markdown_to_pdf

logger = logging.getLogger(__name__)

INDEX_FILENAME = "index.json"
REPORT_FILE_PREFIX = "ETF_briefing_"


def report_filenames(report_id: str) -> tuple[str, str]:
    try:
        stamp = datetime.strptime(report_id, "%Y-%m-%d_%H%M%S").strftime("%Y%m%d_%H%M%S")
    except ValueError:
        stamp = report_id.replace("-", "")
    base = f"{REPORT_FILE_PREFIX}{stamp}"
    return f"{base}.md", f"{base}.pdf"


@dataclass
class ReportMetadata:
    id: str
    created_at: str
    trading_date: str
    yesterday_date: str
    ai_model: str
    portfolio_count: int
    news_total: int
    watchlist_count: int = 0
    calendar_events: int = 0
    screening_sectors: int = 0
    markdown_file: str = "report.md"
    pdf_file: str | None = "report.pdf"
    html_file: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReportMetadata:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ReportResult:
    markdown: str
    metadata: ReportMetadata
    html: str | None = None


@dataclass
class SavedReport:
    markdown: str
    metadata: ReportMetadata
    directory: Path
    md_path: Path
    pdf_path: Path | None


def reports_config() -> dict[str, Any]:
    cfg = load_yaml_config().get("reports", {})
    return {
        "enabled": cfg.get("enabled", True),
        "output_dir": cfg.get("output_dir", "data/reports"),
        "keep_days": int(cfg.get("keep_days", 365)),
        "save_pdf": cfg.get("save_pdf", True),
    }


def reports_base_dir() -> Path:
    cfg = reports_config()
    return resolve_data_path(cfg["output_dir"])


def _report_directory(base: Path, report_id: str) -> Path:
    date_part = report_id[:10]
    return base / date_part[:4] / date_part / report_id


def _index_path(base: Path) -> Path:
    return base / INDEX_FILENAME


def _load_index(base: Path) -> list[dict[str, Any]]:
    path = _index_path(base)
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, list) else []
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Не удалось прочитать индекс отчётов: %s", exc)
        return []


def _save_index(base: Path, entries: list[dict[str, Any]]) -> None:
    base.mkdir(parents=True, exist_ok=True)
    _index_path(base).write_text(
        json.dumps(entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _append_to_index(base: Path, metadata: ReportMetadata, report_dir: Path) -> None:
    rel_dir = report_dir.relative_to(base).as_posix()
    entry = metadata.to_dict()
    entry["directory"] = rel_dir
    entries = [e for e in _load_index(base) if e.get("id") != metadata.id]
    entries.insert(0, entry)
    _save_index(base, entries)


def cleanup_old_reports(
    base: Path | None = None,
    keep_days: int = 30,
) -> list[Path]:
    if keep_days <= 0:
        return []
    base = base or reports_base_dir()
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    kept: list[dict[str, Any]] = []
    removed: list[Path] = []
    for entry in _load_index(base):
        created_raw = entry.get("created_at", "")
        try:
            created = datetime.fromisoformat(created_raw)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
        except ValueError:
            kept.append(entry)
            continue
        if created >= cutoff:
            kept.append(entry)
            continue
        rel_dir = entry.get("directory")
        if rel_dir:
            old_dir = base / rel_dir
            if old_dir.is_dir():
                shutil.rmtree(old_dir, ignore_errors=True)
                removed.append(old_dir)
                logger.info("Удалён устаревший брифинг: %s", old_dir)
    if len(kept) != len(_load_index(base)):
        _save_index(base, kept)
    return removed


def save_report(
    markdown: str,
    metadata: ReportMetadata,
    *,
    output_dir: Path | None = None,
    save_pdf: bool | None = None,
    html: str | None = None,
) -> SavedReport:
    cfg = reports_config()
    base = output_dir or reports_base_dir()
    if save_pdf is None:
        save_pdf = cfg["save_pdf"]

    report_dir = _report_directory(base, metadata.id)
    report_dir.mkdir(parents=True, exist_ok=True)

    md_name, pdf_name = report_filenames(metadata.id)
    metadata.markdown_file = md_name
    metadata.pdf_file = pdf_name if save_pdf else None

    md_path = report_dir / metadata.markdown_file
    md_path.write_text(markdown, encoding="utf-8")

    if html:
        html_name = md_name.replace(".md", ".html")
        metadata.html_file = html_name
        (report_dir / html_name).write_text(html, encoding="utf-8")

    pdf_path: Path | None = None
    if save_pdf and metadata.pdf_file:
        pdf_path = report_dir / metadata.pdf_file
        try:
            export_markdown_to_pdf(
                markdown,
                pdf_path,
                title=f"Торговый брифинг · {metadata.trading_date}",
            )
        except Exception:
            logger.exception("Не удалось сгенерировать PDF для брифинга %s", metadata.id)
            pdf_path = None
            metadata.pdf_file = None

    (report_dir / "metadata.json").write_text(
        json.dumps(metadata.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    _append_to_index(base, metadata, report_dir)
    cleanup_old_reports(base, cfg["keep_days"])

    logger.info("Брифинг сохранён: %s", report_dir.resolve())
    return SavedReport(
        markdown=markdown,
        metadata=metadata,
        directory=report_dir,
        md_path=md_path,
        pdf_path=pdf_path,
    )


def list_reports(limit: int = 50) -> list[dict[str, Any]]:
    """Возвращает последние записи из index.json (newest first)."""
    entries = _load_index(reports_base_dir())[: max(0, limit)]
    return entries


def get_report_path(report_id: str, *, kind: str = "pdf") -> Path | None:
    """Путь к файлу отчёта по id (md | pdf | html | dir)."""
    for entry in _load_index(reports_base_dir()):
        if entry.get("id") != report_id:
            continue
        rel_dir = entry.get("directory")
        if not rel_dir:
            return None
        report_dir = reports_base_dir() / rel_dir
        if kind == "dir":
            return report_dir if report_dir.is_dir() else None
        default_md, default_pdf = report_filenames(report_id)
        if kind == "pdf":
            filename = entry.get("pdf_file") or default_pdf
        elif kind == "html":
            filename = entry.get("html_file")
            if not filename:
                return None
        else:
            filename = entry.get("markdown_file") or default_md
        path = report_dir / filename
        return path if path.is_file() else None
    return None


def delete_report(report_id: str) -> bool:
    """Удаляет каталог отчёта и запись из index.json. True если что-то удалили."""
    base = reports_base_dir()
    entries = _load_index(base)
    kept: list[dict[str, Any]] = []
    removed_dir: Path | None = None
    found = False
    for entry in entries:
        if entry.get("id") != report_id:
            kept.append(entry)
            continue
        found = True
        rel_dir = entry.get("directory")
        if rel_dir:
            report_dir = base / rel_dir
            if report_dir.is_dir():
                shutil.rmtree(report_dir, ignore_errors=True)
                removed_dir = report_dir
    if not found:
        return False
    _save_index(base, kept)
    if removed_dir is not None:
        logger.info("Удалён брифинг: %s", removed_dir)
    else:
        logger.info("Удалена запись индекса брифинга: %s", report_id)
    return True


def persist_report_result(result: ReportResult) -> SavedReport | None:
    if not reports_config()["enabled"]:
        return None
    return save_report(result.markdown, result.metadata, html=result.html)
