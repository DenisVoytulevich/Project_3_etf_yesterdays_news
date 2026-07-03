"""Проверка профилей ширин PDF и пересборка preview_briefing.pdf."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.report.pdf import (
    _TABLE1_COL_WIDTHS,
    _TABLE3_COL_WIDTHS,
    _col_width_percents,
    _fixed_table_col_widths,
    export_report_file_to_pdf,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TABLE1_HEADERS = [
    "Событие",
    "Сила события",
    "Сектор",
    "Влияние на драйвер сектора",
]
TABLE3_HEADERS = [
    "Компания",
    "Зона",
    "Отрасль",
    "Новость за вчера",
    "Влияние",
]


def main() -> int:
    root = Path(__file__).resolve().parent
    pdf_py = root / "src" / "report" / "pdf.py"
    print(f"pdf.py: {pdf_py} (mtime {pdf_py.stat().st_mtime:.0f})")
    print()
    print("§1 профиль:", _TABLE1_COL_WIDTHS)
    w1 = _fixed_table_col_widths(TABLE1_HEADERS)
    assert w1 == _TABLE1_COL_WIDTHS
    print("§1 %:", tuple(round(x, 1) for x in _col_width_percents(w1)))
    print("  Сила события ~5%, Сектор ~21% (было 8% / 14%)")
    print()
    print("§3 профиль:", _TABLE3_COL_WIDTHS)
    w3 = _fixed_table_col_widths(TABLE3_HEADERS)
    assert w3 == _TABLE3_COL_WIDTHS
    print("§3 %:", tuple(round(x, 1) for x in _col_width_percents(w3)))
    print("  Зона ~14%, Влияние ~12% (было 10% / 16%)")
    print()

    md = root / "templates" / "example.md"
    out = root / "data" / "preview_briefing.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    export_report_file_to_pdf(md, out, title="Торговый брифинг")
    print(f"PDF пересобран: {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
