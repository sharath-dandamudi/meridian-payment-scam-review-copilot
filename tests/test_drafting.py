from pathlib import Path

from copilot.drafting import DraftGenerator
from copilot.models import InvestigationDraft
from copilot.workflow import InvestigationWorkflow

ROOT = Path(__file__).resolve().parents[1]


class FailingDraftGenerator:
    def generate(self, baseline: InvestigationDraft) -> InvestigationDraft:
        raise TimeoutError("provider timed out")


class HallucinatingDraftGenerator:
    def generate(self, baseline: InvestigationDraft) -> InvestigationDraft:
        return baseline.model_copy(
            update={"summary": "The customer confirmed fraud and should freeze account 999999."}
        )


def test_model_failure_keeps_deterministic_draft_and_human_gate(tmp_path: Path) -> None:
    generator: DraftGenerator = FailingDraftGenerator()
    workflow = InvestigationWorkflow(
        ROOT / "data" / "fixtures",
        ROOT / "knowledge_base" / "policy",
        tmp_path / "checkpoints.sqlite",
        generator,
    )

    state = workflow.invoke("CASE-AU-001")

    assert state["route"] == "human_review"
    assert "deterministic fallback" in state["draft"].limitations[-1]
    assert state["errors"][0].startswith("Model fallback:")


def test_ungrounded_generated_summary_is_replaced_by_deterministic_summary(tmp_path: Path) -> None:
    generator: DraftGenerator = HallucinatingDraftGenerator()
    workflow = InvestigationWorkflow(
        ROOT / "data" / "fixtures",
        ROOT / "knowledge_base" / "policy",
        tmp_path / "checkpoints.sqlite",
        generator,
    )

    state = workflow.invoke("CASE-AU-001")

    assert state["generation_gate"].passed is False
    assert "deterministic summary was used" in state["draft"].limitations[-1]
    assert "Generation grounding fallback:" in state["errors"][-1]
