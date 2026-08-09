from collections.abc import Collection

from caselens.evaluation.baselines import baseline_runners
from caselens.evaluation.grader import grade_case, summarize_grades
from caselens.evaluation.models import BaselineId, GoldenCase
from caselens.evaluation.report import EvaluationReport

DEFAULT_BASELINES = tuple(BaselineId)


def run_evaluation(
    cases: Collection[GoldenCase],
    baseline_ids: Collection[BaselineId] = DEFAULT_BASELINES,
) -> EvaluationReport:
    cases_tuple = tuple(cases)
    requested = tuple(baseline_ids)
    if not cases_tuple:
        raise ValueError("Evaluation requires at least one Golden Case.")
    if not requested or len(requested) != len(set(requested)):
        raise ValueError("Evaluation baselines must be non-empty and unique.")

    runners = baseline_runners()
    grades = tuple(
        grade_case(case, runners[baseline_id].run(case))
        for case in cases_tuple
        for baseline_id in requested
    )
    summaries = tuple(
        summarize_grades(baseline_id, grades) for baseline_id in requested
    )
    return EvaluationReport(
        case_count=len(cases_tuple),
        baseline_order=requested,
        grades=grades,
        summaries=summaries,
        limitations=(
            "The dataset covers one dispute type and is not statistically representative.",
            "All records and policies are synthetic.",
            "The model-only baseline uses fixed MockModel responses.",
            "No external model or payment provider is called.",
        ),
    )
