from pathlib import Path

from copilot.rag_evaluation import evaluate_policy_retrieval
from copilot.retrieval import PolicyRetriever

ROOT = Path(__file__).resolve().parents[1]


def test_rag_release_queries_retrieve_expected_approved_policy() -> None:
    report = evaluate_policy_retrieval(
        PolicyRetriever(ROOT / "knowledge_base" / "policy"), ROOT / "evals" / "rag" / "queries.json"
    )

    assert report.passed
    assert report.pass_rate == 1.0
    assert len(report.cases) == 4
