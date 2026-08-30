from pathlib import Path

from copilot.models import ConfidenceBand, Recommendation, RetrievalAssessment
from copilot.retrieval import RetrievalResult
from copilot.workflow import InvestigationWorkflow

ROOT = Path(__file__).resolve().parents[1]


def test_high_risk_case_reaches_human_review_with_citations(tmp_path: Path) -> None:
    workflow = InvestigationWorkflow(
        ROOT / "data" / "fixtures",
        ROOT / "knowledge_base" / "policy",
        tmp_path / "checkpoints.sqlite",
    )

    state = workflow.invoke("CASE-AU-001")

    assert state["route"] == "human_review"
    assert state["draft"].recommendation == Recommendation.HUMAN_ESCALATION
    assert len(state["draft"].policy_citations) == 4
    assert all(gate.passed for gate in state["gate_results"])


def test_low_risk_case_still_requires_human_review(tmp_path: Path) -> None:
    workflow = InvestigationWorkflow(
        ROOT / "data" / "fixtures",
        ROOT / "knowledge_base" / "policy",
        tmp_path / "checkpoints.sqlite",
    )

    state = workflow.invoke("CASE-AU-003")

    assert state["route"] == "human_review"
    assert state["draft"].recommendation == Recommendation.FURTHER_INVESTIGATION


def test_missing_alert_routes_to_insufficient_evidence(tmp_path: Path) -> None:
    workflow = InvestigationWorkflow(
        ROOT / "data" / "fixtures",
        ROOT / "knowledge_base" / "policy",
        tmp_path / "checkpoints.sqlite",
    )

    state = workflow.invoke("CASE-DOES-NOT-EXIST")

    assert state["route"] == "insufficient_evidence"
    assert state["errors"]


def test_missing_transaction_control_case_routes_safely_to_insufficient_evidence(
    tmp_path: Path,
) -> None:
    workflow = InvestigationWorkflow(
        ROOT / "data" / "fixtures",
        ROOT / "knowledge_base" / "policy",
        tmp_path / "checkpoints.sqlite",
    )

    state = workflow.invoke("CASE-CTRL-001")

    assert state["route"] == "insufficient_evidence"
    assert state.get("draft") is None
    assert "No transaction exists" in state["errors"][-1]


def test_policy_source_control_mode_stops_before_synthesis(tmp_path: Path) -> None:
    workflow = InvestigationWorkflow(
        ROOT / "data" / "fixtures",
        ROOT / "knowledge_base" / "policy",
        tmp_path / "checkpoints.sqlite",
    )

    state = workflow.invoke("CASE-CTRL-002", control_mode="policy_source_unavailable")

    assert state["route"] == "insufficient_evidence"
    assert state.get("draft") is None
    assert "Approved-policy source was unavailable" in state["errors"][-1]


def test_checkpoint_survives_workflow_recreation(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "checkpoints.sqlite"
    first_workflow = InvestigationWorkflow(
        ROOT / "data" / "fixtures", ROOT / "knowledge_base" / "policy", checkpoint_path
    )
    first_workflow.invoke("CASE-AU-001")
    first_workflow.close()

    restarted_workflow = InvestigationWorkflow(
        ROOT / "data" / "fixtures", ROOT / "knowledge_base" / "policy", checkpoint_path
    )
    persisted_state = restarted_workflow.latest_checkpoint("CASE-AU-001")

    assert persisted_state["route"] == "human_review"
    assert persisted_state["draft"].case_id == "CASE-AU-001"


class UnavailablePolicyBackend:
    def retrieve_with_assessment(self, query: str, top_k: int = 2) -> RetrievalResult:
        raise ConnectionError("approved policy service unavailable")


def test_policy_backend_failure_routes_safely_to_insufficient_evidence(tmp_path: Path) -> None:
    workflow = InvestigationWorkflow(
        ROOT / "data" / "fixtures",
        ROOT / "knowledge_base" / "policy",
        tmp_path / "checkpoints.sqlite",
        retriever=UnavailablePolicyBackend(),
    )

    state = workflow.invoke("CASE-AU-001")

    assert state["route"] == "insufficient_evidence"
    assert "Approved-policy retrieval was unavailable" in state["errors"][-1]


class LowConfidencePolicyBackend:
    def retrieve_with_assessment(self, query: str, top_k: int = 2) -> RetrievalResult:
        return RetrievalResult(
            citations=[],
            assessment=RetrievalAssessment(
                top_keyword_score=0,
                relevant_citation_count=0,
                confidence=0.3,
                confidence_band=ConfidenceBand.LOW,
                rationale=["No relevant policy."],
            ),
        )


def test_weak_retrieval_is_stopped_before_generation(tmp_path: Path) -> None:
    workflow = InvestigationWorkflow(
        ROOT / "data" / "fixtures",
        ROOT / "knowledge_base" / "policy",
        tmp_path / "checkpoints.sqlite",
        retriever=LowConfidencePolicyBackend(),
    )

    state = workflow.invoke("CASE-AU-001")

    assert state["route"] == "insufficient_evidence"
    assert state["answerability_gate"].passed is False
    assert state.get("draft") is None
