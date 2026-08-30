from copilot.intake import classify_intent
from copilot.models import IntakeIntent


def test_investigation_request_routes_only_with_a_case_id() -> None:
    decision = classify_intent("Investigate alert CASE-AU-001")

    assert decision.intent == IntakeIntent.INVESTIGATE_PAYMENT_ALERT
    assert decision.response_mode == "route"
    assert decision.case_id == "CASE-AU-001"


def test_missing_case_id_requires_clarification() -> None:
    decision = classify_intent("Please investigate this alert")

    assert decision.response_mode == "clarify"
    assert decision.missing_fields == ["case_id"]


def test_prohibited_action_is_refused() -> None:
    decision = classify_intent("Freeze account CASE-AU-001")

    assert decision.intent == IntakeIntent.UNSAFE_OR_PROHIBITED
    assert decision.response_mode == "refuse"
