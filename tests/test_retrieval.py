from pathlib import Path

from copilot.models import PolicyCitation
from copilot.retrieval import PolicyRetriever

POLICY_DIR = Path(__file__).resolve().parents[1] / "knowledge_base" / "policy"


def test_retrieval_returns_versioned_policy_citations() -> None:
    citations = PolicyRetriever(POLICY_DIR).retrieve(
        "unusual outbound payment first-time payee account baseline evidence"
    )

    assert len(citations) == 4
    assert "PAY-SCAM-001" in {citation.policy_id for citation in citations}
    assert all(citation.policy_version == "1.0" for citation in citations)


def test_retrieval_returns_explainable_confidence_assessment() -> None:
    result = PolicyRetriever(POLICY_DIR).retrieve_with_assessment(
        "unusual outbound payment first-time payee account baseline evidence"
    )

    assert result.assessment.confidence_band == "high"
    assert result.assessment.confidence >= 0.8
    assert result.assessment.relevant_citation_count >= 1


def test_policy_excerpt_is_query_relevant_and_never_an_empty_hosted_placeholder() -> None:
    retriever = PolicyRetriever(POLICY_DIR)

    excerpt = retriever.excerpt_for_policy(
        "PAY-SCAM-003", "first-time PayID payment against usual customer activity"
    )

    assert excerpt is not None
    section, passage = excerpt
    assert section == "Trigger context"
    assert "PayID" in passage


class ReversingReranker:
    def rerank(
        self, query: str, citations: list[PolicyCitation], top_k: int
    ) -> list[PolicyCitation]:
        return list(reversed(citations))[:top_k]


def test_cross_encoder_contract_reranks_a_wider_candidate_set() -> None:
    result = PolicyRetriever(POLICY_DIR, reranker=ReversingReranker()).retrieve_with_assessment(
        "unusual outbound payment first-time payee account baseline evidence"
    )

    assert result.assessment.reranker_used is True
    assert result.assessment.candidate_count == 12
    assert len(result.citations) == 4
