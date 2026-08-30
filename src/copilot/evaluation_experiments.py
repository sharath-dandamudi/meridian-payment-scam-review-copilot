"""Versioned local snapshots for repeatable offline-evaluation comparisons."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EvaluationSnapshot:
    metrics: dict[str, float]


def snapshot_from_reports(
    golden: Any, rag: Any, conversation: Any, safety: Any
) -> EvaluationSnapshot:
    """Flatten release measures into stable, comparable metric keys."""
    golden_summary = golden.summary
    safety_summary = safety.summary
    return EvaluationSnapshot(
        {
            "workflow.pass_rate": golden.pass_rate,
            "workflow.required_evidence_coverage": golden_summary["required_evidence_coverage"],
            "workflow.required_citation_coverage": golden_summary["required_citation_coverage"],
            "workflow.gate_pass_rate": golden_summary["gate_pass_rate"],
            "rag.pass_rate": rag.pass_rate,
            "rag.policy_precision_at_4": golden_summary["policy_precision_at_4_lower_bound"],
            "rag.policy_recall_at_4": golden_summary["policy_recall_at_4"],
            "conversation.pass_rate": conversation.pass_rate,
            "safety.pass_rate": safety.pass_rate,
            "safety.safe_failure_block_rate": safety_summary["safe_failure_block_rate"],
            "safety.harmful_output_block_rate": safety_summary["harmful_output_block_rate"],
        }
    )


class EvaluationExperimentStore:
    """Persist approved offline baselines without storing prompts, PII or model output."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save_baseline(
        self, name: str, snapshot: EvaluationSnapshot, metadata: dict[str, str] | None = None
    ) -> dict[str, object]:
        safe_name = self._validate_name(name)
        baselines = self._read()
        record: dict[str, object] = {
            "name": safe_name,
            "created_at": datetime.now(UTC).isoformat(),
            "metrics": snapshot.metrics,
            "metadata": metadata or {},
        }
        baselines[safe_name] = record
        self.path.write_text(json.dumps(baselines, indent=2, sort_keys=True), encoding="utf-8")
        return record

    def compare(self, snapshot: EvaluationSnapshot) -> list[dict[str, object]]:
        comparisons: list[dict[str, object]] = []
        for name, record in self._read().items():
            baseline_metrics = record.get("metrics", {})
            if not isinstance(baseline_metrics, dict):
                continue
            deltas = []
            for metric, current_value in snapshot.metrics.items():
                baseline_value = baseline_metrics.get(metric)
                if not isinstance(baseline_value, (int, float)):
                    continue
                delta = current_value - float(baseline_value)
                status = "regression" if delta < 0 else "unchanged" if delta == 0 else "improved"
                deltas.append(
                    {
                        "metric": metric,
                        "baseline": float(baseline_value),
                        "current": current_value,
                        "delta": delta,
                        "status": status,
                    }
                )
            comparisons.append(
                {
                    "name": name,
                    "created_at": record.get("created_at"),
                    "metadata": record.get("metadata", {}),
                    "has_regression": any(item["status"] == "regression" for item in deltas),
                    "metrics": deltas,
                }
            )
        return comparisons

    def _read(self) -> dict[str, dict[str, object]]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _validate_name(name: str) -> str:
        candidate = name.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", candidate):
            raise ValueError(
                "Baseline name must use 1-64 lowercase letters, numbers, dots, hyphens or "
                "underscores."
            )
        return candidate
