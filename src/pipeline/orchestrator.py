"""Оркестратор мультиагентного пайплайна."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.agents.base import AgentError
from src.config import Settings, load_yaml_config, resolve_data_path
from src.pipeline.models import PipelineArtifacts
from src.pipeline.stages.analyst import run_analyst
from src.pipeline.stages.consistency import run_consistency_validator
from src.pipeline.stages.entity_extractor import run_entity_extractor
from src.pipeline.stages.focus_context import build_focus_context
from src.pipeline.stages.news_collector import run_news_collector
from src.pipeline.stages.qa_analytics import run_qa_analytics
from src.pipeline.stages.qa_editor import run_qa_editor
from src.pipeline.stages.renderer import run_renderer
from src.pipeline.stages.revision import run_revision_agent
from src.pipeline.stages.theme_normalizer import run_theme_normalizer
from src.report.generator import ReportGenerationError
from src.report.storage import ReportResult

logger = logging.getLogger(__name__)


def _pipeline_config() -> dict[str, Any]:
    return load_yaml_config().get("pipeline", {})


def _checkpoint_dir(run_id: str) -> Path:
    cfg = _pipeline_config()
    rel = cfg.get("checkpoint_dir", "data/pipeline")
    return resolve_data_path(rel) / run_id


def _save_checkpoint(run_id: str, name: str, payload: Any) -> None:
    cfg = _pipeline_config()
    if not cfg.get("save_checkpoints", True):
        return
    directory = _checkpoint_dir(run_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.json"
    if hasattr(payload, "__dataclass_fields__"):
        from dataclasses import asdict

        data = asdict(payload)
    else:
        data = payload
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


async def run_multi_agent_pipeline(
    settings: Settings,
    *,
    calendar=None,
) -> ReportResult:
    """Полный мультиагентный пайплайн: focus → render."""
    try:
        focus = await build_focus_context(settings, calendar=calendar)
        run_id = focus.dates.local.strftime("%Y-%m-%d_%H%M%S")
        _save_checkpoint(run_id, "00_focus", {"screening_sectors": focus.screening_sectors})

        news = await run_news_collector(focus, settings)
        _save_checkpoint(
            run_id,
            "01_news",
            {
                "count": len(news.items),
                "removed_duplicates": news.removed_duplicates,
                "removed_by_time": news.removed_by_time,
            },
        )

        extracted = await run_entity_extractor(news, focus, settings)
        _save_checkpoint(run_id, "02_entities", extracted)

        normalized = await run_theme_normalizer(extracted, focus, settings)
        _save_checkpoint(run_id, "03_normalized", normalized)

        draft = await run_analyst(normalized, news, focus, settings)
        _save_checkpoint(run_id, "04_draft", draft)

        editor_qa = await run_qa_editor(draft, focus, settings)
        _save_checkpoint(run_id, "05_qa_editor", editor_qa)

        analytics_qa = await run_qa_analytics(draft, normalized, news, focus, settings)
        _save_checkpoint(run_id, "06_qa_analytics", analytics_qa)

        revised = await run_revision_agent(draft, editor_qa, analytics_qa, focus, settings)
        _save_checkpoint(run_id, "07_revised", revised)

        validated = run_consistency_validator(revised, focus)
        _save_checkpoint(run_id, "08_validated", validated)

        result = run_renderer(validated, news, focus, settings)
        _save_checkpoint(
            run_id,
            "09_result",
            {"metadata": result.metadata.to_dict(), "markdown_len": len(result.markdown)},
        )
        return result
    except AgentError as exc:
        raise ReportGenerationError(str(exc)) from exc


async def run_multi_agent_pipeline_with_artifacts(
    settings: Settings,
    *,
    calendar=None,
) -> tuple[ReportResult, PipelineArtifacts]:
    """Пайплайн с возвратом промежуточных артефактов (для отладки)."""
    focus = await build_focus_context(settings, calendar=calendar)
    news = await run_news_collector(focus, settings)
    extracted = await run_entity_extractor(news, focus, settings)
    normalized = await run_theme_normalizer(extracted, focus, settings)
    draft = await run_analyst(normalized, news, focus, settings)
    editor_qa = await run_qa_editor(draft, focus, settings)
    analytics_qa = await run_qa_analytics(draft, normalized, news, focus, settings)
    revised = await run_revision_agent(draft, editor_qa, analytics_qa, focus, settings)
    validated = run_consistency_validator(revised, focus)
    result = run_renderer(validated, news, focus, settings)
    artifacts = PipelineArtifacts(
        focus=focus,
        news=news,
        extracted=extracted,
        normalized=normalized,
        draft=draft,
        editor_qa=editor_qa,
        analytics_qa=analytics_qa,
        validated=validated,
    )
    return result, artifacts
