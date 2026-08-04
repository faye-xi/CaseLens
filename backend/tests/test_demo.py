from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from test_application import SequenceClock

from caselens.api.app import create_app
from caselens.demo import create_demo_application

CREATED_AT = datetime(2026, 8, 4, 13, 0, tzinfo=UTC)


def test_demo_api_runs_verified_replay_with_model_and_tool_traces(tmp_path) -> None:
    clock = SequenceClock(
        CREATED_AT,
        CREATED_AT + timedelta(minutes=5),
        CREATED_AT + timedelta(minutes=10),
        CREATED_AT + timedelta(minutes=11),
        CREATED_AT + timedelta(minutes=12),
    )
    application = create_demo_application(tmp_path / "demo.db", clock=clock)

    with TestClient(create_app(application)) as client:
        cases = client.get("/api/v1/cases").json()
        started = client.post(
            "/api/v1/cases/CASE-DEMO-001/reviews",
            json={"review_id": "review-demo-1", "workflow_id": "workflow-demo-1"},
        )
        approved = client.post(
            "/api/v1/workflows/workflow-demo-1/approval",
            json={"decision": "approved", "decided_by": "demo-reviewer"},
        )
        first_execution = client.post("/api/v1/workflows/workflow-demo-1/execute")
        replayed_execution = client.post("/api/v1/workflows/workflow-demo-1/execute")
        verified = client.post("/api/v1/workflows/workflow-demo-1/verify")
        replay = client.get("/api/v1/workflows/workflow-demo-1/replay")

    assert [case["case_id"] for case in cases] == ["CASE-DEMO-001"]
    assert started.status_code == 201
    assert approved.json()["status"] == "ready_to_execute"
    assert first_execution.json()["action_receipt"]["replayed"] is False
    assert replayed_execution.json()["action_receipt"]["replayed"] is True
    assert verified.json()["status"] == "completed_verified"
    assert (
        replay.json()["review"]["result"]["decision_packet"]["recommendation"]
        == "approve_refund"
    )
    assert replay.json()["resolution"]["status"] == "completed_verified"
    assert replay.json()["resolution"]["action_receipt"]["replayed"] is True
    assert len(replay.json()["trace"]["model_traces"]) == 3
    assert replay.json()["trace"]["model_traces"][-1]["request_id"] == (
        "review-demo-1-draft"
    )
    assert replay.json()["trace"]["tool_traces"] == [
        {
            "call_id": "call-payment",
            "tool_name": "get_payment",
            "arguments_json": '{"payment_id":"payment-demo-1"}',
            "started_at": replay.json()["trace"]["tool_traces"][0]["started_at"],
            "completed_at": replay.json()["trace"]["tool_traces"][0]["completed_at"],
            "duration_ms": replay.json()["trace"]["tool_traces"][0]["duration_ms"],
            "status": "succeeded",
            "error_code": None,
        }
    ]
