"""Local audited case store; the source of truth for human decisions."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from copilot.models import AnalystDecision, InvestigationDraft


class CaseStore:
    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._database_path = database_path
        self._initialise()

    def _initialise(self) -> None:
        with sqlite3.connect(self._database_path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS investigation_runs ("
                "case_id TEXT PRIMARY KEY, route TEXT NOT NULL, draft_json TEXT, "
                "trace_id TEXT, "
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS analyst_decisions ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, "
                "decision TEXT NOT NULL, rationale TEXT NOT NULL, decided_at TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS conversation_turns ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, "
                "question TEXT NOT NULL, reply TEXT NOT NULL, route TEXT NOT NULL, "
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(investigation_runs)").fetchall()
            }
            if "trace_id" not in columns:
                connection.execute("ALTER TABLE investigation_runs ADD COLUMN trace_id TEXT")

    def record_investigation(
        self, case_id: str, route: str, draft: InvestigationDraft | None, trace_id: str | None
    ) -> None:
        draft_json = json.dumps(draft.model_dump(mode="json")) if draft else None
        with sqlite3.connect(self._database_path) as connection:
            connection.execute(
                "INSERT INTO investigation_runs "
                "(case_id, route, draft_json, trace_id) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(case_id) DO UPDATE SET route=excluded.route, "
                "draft_json=excluded.draft_json, trace_id=excluded.trace_id, "
                "created_at=CURRENT_TIMESTAMP",
                (case_id, route, draft_json, trace_id),
            )

    def record_analyst_decision(self, decision: AnalystDecision) -> None:
        with sqlite3.connect(self._database_path) as connection:
            connection.execute(
                "INSERT INTO analyst_decisions (case_id, decision, rationale, decided_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    decision.case_id,
                    decision.decision,
                    decision.rationale,
                    decision.decided_at.isoformat(),
                ),
            )

    def latest_decision(self, case_id: str) -> dict[str, str] | None:
        with sqlite3.connect(self._database_path) as connection:
            row = connection.execute(
                "SELECT decision, rationale, decided_at FROM analyst_decisions "
                "WHERE case_id = ? ORDER BY id DESC LIMIT 1",
                (case_id,),
            ).fetchone()
        return (
            None if row is None else {"decision": row[0], "rationale": row[1], "decided_at": row[2]}
        )

    def trace_id_for_case(self, case_id: str) -> str | None:
        with sqlite3.connect(self._database_path) as connection:
            row = connection.execute(
                "SELECT trace_id FROM investigation_runs WHERE case_id = ?", (case_id,)
            ).fetchone()
        return None if row is None else row[0]

    def decision_counts(self) -> dict[str, int]:
        with sqlite3.connect(self._database_path) as connection:
            rows = connection.execute(
                "SELECT decision, COUNT(*) FROM analyst_decisions GROUP BY decision"
            ).fetchall()
        return {decision: count for decision, count in rows}

    def record_conversation_turn(self, case_id: str, question: str, reply: str, route: str) -> None:
        with sqlite3.connect(self._database_path) as connection:
            connection.execute(
                (
                    "INSERT INTO conversation_turns (case_id, question, reply, route) "
                    "VALUES (?, ?, ?, ?)"
                ),
                (case_id, question, reply, route),
            )

    def recent_conversation(self, case_id: str, limit: int = 6) -> list[dict[str, str]]:
        with sqlite3.connect(self._database_path) as connection:
            rows = connection.execute(
                "SELECT question, reply, route, created_at FROM conversation_turns "
                "WHERE case_id = ? ORDER BY id DESC LIMIT ?",
                (case_id, limit),
            ).fetchall()
        return [
            {"question": row[0], "reply": row[1], "route": row[2], "created_at": row[3]}
            for row in reversed(rows)
        ]

    def online_evaluation_summary(self) -> dict[str, int | float]:
        """Report outcome distribution without equating escalation with draft dissatisfaction."""
        counts = self.decision_counts()
        usefulness_observations = counts.get("approved", 0) + counts.get("edited", 0)
        quality_observations = usefulness_observations + counts.get("more_evidence", 0)
        return {
            "review_count": sum(counts.values()),
            "approved_count": counts.get("approved", 0),
            "edited_count": counts.get("edited", 0),
            "more_evidence_count": counts.get("more_evidence", 0),
            "escalated_count": counts.get("escalated", 0),
            "insufficient_evidence_count": counts.get("insufficient_evidence", 0),
            "draft_usefulness_rate": (
                usefulness_observations / quality_observations if quality_observations else 0.0
            ),
        }

    def escalation_agreement_summary(self) -> dict[str, int | float]:
        """Compare escalation recommendations with final analyst dispositions.

        This is agreement with an analyst escalation decision, not fraud-detection
        precision/recall and is reported only once a case has a final disposition.
        """
        with sqlite3.connect(self._database_path) as connection:
            rows = connection.execute(
                "SELECT investigation_runs.draft_json, analyst_decisions.decision "
                "FROM investigation_runs JOIN analyst_decisions "
                "ON investigation_runs.case_id = analyst_decisions.case_id "
                "WHERE analyst_decisions.id IN "
                "(SELECT MAX(id) FROM analyst_decisions GROUP BY case_id) "
                "AND analyst_decisions.decision IN ('escalated', 'approved', 'edited')"
            ).fetchall()
        true_positive = false_positive = false_negative = true_negative = 0
        for draft_json, decision in rows:
            if draft_json is None:
                continue
            recommendation = json.loads(draft_json)["recommendation"]
            predicted_positive = recommendation == "human_escalation_required"
            actual_positive = decision == "escalated"
            if predicted_positive and actual_positive:
                true_positive += 1
            elif predicted_positive:
                false_positive += 1
            elif actual_positive:
                false_negative += 1
            else:
                true_negative += 1
        precision_denominator = true_positive + false_positive
        recall_denominator = true_positive + false_negative
        return {
            "labelled_case_count": true_positive + false_positive + false_negative + true_negative,
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "true_negative": true_negative,
            "escalation_precision": (
                true_positive / precision_denominator if precision_denominator else 0.0
            ),
            "escalation_recall": (
                true_positive / recall_denominator if recall_denominator else 0.0
            ),
        }
