"""Простой HTML-рендер торгового брифинга."""

from __future__ import annotations

import html
import re

from src.agent_version import agent_version
from src.pipeline.models import BRIEFING_SECTION_KEYS


def _markdown_table_to_html(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip().startswith("|")]
    if len(lines) < 2:
        return f"<pre>{html.escape(text)}</pre>"

    rows: list[list[str]] = []
    for line in lines:
        if re.match(r"^\|[\s\-:|]+\|$", line):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        rows.append(cells)

    if not rows:
        return f"<pre>{html.escape(text)}</pre>"

    header = rows[0]
    body = rows[1:]
    parts = ["<table>", "<thead><tr>"]
    for cell in header:
        parts.append(f"<th>{html.escape(cell)}</th>")
    parts.append("</tr></thead><tbody>")
    for row in body:
        parts.append("<tr>")
        for cell in row:
            parts.append(f"<td>{html.escape(cell)}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def _section_to_html(content: str) -> str:
    if "|" in content and "---" in content:
        prefix_lines: list[str] = []
        table_lines: list[str] = []
        in_table = False
        for line in content.splitlines():
            if line.strip().startswith("|"):
                in_table = True
                table_lines.append(line)
            elif not in_table:
                prefix_lines.append(line)
        html_parts = []
        if prefix_lines:
            html_parts.append(
                f"<p>{html.escape(chr(10).join(prefix_lines).strip())}</p>"
            )
        if table_lines:
            html_parts.append(_markdown_table_to_html("\n".join(table_lines)))
        return "".join(html_parts) or f"<p>{html.escape(content)}</p>"
    return f"<p>{html.escape(content).replace(chr(10), '<br>')}</p>"


_SECTION_TITLES = {
    "executive_summary": "Резюме",
    "top_market_news": "1. Топ новости",
    "sector_ratings": "2. Рейтинг отраслей",
    "portfolio_companies_news": "3. Новости компаний",
    "key_risks_today": "4. Ключевые риски дня",
}


def render_html_report(
    sections: dict[str, str],
    *,
    trading_date: str,
    yesterday_date: str,
    report_datetime: str,
    news_count: int,
    ai_model: str,
) -> str:
    body_parts = [
        "<!DOCTYPE html>",
        '<html lang="ru">',
        "<head>",
        '<meta charset="utf-8">',
        "<title>Торговый брифинг</title>",
        "<style>",
        "body{font-family:Segoe UI,Arial,sans-serif;max-width:900px;margin:2rem auto;line-height:1.5}",
        "h1,h2{color:#1a1a2e}table{border-collapse:collapse;width:100%;margin:1rem 0}",
        "th,td{border:1px solid #ccc;padding:6px 8px;font-size:14px}",
        "th{background:#f0f0f5}",
        ".meta{color:#666;font-size:14px}",
        "</style>",
        "</head>",
        "<body>",
        "<h1>Торговый брифинг</h1>",
        f'<p class="meta">Торговый день: {html.escape(trading_date)} · '
        f"Новости за: {html.escape(yesterday_date)} · "
        f"Сформирован: {html.escape(report_datetime)} (Варшава)</p>",
    ]

    for key in BRIEFING_SECTION_KEYS:
        content = sections.get(key, "")
        if not content:
            continue
        title = _SECTION_TITLES.get(key, key)
        tag = "h2" if key != "executive_summary" else "h2"
        body_parts.append(f"<{tag}>{html.escape(title)}</{tag}>")
        body_parts.append(_section_to_html(content))

    body_parts.append(
        f'<p class="meta">Автобрифинг · {html.escape(agent_version())} · '
        f'{html.escape(ai_model)} · '
        f"Источников: {news_count}</p>"
    )
    body_parts.extend(["</body>", "</html>"])
    return "\n".join(body_parts)
