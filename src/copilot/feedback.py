"""Best-effort publication of analyst outcomes as LangSmith online-evaluation feedback."""

from __future__ import annotations

from langsmith import Client

from copilot.models import AnalystDecision
from copilot.redaction import redact_text
from copilot.settings import Settings


def publish_analyst_feedback(
    settings: Settings, trace_id: str | None, decision: AnalystDecision
) -> bool:
    """Publish categorical feedback without blocking the auditable local decision."""
    if not settings.langsmith_tracing or settings.langsmith_api_key is None or trace_id is None:
        return False
    client = Client(
        api_key=settings.langsmith_api_key.get_secret_value(),
        api_url=settings.langsmith_endpoint,
    )
    run = client.read_run(trace_id)
    client.create_feedback(
        key="analyst_outcome",
        value=decision.decision,
        comment=redact_text(decision.rationale),
        trace_id=trace_id,
        session_id=run.session_id,
    )
    return True
