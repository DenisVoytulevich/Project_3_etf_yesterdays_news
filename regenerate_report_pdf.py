"""Пересобрать PDF из сохранённого .md-отчёта (без OpenAI)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.report.pdf import export_report_file_to_pdf
from src.report.storage import REPORT_FILE_PREFIX, reports_base_dir

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _latest_report_md() -> Path | None:
    base = reports_base_dir()
    if not base.is_dir():
        return None
    files = sorted(
        base.rglob(f"{REPORT_FILE_PREFIX}*.md"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return files[0] if files else None


def main() -> int:
    root = Path(__file__).resolve().parent
    md_path = _latest_report_md()
    if md_path is None:
        md_path = root / "templates" / "example.md"
        print(f"Отчёты не найдены, используется: {md_path}")
    else:
        print(f"Markdown: {md_path}")

    pdf_path = md_path.with_suffix(".pdf")
    export_report_file_to_pdf(md_path, pdf_path, title="Торговый брифинг")
    print(f"PDF:      {pdf_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
