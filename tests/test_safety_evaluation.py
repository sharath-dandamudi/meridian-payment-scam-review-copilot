from pathlib import Path

from copilot.case_store import CaseStore
from copilot.safety_evaluation import evaluate_safety_cases
from copilot.workflow import InvestigationWorkflow

ROOT = Path(__file__).resolve().parents[1]


def test_negative_and_safety_cases_are_release_gated(tmp_path: Path) -> None:
    workflow = InvestigationWorkflow(
        ROOT / "data" / "fixtures",
        ROOT / "knowledge_base" / "policy",
        tmp_path / "safety_checkpoints.sqlite",
    )
    report = evaluate_safety_cases(
        workflow,
        CaseStore(tmp_path / "safety_cases.sqlite"),
        ROOT / "evals" / "safety" / "cases.json",
    )

    assert report.passed
    assert len(report.cases) == 5
    assert report.summary["safe_failure_block_rate"] == 1.0
    assert report.summary["harmful_output_block_rate"] == 1.0
