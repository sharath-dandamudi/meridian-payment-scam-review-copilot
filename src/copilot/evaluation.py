"""Offline golden-case evaluation for deterministic release gating."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from copilot.workflow import InvestigationWorkflow


@dataclass(frozen=True)
class CaseEvaluation:
    case_id: str
    passed: bool
    failures: list[str]
    expected_policy_ids: list[str]
    retrieved_policy_ids: list[str]


@dataclass(frozen=True)
class EvaluationReport:
    cases: list[CaseEvaluation]

    @property
    def pass_rate(self) -> float:
        if not self.cases:
            return 0.0
        return sum(case.passed for case in self.cases) / len(self.cases)

    @property
    def passed(self) -> bool:
        return all(case.passed for case in self.cases)

    @property
    def summary(self) -> dict[str, int | float]:
        """Release-gate measures that can be compared across experiments."""
        total = len(self.cases)
        passed = sum(case.passed for case in self.cases)
        return {
            "case_count": total,
            "passed_count": passed,
            "pass_rate": self.pass_rate,
            "route_and_recommendation_accuracy": self.pass_rate,
            "required_evidence_coverage": self._coverage("Missing required evidence"),
            "required_citation_coverage": self._coverage("Missing required policy citations"),
            "gate_pass_rate": self._coverage("Safety or quality gates failed"),
            "policy_precision_at_4_lower_bound": self._policy_precision(),
            "policy_recall_at_4": self._policy_recall(),
        }

    def _policy_precision(self) -> float:
        retrieved = [policy_id for case in self.cases for policy_id in case.retrieved_policy_ids]
        matched = sum(
            policy_id in case.expected_policy_ids
            for case in self.cases
            for policy_id in case.retrieved_policy_ids
        )
        return matched / len(retrieved) if retrieved else 0.0

    def _policy_recall(self) -> float:
        expected = [policy_id for case in self.cases for policy_id in case.expected_policy_ids]
        matched = sum(
            policy_id in case.retrieved_policy_ids
            for case in self.cases
            for policy_id in case.expected_policy_ids
        )
        return matched / len(expected) if expected else 0.0

    def _coverage(self, failure_prefix: str) -> float:
        if not self.cases:
            return 0.0
        successful = sum(
            not any(failure.startswith(failure_prefix) for failure in case.failures)
            for case in self.cases
        )
        return successful / len(self.cases)


def evaluate_golden_cases(
    workflow: InvestigationWorkflow,
    golden_cases_path: Path,
    partition: str | None = None,
) -> EvaluationReport:
    """Verify routes, recommendations, evidence IDs, citations, and gates."""
    cases = json.loads(golden_cases_path.read_text(encoding="utf-8"))
    evaluations: list[CaseEvaluation] = []
    for expected in cases:
        if partition and expected["partition"] != partition:
            continue
        state = workflow.invoke(expected["case_id"], record_metrics=False)
        failures: list[str] = []
        retrieved_policy_ids: list[str] = []
        if state.get("route") != expected["expected_route"]:
            failures.append(
                f"Expected route {expected['expected_route']}, received {state.get('route')}."
            )
        draft = state.get("draft")
        if draft is None:
            failures.append("No investigation draft was produced.")
        else:
            if draft.recommendation.value != expected["expected_recommendation"]:
                failures.append("Recommendation did not match expected outcome.")
            missing_evidence = set(expected["required_evidence_ids"]) - set(draft.evidence_ids)
            if missing_evidence:
                failures.append(f"Missing required evidence: {sorted(missing_evidence)}.")
            found_policy_ids = {citation.policy_id for citation in draft.policy_citations}
            retrieved_policy_ids = sorted(found_policy_ids)
            missing_policy = set(expected["required_policy_ids"]) - found_policy_ids
            if missing_policy:
                failures.append(f"Missing required policy citations: {sorted(missing_policy)}.")
        failed_gates = [gate.gate_name for gate in state.get("gate_results", []) if not gate.passed]
        if failed_gates:
            failures.append(f"Safety or quality gates failed: {failed_gates}.")
        evaluations.append(
            CaseEvaluation(
                case_id=expected["case_id"],
                passed=not failures,
                failures=failures,
                expected_policy_ids=expected["required_policy_ids"],
                retrieved_policy_ids=retrieved_policy_ids,
            )
        )
    return EvaluationReport(cases=evaluations)
