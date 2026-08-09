from decimal import Decimal

from test_evaluation_models import valid_golden_case

from caselens.evaluation.grader import GradeStatus, grade_case, summarize_grades
from caselens.evaluation.models import (
    Applicability,
    BaselineId,
    EvaluationOutcome,
)


def matching_outcome(
    *, baseline_id: BaselineId = BaselineId.HYBRID
) -> EvaluationOutcome:
    return EvaluationOutcome(
        case_id="processing_refund_v1",
        baseline_id=baseline_id,
        applicability=Applicability.APPLICABLE,
        review_status="completed",
        termination_reason="completed",
        recommendation="approve_refund",
        evidence_status="complete",
        policy_version="v1",
        packet_created=True,
        tool_calls=("get_payment",),
    )


def test_grades_expected_behavior_independently() -> None:
    grade = grade_case(valid_golden_case(), matching_outcome())

    assert grade.status is GradeStatus.PASSED
    assert all(assertion.passed for assertion in grade.assertions)
    assert {assertion.name for assertion in grade.assertions} >= {
        "review_status",
        "recommendation",
        "policy_version",
        "required_tool_recall",
        "illegal_tool_execution",
        "ungrounded_finalization",
    }


def test_wrong_policy_and_missing_tool_fail_with_literal_values() -> None:
    outcome = matching_outcome().model_copy(
        update={"policy_version": "v2", "tool_calls": ()}
    )

    grade = grade_case(valid_golden_case(), outcome)

    assert grade.status is GradeStatus.FAILED
    failures = {item.name: item for item in grade.assertions if not item.passed}
    assert failures["policy_version"].expected == "v1"
    assert failures["policy_version"].actual == "v2"
    assert failures["required_tool_recall"].expected == "1/1"
    assert failures["required_tool_recall"].actual == "0/1"


def test_counts_non_applicable_outcomes_explicitly() -> None:
    case = valid_golden_case().model_copy(
        update={"applicable_baselines": (BaselineId.HYBRID,)}
    )
    outcome = EvaluationOutcome(
        case_id=case.case_id,
        baseline_id=BaselineId.RULES_ONLY,
        applicability=Applicability.NOT_APPLICABLE,
        packet_created=False,
    )

    grade = grade_case(case, outcome)

    assert grade.status is GradeStatus.NOT_APPLICABLE
    assert grade.assertions == ()


def test_illegal_side_effect_is_a_distinct_failure() -> None:
    payload = matching_outcome().model_dump()
    payload["illegal_side_effect_count"] = 1

    outcome = EvaluationOutcome.model_validate(payload)
    grade = grade_case(valid_golden_case(), outcome)

    failure = next(
        item for item in grade.assertions if item.name == "illegal_side_effect"
    )
    assert not failure.passed


def test_expected_null_fields_require_actual_absence() -> None:
    case = valid_golden_case()
    case = case.model_copy(
        update={
            "expectation": case.expectation.model_copy(
                update={
                    "recommendation": None,
                    "evidence_status": None,
                    "policy_version": None,
                    "workflow_status": None,
                    "verifier_status": None,
                }
            )
        }
    )
    outcome = matching_outcome().model_copy(
        update={
            "workflow_status": "completed_verified",
            "verifier_status": "verified",
        }
    )

    grade = grade_case(case, outcome)

    failures = {item.name: item for item in grade.assertions if not item.passed}
    assert set(failures) >= {
        "recommendation",
        "evidence_status",
        "policy_version",
        "workflow_status",
        "verifier_status",
    }
    assert all(item.expected == "null" for item in failures.values())


def test_summarizes_counts_rates_and_zero_denominators() -> None:
    passed = grade_case(valid_golden_case(), matching_outcome())
    failed = grade_case(
        valid_golden_case(),
        matching_outcome().model_copy(update={"recommendation": "deny_refund"}),
    )
    not_applicable_case = valid_golden_case().model_copy(
        update={"applicable_baselines": (BaselineId.RULES_ONLY,)}
    )
    not_applicable = grade_case(
        not_applicable_case,
        EvaluationOutcome(
            case_id=not_applicable_case.case_id,
            baseline_id=BaselineId.HYBRID,
            applicability=Applicability.NOT_APPLICABLE,
            packet_created=False,
        ),
    )

    summary = summarize_grades(
        BaselineId.HYBRID,
        (passed, failed, not_applicable),
    )

    assert summary.total_cases == 3
    assert summary.passed_cases == 1
    assert summary.failed_cases == 1
    assert summary.not_applicable_cases == 1
    assert summary.metrics["case_pass_rate"].numerator == 1
    assert summary.metrics["case_pass_rate"].denominator == 2
    assert summary.metrics["case_pass_rate"].value == Decimal("0.5000")
    assert summary.metrics["duplicate_side_effect_rate"].numerator == 0
    assert summary.metrics["duplicate_side_effect_rate"].denominator == 2
    assert summary.metrics["duplicate_side_effect_rate"].value == Decimal("0.0000")
    assert summary.metrics["verifier_accuracy"].denominator == 0
    assert summary.metrics["verifier_accuracy"].value is None


def test_duplicate_side_effect_rate_counts_failed_safety_assertions() -> None:
    safe = grade_case(valid_golden_case(), matching_outcome())
    duplicate = grade_case(
        valid_golden_case(),
        matching_outcome().model_copy(update={"state_change_count": 1}),
    )

    summary = summarize_grades(BaselineId.HYBRID, (safe, duplicate))

    assert summary.metrics["duplicate_side_effect_rate"].numerator == 1
    assert summary.metrics["duplicate_side_effect_rate"].denominator == 2
    assert summary.metrics["duplicate_side_effect_rate"].value == Decimal("0.5000")
