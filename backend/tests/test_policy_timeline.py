from datetime import datetime

import pytest
from pydantic import ValidationError

from caselens.domain.models import Case
from caselens.domain.policy import (
    PolicyTimeline,
    PolicyVersion,
    PolicyVersionNotFoundError,
)


def make_timeline() -> PolicyTimeline:
    return PolicyTimeline.model_validate(
        {
            "policy_id": "refund-policy",
            "versions": [
                {
                    "policy_id": "refund-policy",
                    "version": "v2",
                    "effective_from": "2026-07-01T00:00:00+08:00",
                    "effective_to": None,
                },
                {
                    "policy_id": "refund-policy",
                    "version": "v1",
                    "effective_from": "2026-01-01T00:00:00+08:00",
                    "effective_to": "2026-07-01T00:00:00+08:00",
                },
            ],
        }
    )


@pytest.mark.parametrize(
    ("occurred_at", "expected_version"),
    [
        ("2026-06-30T23:59:59+08:00", "v1"),
        ("2026-07-01T00:00:00+08:00", "v2"),
        ("2026-08-01T12:00:00+08:00", "v2"),
        ("2026-06-30T16:00:00+00:00", "v2"),
    ],
)
def test_selects_version_effective_when_dispute_occurred(
    occurred_at: str,
    expected_version: str,
) -> None:
    selected = make_timeline().version_at(datetime.fromisoformat(occurred_at))

    assert selected.version == expected_version


def test_selects_policy_from_case_occurrence_time() -> None:
    case = Case.model_validate(
        {
            "case_id": "CASE-POLICY-001",
            "case_type": "refund_not_received",
            "occurred_at": "2026-06-15T10:00:00+08:00",
            "customer_statement": "I did not receive my refund",
            "claim_amount": 50,
            "currency": "CNY",
            "order_id": "ORDER-POLICY-001",
            "payment_id": "PAYMENT-POLICY-001",
            "refund_id": "REFUND-POLICY-001",
        }
    )

    selected = make_timeline().version_at(case.occurred_at)

    assert selected.version == "v1"


@pytest.mark.parametrize(
    ("effective_from", "effective_to"),
    [
        ("2026-07-01T00:00:00+08:00", "2026-07-01T00:00:00+08:00"),
        ("2026-07-02T00:00:00+08:00", "2026-07-01T00:00:00+08:00"),
    ],
)
def test_rejects_policy_version_with_non_positive_effective_window(
    effective_from: str,
    effective_to: str,
) -> None:
    with pytest.raises(ValidationError, match="after effective_from"):
        PolicyVersion(
            policy_id="refund-policy",
            version="invalid-window",
            effective_from=effective_from,
            effective_to=effective_to,
        )


@pytest.mark.parametrize("field", ["policy_id", "version"])
def test_rejects_blank_policy_version_identifiers(field: str) -> None:
    values = {
        "policy_id": "refund-policy",
        "version": "v1",
        "effective_from": "2026-01-01T00:00:00+08:00",
    }
    values[field] = "   "

    with pytest.raises(ValidationError):
        PolicyVersion.model_validate(values)


@pytest.mark.parametrize("field", ["effective_from", "effective_to"])
def test_rejects_timezone_naive_policy_effective_time(field: str) -> None:
    values = {
        "policy_id": "refund-policy",
        "version": "v1",
        "effective_from": "2026-01-01T00:00:00+08:00",
        "effective_to": "2026-07-01T00:00:00+08:00",
    }
    values[field] = "2026-01-01T00:00:00"

    with pytest.raises(ValidationError):
        PolicyVersion.model_validate(values)


def test_rejects_unknown_policy_version_fields() -> None:
    with pytest.raises(ValidationError):
        PolicyVersion.model_validate(
            {
                "policy_id": "refund-policy",
                "version": "v1",
                "effective_from": "2026-01-01T00:00:00+08:00",
                "published_by": "policy-team",
            }
        )


def test_policy_version_is_immutable() -> None:
    version = PolicyVersion(
        policy_id="refund-policy",
        version="v1",
        effective_from="2026-01-01T00:00:00+08:00",
    )

    with pytest.raises(ValidationError):
        version.version = "changed"


def test_rejects_empty_policy_timeline() -> None:
    with pytest.raises(ValidationError):
        PolicyTimeline(policy_id="refund-policy", versions=())


def test_rejects_version_from_another_policy() -> None:
    with pytest.raises(ValidationError, match="same policy_id"):
        PolicyTimeline(
            policy_id="refund-policy",
            versions=(
                PolicyVersion(
                    policy_id="shipping-policy",
                    version="v1",
                    effective_from="2026-01-01T00:00:00+08:00",
                ),
            ),
        )


def test_rejects_duplicate_version_labels() -> None:
    with pytest.raises(ValidationError, match="Duplicate policy version"):
        PolicyTimeline.model_validate(
            {
                "policy_id": "refund-policy",
                "versions": [
                    {
                        "policy_id": "refund-policy",
                        "version": "v1",
                        "effective_from": "2026-01-01T00:00:00+08:00",
                        "effective_to": "2026-04-01T00:00:00+08:00",
                    },
                    {
                        "policy_id": "refund-policy",
                        "version": "v1",
                        "effective_from": "2026-04-01T00:00:00+08:00",
                        "effective_to": "2026-07-01T00:00:00+08:00",
                    },
                ],
            }
        )


@pytest.mark.parametrize(
    "versions",
    [
        [
            {
                "policy_id": "refund-policy",
                "version": "v1",
                "effective_from": "2026-01-01T00:00:00+08:00",
                "effective_to": "2026-07-01T00:00:00+08:00",
            },
            {
                "policy_id": "refund-policy",
                "version": "v2",
                "effective_from": "2026-06-01T00:00:00+08:00",
                "effective_to": None,
            },
        ],
        [
            {
                "policy_id": "refund-policy",
                "version": "v1",
                "effective_from": "2026-01-01T00:00:00+08:00",
                "effective_to": None,
            },
            {
                "policy_id": "refund-policy",
                "version": "v2",
                "effective_from": "2026-07-01T00:00:00+08:00",
                "effective_to": None,
            },
        ],
    ],
)
def test_rejects_overlapping_policy_versions(
    versions: list[dict[str, object]],
) -> None:
    with pytest.raises(ValidationError, match="overlap"):
        PolicyTimeline.model_validate(
            {
                "policy_id": "refund-policy",
                "versions": versions,
            }
        )


def test_rejects_blank_policy_timeline_id() -> None:
    with pytest.raises(ValidationError):
        PolicyTimeline.model_validate(
            {
                "policy_id": "   ",
                "versions": [
                    {
                        "policy_id": "refund-policy",
                        "version": "v1",
                        "effective_from": "2026-01-01T00:00:00+08:00",
                    }
                ],
            }
        )


def test_rejects_unknown_policy_timeline_fields() -> None:
    with pytest.raises(ValidationError):
        PolicyTimeline.model_validate(
            {
                "policy_id": "refund-policy",
                "versions": [
                    {
                        "policy_id": "refund-policy",
                        "version": "v1",
                        "effective_from": "2026-01-01T00:00:00+08:00",
                    }
                ],
                "active": True,
            }
        )


def test_policy_timeline_is_immutable() -> None:
    timeline = make_timeline()

    with pytest.raises(ValidationError):
        timeline.policy_id = "changed-policy"


def test_gap_does_not_fall_back_to_nearest_policy_version() -> None:
    timeline = PolicyTimeline.model_validate(
        {
            "policy_id": "refund-policy",
            "versions": [
                {
                    "policy_id": "refund-policy",
                    "version": "v1",
                    "effective_from": "2026-01-01T00:00:00+08:00",
                    "effective_to": "2026-04-01T00:00:00+08:00",
                },
                {
                    "policy_id": "refund-policy",
                    "version": "v2",
                    "effective_from": "2026-07-01T00:00:00+08:00",
                    "effective_to": None,
                },
            ],
        }
    )
    occurred_at = datetime.fromisoformat("2026-05-01T00:00:00+08:00")

    with pytest.raises(PolicyVersionNotFoundError) as error:
        timeline.version_at(occurred_at)

    assert error.value.policy_id == "refund-policy"
    assert error.value.occurred_at == occurred_at


def test_rejects_timezone_naive_occurrence_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        make_timeline().version_at(datetime.fromisoformat("2026-06-01T00:00:00"))
