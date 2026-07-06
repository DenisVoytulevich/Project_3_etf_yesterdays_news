"""Загрузка промптов агентов и рендер через Jinja2."""

from __future__ import annotations

from jinja2 import Template

from src.config import get_project_root


def load_agent_prompt(name: str) -> str:
    path = get_project_root() / "prompts" / f"{name}.md"
    return path.read_text(encoding="utf-8")


def render_agent_prompt(name: str, **context) -> str:
    template = Template(load_agent_prompt(name))
    return template.render(**context)
