"""Read-only repositories over committed synthetic fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from copilot.errors import DataNotFoundError
from copilot.models import AccountProfile, Alert, Transaction

FixtureModel = TypeVar("FixtureModel", bound=BaseModel)


class SyntheticFraudRepository:
    """A safe local stand-in for governed banking-data services."""

    def __init__(self, fixtures_dir: Path) -> None:
        self._fixtures_dir = fixtures_dir
        self._alerts = self._load("cases.json", Alert, "case_id")
        self._accounts = self._load("accounts.json", AccountProfile, "account_id")
        transactions = self._load_list("transactions.json", Transaction)
        self._transactions = {
            transaction.transaction_id: transaction for transaction in transactions
        }
        self._transactions_by_account: dict[str, list[Transaction]] = {}
        for transaction in transactions:
            self._transactions_by_account.setdefault(transaction.account_id, []).append(transaction)
        for account_transactions in self._transactions_by_account.values():
            account_transactions.sort(key=lambda transaction: transaction.occurred_at)

    def _load(
        self,
        filename: str,
        model_type: type[FixtureModel],
        key: str,
    ) -> dict[str, FixtureModel]:
        return {getattr(item, key): item for item in self._load_list(filename, model_type)}

    def _load_list(
        self,
        filename: str,
        model_type: type[FixtureModel],
    ) -> list[FixtureModel]:
        raw = json.loads((self._fixtures_dir / filename).read_text(encoding="utf-8"))
        return [model_type.model_validate(item) for item in raw]

    def get_alert(self, case_id: str) -> Alert:
        alert = self._alerts.get(case_id)
        if not isinstance(alert, Alert):
            raise DataNotFoundError(f"No alert exists for case_id={case_id}")
        return alert

    def list_alerts(self) -> list[Alert]:
        """Return synthetic alert queue entries in a stable demo order."""
        # Control-test fixtures remain directly addressable but never appear in the
        # normal analyst queue alongside realistic end-to-end cases.
        return sorted(
            (alert for alert in self._alerts.values() if alert.case_id.startswith("CASE-AU-")),
            key=lambda alert: alert.case_id,
        )

    def get_account_profile(self, account_id: str) -> AccountProfile:
        profile = self._accounts.get(account_id)
        if not isinstance(profile, AccountProfile):
            raise DataNotFoundError(f"No account profile exists for account_id={account_id}")
        return profile

    def get_transaction(self, transaction_id: str) -> Transaction:
        transaction = self._transactions.get(transaction_id)
        if transaction is None:
            raise DataNotFoundError(f"No transaction exists for transaction_id={transaction_id}")
        return transaction

    def get_recent_transactions(self, account_id: str, limit: int = 20) -> list[Transaction]:
        if account_id not in self._transactions_by_account:
            raise DataNotFoundError(f"No transactions exist for account_id={account_id}")
        return self._transactions_by_account[account_id][-limit:]
