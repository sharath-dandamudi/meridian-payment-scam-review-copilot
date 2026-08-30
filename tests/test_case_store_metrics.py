from datetime import datetime
from pathlib import Path

from copilot.case_store import CaseStore
from copilot.models import AnalystDecision
from copilot.workflow import InvestigationWorkflow

ROOT = Path(__file__).resolve().parents[1]


def test_escalation_agreement_metrics_use_final_analyst_outcome(tmp_path: Path) -> None:
    workflow = InvestigationWorkflow(
        ROOT / "data" / "fixtures",
        ROOT / "knowledge_base" / "policy",
        tmp_path / "checkpoints.sqlite",
    )
    state = workflow.invoke("CASE-AU-001")
    store = CaseStore(tmp_path / "cases.sqlite")
    store.record_investigation("CASE-AU-001", "human_review", state["draft"], None)
    store.record_analyst_decision(
        AnalystDecision(
            case_id="CASE-AU-001",
            decision="escalated",
            rationale="Synthetic high-risk scenario requires escalation.",
            decided_at=datetime.now().astimezone(),
        )
    )

    summary = store.escalation_agreement_summary()

    assert summary["labelled_case_count"] == 1
    assert summary["escalation_precision"] == 1.0
    assert summary["escalation_recall"] == 1.0
