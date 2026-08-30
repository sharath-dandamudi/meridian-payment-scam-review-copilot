from pathlib import Path

from copilot.evaluation import evaluate_golden_cases
from copilot.workflow import InvestigationWorkflow

ROOT = Path(__file__).resolve().parents[1]


def test_golden_cases_pass_as_a_release_gate() -> None:
    workflow = InvestigationWorkflow(ROOT / "data" / "fixtures", ROOT / "knowledge_base" / "policy")

    report = evaluate_golden_cases(workflow, ROOT / "evals" / "golden" / "cases.json")

    assert report.passed
    assert report.pass_rate == 1.0
    assert len(report.cases) == 20
    assert report.summary["required_evidence_coverage"] == 1.0
    assert report.summary["required_citation_coverage"] == 1.0
    assert report.summary["policy_recall_at_4"] == 1.0
    assert report.summary["policy_precision_at_4_lower_bound"] > 0
