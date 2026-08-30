"""Hosted Pinecone policy retrieval with a deterministic local fallback."""

from __future__ import annotations

import logging
from pathlib import Path
from time import sleep
from typing import Literal

from openai import OpenAI
from pinecone import Pinecone

from copilot.metrics import RAG_FALLBACKS, metrics_enabled
from copilot.models import ConfidenceBand, PolicyCitation, RetrievalAssessment
from copilot.reranker import CrossEncoderReranker, rerank_safely
from copilot.retrieval import PolicyRetriever, RetrievalResult
from copilot.settings import Settings

NEBIUS_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
logger = logging.getLogger(__name__)


class PineconePolicyRetriever:
    """Queries Pinecone for approved policy, falling back safely to local retrieval."""

    def __init__(self, settings: Settings, policy_dir: Path) -> None:
        if settings.nebius_api_key is None or settings.pinecone_api_key is None:
            raise ValueError("Nebius and Pinecone credentials are required for hosted policy RAG.")
        self._reranker = (
            CrossEncoderReranker(settings.reranker_model_name)
            if settings.reranker_enabled
            else None
        )
        self._fallback = PolicyRetriever(policy_dir, reranker=self._reranker)
        self._embedding_client = OpenAI(
            base_url=NEBIUS_BASE_URL,
            api_key=settings.nebius_api_key.get_secret_value(),
            timeout=30,
        )
        pinecone = Pinecone(api_key=settings.pinecone_api_key.get_secret_value())
        descriptor = pinecone.describe_index(settings.pinecone_index_name)
        self._index = pinecone.Index(host=descriptor.host)
        self._namespace = settings.pinecone_namespace
        self._embedding_model = settings.embedding_model_name
        self._hybrid_search_enabled = settings.hybrid_search_enabled

    def retrieve(self, query: str, top_k: int = 4) -> list[PolicyCitation]:
        return self.retrieve_with_assessment(query, top_k).citations

    def retrieve_with_assessment(self, query: str, top_k: int = 4) -> RetrievalResult:
        try:
            # A single retry smooths over a transient provider/network failure without
            # making an analyst wait through a long retry chain.
            for attempt in range(2):
                try:
                    embedding = (
                        self._embedding_client.embeddings.create(
                            model=self._embedding_model, input=query
                        )
                        .data[0]
                        .embedding
                    )
                    response = self._index.query(
                        vector=embedding,
                        top_k=max(top_k * 3, top_k),
                        include_metadata=True,
                        namespace=self._namespace,
                    )
                    break
                except Exception:
                    if attempt == 1:
                        raise
                    sleep(0.25)
            matches = response.matches or []
            semantic_citations: list[PolicyCitation] = []
            for match in matches:
                policy_id = str(match.metadata["policy_id"])
                local_excerpt = self._fallback.excerpt_for_policy(policy_id, query)
                # The packaged, versioned corpus is the citation source of record.
                # This also repairs older hosted vectors that stored an empty excerpt.
                section, excerpt = local_excerpt or (
                    str(match.metadata.get("section", "Policy")),
                    str(match.metadata.get("excerpt", "")),
                )
                semantic_citations.append(
                    PolicyCitation(
                        policy_id=policy_id,
                        policy_version=str(match.metadata["policy_version"]),
                        section=section,
                        excerpt=excerpt,
                    )
                )
            candidates = semantic_citations
            search_mode: Literal["semantic", "hybrid"] = "semantic"
            if self._hybrid_search_enabled:
                # The local versioned corpus supplies lexical candidates. Merging it
                # with Pinecone's semantic candidates gives robust coverage for exact
                # policy terms as well as meaning-based matches.
                lexical = self._fallback.retrieve_with_assessment(
                    query, top_k=max(top_k * 3, top_k)
                )
                candidates = self._merge_candidates(semantic_citations, lexical.citations)
                search_mode = "hybrid"
            reranked = rerank_safely(self._reranker, query, candidates, top_k)
            citations = reranked.citations
            top_score = float(matches[0].score) if matches else 0.0
            if top_score >= 0.65 and citations:
                confidence, band = 0.9, ConfidenceBand.HIGH
                rationale = [
                    "Hybrid semantic and lexical retrieval returned a high-similarity approved "
                    "policy match."
                ]
            elif top_score >= 0.45 and citations:
                confidence, band = 0.7, ConfidenceBand.MODERATE
                rationale = [
                    "Hybrid semantic and lexical retrieval returned a moderate-similarity policy "
                    "match."
                ]
            else:
                confidence, band = 0.3, ConfidenceBand.LOW
                rationale = [
                    "Hosted vector retrieval did not return a sufficiently similar policy match."
                ]
            return RetrievalResult(
                citations=citations,
                assessment=RetrievalAssessment(
                    top_keyword_score=round(top_score * 100),
                    relevant_citation_count=len(citations),
                    confidence=confidence,
                    confidence_band=band,
                    backend="pinecone",
                    search_mode=search_mode,
                    reranker_used=reranked.used,
                    candidate_count=len(candidates),
                    rationale=rationale,
                ),
            )
        except Exception as error:
            logger.warning("Hosted policy retrieval failed; using local approved-policy fallback.")
            if metrics_enabled.get():
                RAG_FALLBACKS.labels(reason=type(error).__name__).inc()
            fallback = self._fallback.retrieve_with_assessment(query, top_k)
            assessment = fallback.assessment.model_copy(
                update={
                    "fallback_used": True,
                    "rationale": [
                        "Hosted vector retrieval was temporarily unavailable; used the local "
                        "versioned approved-policy fallback.",
                        *fallback.assessment.rationale,
                    ],
                }
            )
            return RetrievalResult(citations=fallback.citations, assessment=assessment)

    @staticmethod
    def _merge_candidates(
        semantic: list[PolicyCitation], lexical: list[PolicyCitation]
    ) -> list[PolicyCitation]:
        merged: dict[str, PolicyCitation] = {}
        for citation in [*semantic, *lexical]:
            merged.setdefault(citation.policy_id, citation)
        return list(merged.values())


def ingest_policy_documents(settings: Settings, policy_dir: Path) -> int:
    """Embed and upsert only the fictional approved policy corpus into Pinecone."""
    retriever = PineconePolicyRetriever(settings, policy_dir)
    vectors = []
    for document in retriever._fallback._documents:
        embedding = (
            retriever._embedding_client.embeddings.create(
                model=retriever._embedding_model, input=document.body
            )
            .data[0]
            .embedding
        )
        # Store a readable fallback passage. At retrieval time it is replaced by the
        # query-specific section from the locally versioned corpus.
        section = "Policy overview"
        excerpt = " ".join(document.body.split())[:500]
        vectors.append(
            {
                "id": f"{document.policy_id}:{document.version}",
                "values": embedding,
                "metadata": {
                    "policy_id": document.policy_id,
                    "policy_version": document.version,
                    "section": section,
                    "excerpt": excerpt,
                    "corpus": "fictional-approved-policy",
                },
            }
        )
    retriever._index.upsert(vectors=vectors, namespace=retriever._namespace)
    return len(vectors)
