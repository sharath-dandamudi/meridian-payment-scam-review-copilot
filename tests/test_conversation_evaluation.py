from pathlib import Path

from copilot.case_store import CaseStore
from copilot.conversation_evaluation import evaluate_conversations
from copilot.workflow import InvestigationWorkflow

ROOT = Path(__file__).resolve().parents[1]


def test_conversation_golden_cases_pass(tmp_path: Path) -> None:
    workflow = InvestigationWorkflow(
        ROOT / "data" / "fixtures",
        ROOT / "knowledge_base" / "policy",
        tmp_path / "checkpoints.sqlite",
    )
    report = evaluate_conversations(
        workflow,
        CaseStore(tmp_path / "cases.sqlite"),
        ROOT / "evals" / "conversation" / "cases.json",
    )

    assert report.passed
    assert len(report.cases) == 6
