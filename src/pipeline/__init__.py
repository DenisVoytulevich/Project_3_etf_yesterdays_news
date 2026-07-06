from src.pipeline.models import BRIEFING_SECTION_KEYS

__all__ = ["BRIEFING_SECTION_KEYS", "run_multi_agent_pipeline"]


def run_multi_agent_pipeline(*args, **kwargs):
    from src.pipeline.orchestrator import run_multi_agent_pipeline as _run

    return _run(*args, **kwargs)
