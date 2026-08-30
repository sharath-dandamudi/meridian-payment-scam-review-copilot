"""Offline behavioural evaluation for bounded analyst conversation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from copilot.case_store import CaseStore
from copilot.conversation import respond_to_case_question
from copilot.workflow import InvestigationWorkflow


@dataclass(frozen=True)
class ConversationCaseEvaluation:
    case_id: str
    question: str
    passed: bool
    failures: list[str]


@dataclass(frozen=True)
class ConversationEvaluationReport:
    cases: list[ConversationCaseEvaluation]

    @property
    def pass_rate(self) -> float:
        return sum(case.passed for case in self.cases) / len(self.cases) if self.cases else 0.0

    @property
    def passed(self) -> bool:
        return all(case.passed for case in self.cases)


def evaluate_conversations(
    workflow: InvestigationWorkflow, case_store: CaseStore, cases_path: Path
) -> ConversationEvaluationReport:
    results: list[ConversationCaseEvaluation] = []
    for expected in json.loads(cases_path.read_text(encoding="utf-8")):
        state = workflow.invoke(expected["case_id"], record_metrics=False)
        draft = state.get("draft")
        failures: list[str] = []
        if draft is None:
            failures.append("No draft was available for conversation evaluation.")
            results.append(
                ConversationCaseEvaluation(
                    expected["case_id"], expected["question"], False, failures
                )
            )
            continue
        retrieval_query = " ".join([expected["question"], *draft.observed_signals])
        retrieval = workflow.retriever.retrieve_with_assessment(retrieval_query, top_k=4)
        response = respond_to_case_question(
            expected["case_id"], expected["question"], draft, retrieval, case_store
        )
        if response.route != expected["expected_route"]:
            failures.append(f"Expected {expected['expected_route']}, received {response.route}.")
        if expected.get("requires_citations") and not response.citations:
            failures.append("Expected approved-policy citations in the answer.")
        results.append(
            ConversationCaseEvaluation(
                expected["case_id"], expected["question"], not failures, failures
            )
        )
    return ConversationEvaluationReport(results)
