"""Предпросмотр PDF из templates/example.md."""

from pathlib import Path

from src.report.pdf import export_report_file_to_pdf

if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    md = root / "templates" / "example.md"
    out = root / "data" / "preview_briefing.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    export_report_file_to_pdf(md, out, title="Торговый брифинг")
    print(out)
