"""Structured local telemetry designed to correlate with LangSmith traces."""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from time import perf_counter
from uuid import uuid4

import structlog

from copilot.models import InvestigationDraft

run_id_context: ContextVar[str | None] = ContextVar("run_id", default=None)
case_id_context: ContextVar[str | None] = ContextVar("case_id", default=None)
request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)


def configure_logging() -> None:
    """Configure JSON logs once; trace IDs can be joined in an external backend."""
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


class WorkflowTelemetry:
    """Minimal telemetry wrapper with no sensitive source content in logs."""

    def __init__(self, case_id: str) -> None:
        self.case_id = case_id
        self.run_id = str(uuid4())
        self._started_at = perf_counter()
        self._logger = structlog.get_logger("copilot.workflow")

    def start(self) -> None:
        run_id_context.set(self.run_id)
        case_id_context.set(self.case_id)
        self._logger.info("workflow_started", case_id=self.case_id, run_id=self.run_id)

    def completed(self, route: str, draft: InvestigationDraft | None, gate_failures: int) -> None:
        self._logger.info(
            "workflow_completed",
            case_id=self.case_id,
            run_id=self.run_id,
            request_id=request_id_context.get(),
            route=route,
            recommendation=draft.recommendation.value if draft else None,
            gate_failures=gate_failures,
            duration_ms=round((perf_counter() - self._started_at) * 1000, 2),
        )
