from pathlib import Path

from copilot.case_store import CaseStore
from copilot.conversation import respond_to_case_question
from copilot.workflow import InvestigationWorkflow

ROOT = Path(__file__).resolve().parents[1]


def test_case_conversation_answers_with_citations_and_persists_history(tmp_path: Path) -> None:
    workflow = InvestigationWorkflow(
        ROOT / "data" / "fixtures",
        ROOT / "knowledge_base" / "policy",
        tmp_path / "checkpoints.sqlite",
    )
    state = workflow.invoke("CASE-AU-001")
    store = CaseStore(tmp_path / "cases.sqlite")
    query = "Which policy applies to this payment? " + " ".join(state["draft"].observed_signals)
    retrieval = workflow.retriever.retrieve_with_assessment(query, 4)

    response = respond_to_case_question(
        "CASE-AU-001",
        "Which policy citations apply to this payment?",
        state["draft"],
        retrieval,
        store,
    )

    assert response.route == "answer"
    assert response.citations
    assert len(response.history) == 1


def test_case_conversation_refuses_consequential_action(tmp_path: Path) -> None:
    workflow = InvestigationWorkflow(
        ROOT / "data" / "fixtures",
        ROOT / "knowledge_base" / "policy",
        tmp_path / "checkpoints.sqlite",
    )
    state = workflow.invoke("CASE-AU-001")
    store = CaseStore(tmp_path / "cases.sqlite")
    retrieval = workflow.retriever.retrieve_with_assessment("policy context", 4)

    response = respond_to_case_question(
        "CASE-AU-001", "Please freeze account now", state["draft"], retrieval, store
    )

    assert response.route == "refuse"
