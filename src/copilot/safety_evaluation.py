"""Offline negative and safety evaluation for governed Meridian behaviour."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from copilot.case_store import CaseStore
from copilot.conversation import respond_to_case_question
from copilot.guardrails import evaluate_generated_summary
from copilot.workflow import InvestigationWorkflow

SafetyCaseKind = Literal["workflow", "conversation", "generation"]


@dataclass(frozen=True)
class SafetyCaseEvaluation:
    case_id: str
    case_kind: SafetyCaseKind
    passed: bool
    failures: list[str]
    expected_safe_failure: bool
    safely_blocked: bool


@dataclass(frozen=True)
class SafetyEvaluationReport:
    cases: list[SafetyCaseEvaluation]

    @property
    def pass_rate(self) -> float:
        return sum(case.passed for case in self.cases) / len(self.cases) if self.cases else 0.0

    @property
    def passed(self) -> bool:
        return all(case.passed for case in self.cases)

    @property
    def summary(self) -> dict[str, int | float]:
        expected_safe_failures = [case for case in self.cases if case.expected_safe_failure]
        safely_blocked = sum(case.safely_blocked for case in expected_safe_failures)
        return {
            "case_count": len(self.cases),
            "passed_count": sum(case.passed for case in self.cases),
            "pass_rate": self.pass_rate,
            "expected_safe_failure_count": len(expected_safe_failures),
            "safe_failure_block_rate": (
                safely_blocked / len(expected_safe_failures) if expected_safe_failures else 1.0
            ),
            "harmful_output_rate": (
                sum(
                    case.expected_safe_failure and case.case_kind == "generation"
                    for case in self.cases
                )
                / len(self.cases)
                if self.cases
                else 0.0
            ),
            "harmful_output_block_rate": self._harmful_output_block_rate(),
        }

    def _harmful_output_block_rate(self) -> float:
        harmful_cases = [
            case
            for case in self.cases
            if case.expected_safe_failure and case.case_kind == "generation"
        ]
        return (
            sum(case.safely_blocked for case in harmful_cases) / len(harmful_cases)
            if harmful_cases
            else 1.0
        )


def evaluate_safety_cases(
    workflow: InvestigationWorkflow,
    case_store: CaseStore,
    cases_path: Path,
) -> SafetyEvaluationReport:
    """Run pre-labelled unsafe, weak-evidence and harmful-output assertions offline."""
    evaluations: list[SafetyCaseEvaluation] = []
    for expected in json.loads(cases_path.read_text(encoding="utf-8")):
        kind = expected["kind"]
        if kind == "workflow":
            evaluations.append(_evaluate_workflow_case(workflow, expected))
        elif kind == "conversation":
            evaluations.append(_evaluate_conversation_case(workflow, case_store, expected))
        elif kind == "generation":
            evaluations.append(_evaluate_generation_case(workflow, expected))
        else:
            raise ValueError(f"Unknown safety evaluation case kind: {kind}")
    return SafetyEvaluationReport(evaluations)


def _evaluate_workflow_case(
    workflow: InvestigationWorkflow, expected: dict[str, Any]
) -> SafetyCaseEvaluation:
    state = workflow.invoke(
        expected["case_id"],
        record_metrics=False,
        control_mode=expected.get("control_mode"),
    )
    failures: list[str] = []
    if state.get("route") != expected["expected_route"]:
        failures.append(
            f"Expected route {expected['expected_route']}, received {state.get('route')}."
        )
    if expected.get("draft_must_be_absent") and state.get("draft") is not None:
        failures.append("A draft was produced despite the expected safe failure.")
    required_error = expected.get("error_contains")
    errors = " ".join(state.get("errors", []))
    if required_error and required_error.lower() not in errors.lower():
        failures.append(f"Expected safe-failure reason containing: {required_error!r}.")
    expected_gate = expected.get("failed_gate")
    if expected_gate:
        gate = state.get("answerability_gate")
        if gate is None or gate.gate_name != expected_gate or gate.passed:
            failures.append(f"Expected failed {expected_gate} gate.")
    return SafetyCaseEvaluation(
        expected["case_id"], "workflow", not failures, failures, True, not failures
    )


def _evaluate_conversation_case(
    workflow: InvestigationWorkflow, case_store: CaseStore, expected: dict[str, Any]
) -> SafetyCaseEvaluation:
    state = workflow.invoke(expected["case_id"], record_metrics=False)
    draft = state.get("draft")
    failures: list[str] = []
    if draft is None:
        failures.append("No draft was available for the safety conversation test.")
    else:
        retrieval = workflow.retriever.retrieve_with_assessment(expected["question"], top_k=4)
        response = respond_to_case_question(
            expected["case_id"], expected["question"], draft, retrieval, case_store
        )
        if response.route != expected["expected_route"]:
            failures.append(f"Expected {expected['expected_route']}, received {response.route}.")
        required_reply = expected.get("reply_contains")
        if required_reply and required_reply.lower() not in response.reply.lower():
            failures.append(f"Expected reply to contain: {required_reply!r}.")
    return SafetyCaseEvaluation(
        expected["case_id"], "conversation", not failures, failures, True, not failures
    )


def _evaluate_generation_case(
    workflow: InvestigationWorkflow, expected: dict[str, Any]
) -> SafetyCaseEvaluation:
    state = workflow.invoke(expected["case_id"], record_metrics=False)
    draft = state.get("draft")
    failures: list[str] = []
    if draft is None:
        failures.append("No baseline draft was available for generation safety test.")
        safely_blocked = False
    else:
        gate = evaluate_generated_summary(expected["candidate_summary"], draft)
        expected_pass = expected["expected_gate_passed"]
        if gate.passed != expected_pass:
            failures.append(
                f"Expected generation gate passed={expected_pass}, received {gate.passed}."
            )
        required_reason = expected.get("reason_contains")
        if required_reason and required_reason.lower() not in " ".join(gate.reasons).lower():
            failures.append(f"Expected generation gate reason containing: {required_reason!r}.")
        safely_blocked = not gate.passed
    expected_safe_failure = not expected["expected_gate_passed"]
    return SafetyCaseEvaluation(
        expected["case_id"],
        "generation",
        not failures,
        failures,
        expected_safe_failure,
        safely_blocked if expected_safe_failure else not failures,
    )
