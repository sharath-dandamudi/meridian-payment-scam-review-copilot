"""Optional local cross-encoder reranking for retrieved approved-policy excerpts."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import cached_property
from time import perf_counter
from typing import Protocol

from langsmith import traceable

from copilot.metrics import RERANKER_DURATION, RERANKER_RUNS, metrics_enabled
from copilot.models import PolicyCitation

logger = logging.getLogger(__name__)


class CitationReranker(Protocol):
    def rerank(
        self, query: str, citations: list[PolicyCitation], top_k: int
    ) -> list[PolicyCitation]: ...


@dataclass(frozen=True)
class RerankResult:
    citations: list[PolicyCitation]
    used: bool


class CrossEncoderReranker:
    """Lazy local model wrapper; retrieval remains usable if model loading fails."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    @cached_property
    def _model(self) -> object:
        from sentence_transformers import CrossEncoder

        return CrossEncoder(self.model_name)

    @traceable(name="rag.cross_encoder_rerank", run_type="chain")
    def rerank(
        self, query: str, citations: list[PolicyCitation], top_k: int
    ) -> list[PolicyCitation]:
        started_at = perf_counter()
        try:
            pairs = [(query, citation.excerpt) for citation in citations]
            scores = self._model.predict(pairs)  # type: ignore[attr-defined]
            ranked = sorted(
                zip(scores, citations, strict=True), key=lambda item: item[0], reverse=True
            )
            if metrics_enabled.get():
                RERANKER_RUNS.labels(outcome="success").inc()
            return [citation for _, citation in ranked[:top_k]]
        except Exception:
            logger.warning("Cross-encoder reranker was unavailable; retaining retrieval order.")
            if metrics_enabled.get():
                RERANKER_RUNS.labels(outcome="fallback").inc()
            raise
        finally:
            if metrics_enabled.get():
                RERANKER_DURATION.observe(perf_counter() - started_at)


def rerank_safely(
    reranker: CitationReranker | None,
    query: str,
    citations: list[PolicyCitation],
    top_k: int,
) -> RerankResult:
    """Keep the retrieval result safe and available when optional reranking fails."""
    if reranker is None or len(citations) <= top_k:
        return RerankResult(citations=citations[:top_k], used=False)
    try:
        return RerankResult(citations=reranker.rerank(query, citations, top_k), used=True)
    except Exception:
        return RerankResult(citations=citations[:top_k], used=False)
