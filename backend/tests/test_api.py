from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from test_application import _application
from test_resolution_models import make_review

from caselens.api.app import create_app, create_app_from_factory

CREATED_AT = datetime(2026, 8, 4, 13, 0, tzinfo=UTC)


def test_application_factory_is_not_called_until_lifespan_starts(tmp_path) -> None:
    calls = []

    def factory():
        calls.append("created")
        application, _ = _application(tmp_path, make_review(), CREATED_AT)
        return application

    app = create_app_from_factory(factory)

    assert calls == []
    with TestClient(app) as client:
        assert calls == ["created"]
        assert client.get("/api/v1/health").status_code == 200


def test_health_case_reads_and_review_replay_routes(tmp_path) -> None:
    application, _ = _application(tmp_path, make_review(), CREATED_AT)
    with TestClient(create_app(application)) as client:
        assert client.get("/api/v1/health").json() == {"status": "ok"}
        cases = client.get("/api/v1/cases")
        case = client.get("/api/v1/cases/CASE-006")
        started = client.post(
            "/api/v1/cases/CASE-006/reviews",
            json={"review_id": "review-1", "workflow_id": "workflow-1"},
        )
        review = client.get("/api/v1/reviews/review-1")
        workflow = client.get("/api/v1/workflows/workflow-1")
        replay = client.get("/api/v1/workflows/workflow-1/replay")

    assert cases.status_code == 200
    assert [item["case_id"] for item in cases.json()] == ["CASE-006"]
    assert case.status_code == 200
    assert case.json()["case_type"] == "refund_not_received"
    assert started.status_code == 201
    assert started.json()["workflow"]["status"] == "waiting_approval"
    assert review.json()["result"]["decision_packet"]["recommendation"] == (
        "approve_refund"
    )
    assert workflow.json()["review_id"] == "review-1"
    assert replay.json()["case"]["case_id"] == "CASE-006"
    assert replay.json()["review"]["review_id"] == "review-1"
    assert replay.json()["resolution"]["workflow_id"] == "workflow-1"


def test_replayed_review_creation_returns_ok_instead_of_created(tmp_path) -> None:
    application, _ = _application(tmp_path, make_review(), CREATED_AT)
    with TestClient(create_app(application)) as client:
        first = client.post(
            "/api/v1/cases/CASE-006/reviews",
            json={"review_id": "review-1", "workflow_id": "workflow-1"},
        )
        replay = client.post(
            "/api/v1/cases/CASE-006/reviews",
            json={"review_id": "review-1", "workflow_id": "workflow-1"},
        )

    assert first.status_code == 201
    assert first.json()["created"] is True
    assert replay.status_code == 200
    assert replay.json()["created"] is False


def test_approval_execution_and_verification_routes_use_real_workflow(tmp_path) -> None:
    application, _ = _application(
        tmp_path,
        make_review(),
        CREATED_AT,
        CREATED_AT + timedelta(minutes=5),
        CREATED_AT + timedelta(minutes=10),
        CREATED_AT + timedelta(minutes=11),
    )
    with TestClient(create_app(application)) as client:
        client.post(
            "/api/v1/cases/CASE-006/reviews",
            json={"review_id": "review-1", "workflow_id": "workflow-1"},
        )
        approved = client.post(
            "/api/v1/workflows/workflow-1/approval",
            json={"decision": "approved", "decided_by": "reviewer-1"},
        )
        executed = client.post("/api/v1/workflows/workflow-1/execute")
        verified = client.post("/api/v1/workflows/workflow-1/verify")

    assert approved.status_code == 200
    assert approved.json()["status"] == "ready_to_execute"
    assert executed.status_code == 200
    assert executed.json()["status"] == "ready_to_verify"
    assert verified.status_code == 200
    assert verified.json()["status"] == "completed_verified"
    assert verified.json()["verification"]["status"] == "verified"


def test_expected_failures_have_stable_http_mapping(tmp_path) -> None:
    application, _ = _application(
        tmp_path,
        make_review(),
        CREATED_AT,
        CREATED_AT + timedelta(minutes=1),
    )
    with TestClient(create_app(application)) as client:
        missing_case = client.get("/api/v1/cases/CASE-UNKNOWN")
        missing_workflow = client.get("/api/v1/workflows/workflow-unknown")
        malformed = client.post(
            "/api/v1/cases/CASE-006/reviews",
            json={
                "review_id": " ",
                "workflow_id": "workflow-1",
                "unexpected": True,
            },
        )
        client.post(
            "/api/v1/cases/CASE-006/reviews",
            json={"review_id": "review-1", "workflow_id": "workflow-1"},
        )
        illegal = client.post("/api/v1/workflows/workflow-1/execute")

    assert missing_case.status_code == 404
    assert missing_case.json() == {
        "error": {
            "code": "resource_not_found",
            "message": "The requested resource was not found.",
        }
    }
    assert missing_workflow.status_code == 404
    assert missing_workflow.json()["error"]["code"] == "resource_not_found"
    assert malformed.status_code == 422
    assert illegal.status_code == 409
    assert illegal.json()["error"]["code"] == "illegal_transition"
