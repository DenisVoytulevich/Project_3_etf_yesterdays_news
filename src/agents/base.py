"""Базовый клиент OpenAI для агентов пайплайна."""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI

from src.config import Settings

logger = logging.getLogger(__name__)


class AgentError(RuntimeError):
    """Ошибка вызова агента."""


def require_openai(settings: Settings) -> None:
    if not (settings.openai_api_key or "").strip():
        raise AgentError("OPENAI_API_KEY не задан")


def call_json_agent(
    settings: Settings,
    *,
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
) -> tuple[dict[str, Any], str]:
    require_openai(settings)
    used_model = model or settings.openai_model
    if not used_model.strip():
        used_model = settings.openai_model
    try:
        logger.info("Агент OpenAI, модель: %s", used_model)
        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model=used_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        payload = json.loads(content)
        return payload, response.model or used_model
    except AgentError:
        raise
    except Exception as exc:
        logger.error("OpenAI недоступен (%s)", exc)
        raise AgentError("OpenAI недоступен") from exc
