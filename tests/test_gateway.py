from pathlib import Path

import pytest

from copilot.errors import DataNotFoundError
from copilot.mcp_gateway import FraudDataGateway

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "fixtures"


def test_gateway_reads_alert_and_related_evidence() -> None:
    gateway = FraudDataGateway(FIXTURES)

    alert = gateway.get_alert("CASE-AU-001")
    account = gateway.get_account_profile(alert.account_id)
    transactions = gateway.get_recent_transactions(alert.account_id)

    assert alert.transaction_id == "TX-1005"
    assert account.usual_outbound_payment_max_aud == 3500.0
    assert any(transaction.transaction_id == alert.transaction_id for transaction in transactions)


def test_gateway_lists_full_synthetic_demo_queue() -> None:
    alerts = FraudDataGateway(FIXTURES).list_alerts()

    assert len(alerts) == 20
    assert alerts[0].case_id == "CASE-AU-001"
    assert alerts[-1].case_id == "CASE-AU-020"


def test_gateway_rejects_unknown_case() -> None:
    gateway = FraudDataGateway(FIXTURES)

    with pytest.raises(DataNotFoundError):
        gateway.get_alert("CASE-DOES-NOT-EXIST")
