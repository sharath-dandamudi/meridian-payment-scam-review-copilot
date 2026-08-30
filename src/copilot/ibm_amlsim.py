"""Reproducible adapter for the public IBM AMLSim synthetic transaction sample.

The source dataset is not Australian banking data and is never presented as such.
It is used only to broaden synthetic pattern-testing outside the committed demo fixtures.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

REQUIRED_COLUMNS = {
    "TXN_ID",
    "ACCOUNT_ID",
    "COUNTER_PARTY_ACCOUNT_NUM",
    "TXN_SOURCE_TYPE_CODE",
    "TXN_AMOUNT_ORIG",
    "start",
}
INBOUND_SOURCES = {"CREDIT", "DEPOSIT"}


def build_preview(source_csv: Path, output_path: Path, limit: int = 100) -> int:
    """Convert a bounded CSV sample into a transparent, non-production preview."""
    with source_csv.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None or not REQUIRED_COLUMNS.issubset(reader.fieldnames):
            raise ValueError(
                "Source file does not match the expected IBM AMLSim transaction schema."
            )
        transactions: list[dict[str, Any]] = []
        for row in reader:
            if len(transactions) >= limit:
                break
            source_type = row["TXN_SOURCE_TYPE_CODE"].upper()
            transactions.append(
                {
                    "transaction_id": f"IBMSIM-{row['TXN_ID']}",
                    "account_id": f"IBMSIM-{row['ACCOUNT_ID']}",
                    "counterparty_reference": f"IBMSIM-{row['COUNTER_PARTY_ACCOUNT_NUM']}",
                    "direction": "inbound" if source_type in INBOUND_SOURCES else "outbound",
                    "amount": float(row["TXN_AMOUNT_ORIG"]),
                    "source_type": source_type,
                    "simulation_day": int(row["start"]),
                }
            )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "source": "IBM AMLSim public synthetic sample",
                "warning": "Not Australian banking data; identifiers are synthetic simulation IDs.",
                "transactions": transactions,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return len(transactions)
