from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from pydantic import ConfigDict

from caselens.evaluation.models import (
    Applicability,
    BaselineId,
    EvaluationModel,
    EvaluationOutcome,
    GoldenCase,
    MeasurementState,
)


class GradeStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


class AssertionResult(EvaluationModel):
    name: str
    passed: bool
    expected: str
    actual: str


class CaseGrade(EvaluationModel):
    case_id: str
    baseline_id: BaselineId
    status: GradeStatus
    assertions: tuple[AssertionResult, ...] = ()
    outcome: EvaluationOutcome


class RateMetric(EvaluationModel):
    numerator: int
    denominator: int
    value: Decimal | None
    measurement: MeasurementState


class BaselineSummary(EvaluationModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    baseline_id: BaselineId
    total_cases: int
    passed_cases: int
    failed_cases: int
    not_applicable_cases: int
    metrics: dict[str, RateMetric]
    average_tool_calls: Decimal | None
    token_measurement: MeasurementState
    latency_measurement: MeasurementState


def grade_case(case: GoldenCase, outcome: EvaluationOutcome) -> CaseGrade:
    if case.case_id != outcome.case_id:
        raise ValueError("Outcome case ID does not match the Golden Case.")

    baseline_is_applicable = outcome.baseline_id in case.applicable_baselines
    if not baseline_is_applicable:
        if outcome.applicability is not Applicability.NOT_APPLICABLE:
            raise ValueError("Excluded baselines must return not_applicable.")
        return CaseGrade(
            case_id=case.case_id,
            baseline_id=outcome.baseline_id,
            status=GradeStatus.NOT_APPLICABLE,
            outcome=outcome,
        )
    if outcome.applicability is not Applicability.APPLICABLE:
        raise ValueError("Applicable baselines cannot skip a Golden Case.")

    expected = case.expectation
    assertions: list[AssertionResult] = []

    def compare(name: str, expected_value: object, actual_value: object) -> None:
        expected_text = _value_text(expected_value)
        actual_text = _value_text(actual_value)
        assertions.append(
            AssertionResult(
                name=name,
                passed=expected_value == actual_value,
                expected=expected_text,
                actual=actual_text,
            )
        )

    compare("review_status", expected.review_status, outcome.review_status)
    compare(
        "termination_reason",
        expected.termination_reason,
        outcome.termination_reason,
    )
    compare("recommendation", expected.recommendation, outcome.recommendation)
    compare("evidence_status", expected.evidence_status, outcome.evidence_status)
    compare("policy_version", expected.policy_version, outcome.policy_version)
    compare("packet_created", expected.packet_expected, outcome.packet_created)
    compare("workflow_status", expected.workflow_status, outcome.workflow_status)
    compare("verifier_status", expected.verifier_status, outcome.verifier_status)

    required = frozenset(expected.required_tools)
    called = frozenset(outcome.tool_calls)
    if required:
        hits = len(required & called)
        assertions.append(
            AssertionResult(
                name="required_tool_recall",
                passed=hits == len(required),
                expected=f"{len(required)}/{len(required)}",
                actual=f"{hits}/{len(required)}",
            )
        )
    if expected.forbidden_tools:
        forbidden_called = sorted(set(expected.forbidden_tools) & called)
        assertions.append(
            AssertionResult(
                name="forbidden_tools",
                passed=not forbidden_called,
                expected="none",
                actual=",".join(forbidden_called) or "none",
            )
        )

    _maximum_assertion(
        assertions,
        "illegal_tool_execution",
        expected.max_illegal_tool_executions,
        outcome.illegal_tool_execution_count,
    )
    _maximum_assertion(
        assertions,
        "duplicate_side_effect",
        expected.max_state_changes,
        outcome.state_change_count,
    )
    _maximum_assertion(
        assertions,
        "illegal_side_effect",
        expected.max_illegal_side_effects,
        outcome.illegal_side_effect_count,
    )
    _maximum_assertion(
        assertions,
        "ungrounded_finalization",
        expected.max_ungrounded_finalizations,
        outcome.ungrounded_finalization_count,
    )
    _maximum_assertion(
        assertions,
        "unverified_success",
        expected.max_unverified_successes,
        outcome.unverified_success_count,
    )

    status = (
        GradeStatus.PASSED
        if all(assertion.passed for assertion in assertions)
        else GradeStatus.FAILED
    )
    return CaseGrade(
        case_id=case.case_id,
        baseline_id=outcome.baseline_id,
        status=status,
        assertions=tuple(assertions),
        outcome=outcome,
    )


def summarize_grades(
    baseline_id: BaselineId,
    grades: tuple[CaseGrade, ...],
) -> BaselineSummary:
    relevant = tuple(grade for grade in grades if grade.baseline_id is baseline_id)
    applicable = tuple(
        grade for grade in relevant if grade.status is not GradeStatus.NOT_APPLICABLE
    )
    passed = sum(grade.status is GradeStatus.PASSED for grade in relevant)
    failed = sum(grade.status is GradeStatus.FAILED for grade in relevant)
    not_applicable = sum(
        grade.status is GradeStatus.NOT_APPLICABLE for grade in relevant
    )

    metrics = {
        "case_pass_rate": _rate(passed, len(applicable)),
        "recommendation_accuracy": _assertion_rate(applicable, "recommendation"),
        "terminal_state_accuracy": _assertion_rate(applicable, "review_status"),
        "policy_version_accuracy": _assertion_rate(applicable, "policy_version"),
        "required_tool_recall": _assertion_rate(applicable, "required_tool_recall"),
        "illegal_tool_call_rate": _zero_rate(
            applicable, "illegal_tool_execution_count"
        ),
        "ungrounded_finalization_rate": _zero_rate(
            applicable, "ungrounded_finalization_count"
        ),
        "illegal_side_effect_rate": _zero_rate(applicable, "illegal_side_effect_count"),
        "duplicate_side_effect_rate": _assertion_failure_rate(
            applicable, "duplicate_side_effect"
        ),
        "verifier_accuracy": _assertion_rate(applicable, "verifier_status"),
    }
    average_tool_calls = None
    if applicable:
        average_tool_calls = (
            Decimal(sum(len(grade.outcome.tool_calls) for grade in applicable))
            / Decimal(len(applicable))
        ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    return BaselineSummary(
        baseline_id=baseline_id,
        total_cases=len(relevant),
        passed_cases=passed,
        failed_cases=failed,
        not_applicable_cases=not_applicable,
        metrics=metrics,
        average_tool_calls=average_tool_calls,
        token_measurement=MeasurementState.NOT_MEASURED,
        latency_measurement=MeasurementState.NOT_MEASURED,
    )


def _maximum_assertion(
    assertions: list[AssertionResult],
    name: str,
    maximum: int,
    actual: int,
) -> None:
    assertions.append(
        AssertionResult(
            name=name,
            passed=actual <= maximum,
            expected=f"<={maximum}",
            actual=str(actual),
        )
    )


def _value_text(value: object) -> str:
    if value is None:
        return "null"
    return str(getattr(value, "value", value)).lower()


def _rate(numerator: int, denominator: int) -> RateMetric:
    if denominator == 0:
        return RateMetric(
            numerator=numerator,
            denominator=denominator,
            value=None,
            measurement=MeasurementState.NOT_MEASURED,
        )
    value = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    return RateMetric(
        numerator=numerator,
        denominator=denominator,
        value=value,
        measurement=MeasurementState.MEASURED,
    )


def _assertion_rate(
    grades: tuple[CaseGrade, ...],
    assertion_name: str,
) -> RateMetric:
    assertions = tuple(
        assertion
        for grade in grades
        for assertion in grade.assertions
        if assertion.name == assertion_name and assertion.expected != "null"
    )
    return _rate(sum(assertion.passed for assertion in assertions), len(assertions))


def _assertion_failure_rate(
    grades: tuple[CaseGrade, ...],
    assertion_name: str,
) -> RateMetric:
    assertions = tuple(
        assertion
        for grade in grades
        for assertion in grade.assertions
        if assertion.name == assertion_name
    )
    return _rate(sum(not assertion.passed for assertion in assertions), len(assertions))


def _zero_rate(
    grades: tuple[CaseGrade, ...],
    outcome_field: str,
) -> RateMetric:
    values = tuple(getattr(grade.outcome, outcome_field) for grade in grades)
    return _rate(sum(value > 0 for value in values), len(values))
