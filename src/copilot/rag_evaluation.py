"""Deterministic RAG checks for approved-policy retrieval.

These are deliberately separate from answer quality.  They establish whether the
retriever found the policy a reviewer would expect before an LLM sees any context.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from copilot.retrieval import PolicyRetriever


@dataclass(frozen=True)
class RAGCaseEvaluation:
    query_id: str
    passed: bool
    failures: list[str]


@dataclass(frozen=True)
class RAGEvaluationReport:
    cases: list[RAGCaseEvaluation]

    @property
    def pass_rate(self) -> float:
        return sum(case.passed for case in self.cases) / len(self.cases) if self.cases else 0.0

    @property
    def passed(self) -> bool:
        return all(case.passed for case in self.cases)


def evaluate_policy_retrieval(retriever: PolicyRetriever, cases_path: Path) -> RAGEvaluationReport:
    evaluations: list[RAGCaseEvaluation] = []
    for expected in json.loads(cases_path.read_text(encoding="utf-8")):
        result = retriever.retrieve_with_assessment(expected["query"])
        found_policy_ids = {citation.policy_id for citation in result.citations}
        failures: list[str] = []
        if not set(expected["required_policy_ids"]).issubset(found_policy_ids):
            failures.append("Expected policy was not retrieved.")
        if result.assessment.confidence < expected["minimum_confidence"]:
            failures.append("Retrieval confidence was below the expected floor.")
        evaluations.append(RAGCaseEvaluation(expected["query_id"], not failures, failures))
    return RAGEvaluationReport(evaluations)
