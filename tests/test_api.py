from fastapi.testclient import TestClient
from pydantic import SecretStr

from copilot.api import create_app
from copilot.settings import Settings


def test_api_runs_an_investigation_and_exposes_golden_evaluation() -> None:
    client = TestClient(create_app())

    investigation = client.post("/cases/CASE-AU-001/investigate")
    golden = client.get("/evals/golden")
    conversation_evaluation = client.get("/evals/conversation")
    safety_evaluation = client.get("/evals/safety")
    readiness = client.get("/ready")

    assert investigation.status_code == 200
    assert investigation.json()["route"] == "human_review"
    assert len(client.get("/cases").json()) == 20
    assert golden.status_code == 200
    assert golden.json()["passed"] is True
    assert conversation_evaluation.status_code == 200
    assert conversation_evaluation.json()["passed"] is True
    assert safety_evaluation.status_code == 200
    assert safety_evaluation.json()["summary"]["harmful_output_block_rate"] == 1.0
    assert readiness.status_code == 200


def test_api_streams_real_investigation_stages_and_final_result() -> None:
    client = TestClient(create_app())

    response = client.post("/cases/CASE-AU-001/investigate/stream")

    assert response.status_code == 200
    assert '"node": "collect_evidence"' in response.text
    assert '"node": "retrieve_policy"' in response.text
    assert '"node": "run_gates"' in response.text
    assert '"type": "result"' in response.text


def test_api_supports_case_bound_follow_up_conversation() -> None:
    client = TestClient(create_app())
    client.post("/cases/CASE-AU-001/investigate")

    response = client.post(
        "/cases/CASE-AU-001/chat",
        json={"question": "Which policy applies to this payment?"},
    )

    assert response.status_code == 200
    assert response.json()["route"] == "answer"
    assert response.json()["citations"]


def test_api_records_only_a_human_supplied_review() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/cases/CASE-AU-001/review",
        json={
            "case_id": "CASE-AU-001",
            "decision": "escalated",
            "rationale": "Synthetic scenario requires an authorised analyst escalation.",
            "decided_at": "2026-08-28T12:00:00+10:00",
        },
    )

    assert response.status_code == 200
    assert client.get("/cases/CASE-AU-001/review").json()["decision"] == "escalated"


def test_api_roles_request_ids_and_rate_limit() -> None:
    settings = Settings(
        auth_enabled=True,
        analyst_api_key=SecretStr("analyst-test-key"),
        operations_api_key=SecretStr("operations-test-key"),
        rate_limit_per_minute=2,
    )
    client = TestClient(create_app(settings))

    denied = client.get("/cases")
    analyst = client.get("/cases", headers={"X-API-Key": "analyst-test-key"})
    operations = client.get("/metrics", headers={"X-API-Key": "operations-test-key"})
    analyst_operations = client.get("/metrics", headers={"X-API-Key": "analyst-test-key"})
    limited = client.get("/cases", headers={"X-API-Key": "analyst-test-key"})

    assert denied.status_code == 403
    assert analyst.status_code == 200
    assert analyst.headers["X-Request-ID"]
    assert operations.status_code == 200
    assert analyst_operations.status_code == 403
    assert limited.status_code == 429
