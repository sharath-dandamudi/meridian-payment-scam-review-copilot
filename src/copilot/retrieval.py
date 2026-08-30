"""Versioned local policy retrieval with transparent scoring and citations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from langsmith import traceable

from copilot.cache import TTLCache
from copilot.metrics import (
    CACHE_EVENTS,
    RAG_RETRIEVAL_DURATION,
    RAG_RETRIEVAL_SCORE,
    RAG_RETRIEVALS,
    metrics_enabled,
)
from copilot.models import ConfidenceBand, PolicyCitation, RetrievalAssessment
from copilot.reranker import CitationReranker, rerank_safely


@dataclass(frozen=True)
class PolicyDocument:
    policy_id: str
    version: str
    title: str
    body: str


@dataclass(frozen=True)
class RetrievalResult:
    citations: list[PolicyCitation]
    assessment: RetrievalAssessment


class PolicyRetriever:
    """Simple deterministic retriever used until the optional vector backend is enabled.

    This is still retrieval-augmented generation: selected, versioned policy
    content is injected into the synthesis context. Keyword scoring keeps the
    early workflow explainable and removes a hosted-embedding dependency.
    """

    def __init__(self, policy_dir: Path, reranker: CitationReranker | None = None) -> None:
        self._documents = [
            self._parse(path)
            for path in sorted(policy_dir.glob("*.md"))
            if path.name != "README.md"
        ]
        self._cache: TTLCache[RetrievalResult] = TTLCache(max_entries=64, ttl_seconds=300)
        self._reranker = reranker

    @staticmethod
    def _parse(path: Path) -> PolicyDocument:
        content = path.read_text(encoding="utf-8")
        _, frontmatter, body = content.split("---", maxsplit=2)
        values = {
            key.strip(): value.strip()
            for line in frontmatter.strip().splitlines()
            if ":" in line
            for key, value in [line.split(":", maxsplit=1)]
        }
        return PolicyDocument(
            policy_id=values["policy_id"],
            version=values["version"],
            title=values["title"],
            body=body.strip(),
        )

    def retrieve(self, query: str, top_k: int = 4) -> list[PolicyCitation]:
        return self.retrieve_with_assessment(query, top_k).citations

    def excerpt_for_policy(self, policy_id: str, query: str) -> tuple[str, str] | None:
        """Return the query-relevant, locally versioned section for a known policy ID.

        Pinecone identifies the policy document semantically. This method makes the
        analyst citation precise and readable, without trusting a stale hosted excerpt.
        """
        document = next(
            (document for document in self._documents if document.policy_id == policy_id), None
        )
        if document is None:
            return None
        query_tokens = set(re.findall(r"[a-z]{3,}", query.lower()))
        return self._best_section(document.body, query_tokens)

    @traceable(name="rag.retrieve_approved_policy", run_type="retriever")
    def retrieve_with_assessment(self, query: str, top_k: int = 4) -> RetrievalResult:
        started_at = perf_counter()
        cache_key = f"v2:{top_k}:{query.lower()}"
        cached = self._cache.get(cache_key)
        if cached.hit:
            assert cached.value is not None
            if metrics_enabled.get():
                CACHE_EVENTS.labels(cache_name="policy_rag", outcome="hit").inc()
                RAG_RETRIEVALS.labels(
                    confidence_band=cached.value.assessment.confidence_band.value
                ).inc()
                RAG_RETRIEVAL_DURATION.observe(perf_counter() - started_at)
            return cached.value
        if metrics_enabled.get():
            CACHE_EVENTS.labels(cache_name="policy_rag", outcome="miss").inc()
        query_tokens = set(re.findall(r"[a-z]{3,}", query.lower()))

        def score(document: PolicyDocument) -> int:
            document_tokens = set(re.findall(r"[a-z]{3,}", document.body.lower()))
            return len(query_tokens & document_tokens)

        ranked = sorted(
            ((document, score(document)) for document in self._documents),
            key=lambda item: (item[1], item[0].policy_id),
            reverse=True,
        )
        candidate_count = min(len(ranked), max(top_k * 3, top_k))
        candidates: list[PolicyCitation] = []
        for document, _ in ranked[:candidate_count]:
            section, excerpt = self._best_section(document.body, query_tokens)
            candidates.append(
                PolicyCitation(
                    policy_id=document.policy_id,
                    policy_version=document.version,
                    section=section,
                    excerpt=excerpt,
                )
            )
        reranked = rerank_safely(self._reranker, query, candidates, top_k)
        citations = reranked.citations
        top_keyword_score = ranked[0][1] if ranked else 0
        relevant_citation_count = sum(score >= 3 for _, score in ranked[:top_k])
        if top_keyword_score >= 6 and relevant_citation_count >= 1:
            confidence, band = 0.9, ConfidenceBand.HIGH
            rationale = ["Strong keyword overlap with an approved policy source."]
        elif top_keyword_score >= 3 and relevant_citation_count >= 1:
            confidence, band = 0.7, ConfidenceBand.MODERATE
            rationale = ["Partial keyword overlap; analyst should verify policy applicability."]
        else:
            confidence, band = 0.3, ConfidenceBand.LOW
            rationale = ["No sufficiently relevant approved policy content was retrieved."]
        result = RetrievalResult(
            citations=citations,
            assessment=RetrievalAssessment(
                top_keyword_score=top_keyword_score,
                relevant_citation_count=relevant_citation_count,
                confidence=confidence,
                confidence_band=band,
                backend="local",
                search_mode="lexical",
                reranker_used=reranked.used,
                candidate_count=len(candidates),
                rationale=rationale,
            ),
        )
        self._cache.put(cache_key, result)
        if metrics_enabled.get():
            RAG_RETRIEVALS.labels(confidence_band=result.assessment.confidence_band.value).inc()
            RAG_RETRIEVAL_SCORE.observe(result.assessment.top_keyword_score)
            RAG_RETRIEVAL_DURATION.observe(perf_counter() - started_at)
        return result

    @staticmethod
    def _best_section(body: str, query_tokens: set[str]) -> tuple[str, str]:
        sections = re.split(r"(?=^# )", body, flags=re.MULTILINE)
        ranked_sections = sorted(
            sections,
            key=lambda section: len(query_tokens & set(re.findall(r"[a-z]{3,}", section.lower()))),
            reverse=True,
        )
        best = ranked_sections[0].strip()
        lines = best.splitlines()
        heading = lines[0].lstrip("# ") if lines else "Policy"
        excerpt = " ".join(lines[1:]).strip()
        return heading, excerpt[:500]
