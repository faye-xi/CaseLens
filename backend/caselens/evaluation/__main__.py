import argparse
import sys
from collections.abc import Sequence

from caselens.evaluation.dataset import EvaluationDatasetError, load_golden_cases
from caselens.evaluation.models import BaselineId
from caselens.evaluation.report import reports_match, write_report
from caselens.evaluation.runner import run_evaluation


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the offline CaseLens evaluation.")
    parser.add_argument("--dataset", default="evals/golden_cases.json")
    parser.add_argument(
        "--baseline",
        action="append",
        choices=tuple(item.value for item in BaselineId),
    )
    parser.add_argument("--output-json", default="evals/results/day15-baseline.json")
    parser.add_argument("--output-markdown", default="evals/results/day15-baseline.md")
    parser.add_argument("--check", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    baseline_ids = (
        tuple(BaselineId(value) for value in args.baseline)
        if args.baseline
        else tuple(BaselineId)
    )
    try:
        cases = load_golden_cases(args.dataset)
        report = run_evaluation(cases, baseline_ids)
        if args.check:
            if not reports_match(report, args.output_json, args.output_markdown):
                print("Evaluation reports are missing or out of date.", file=sys.stderr)
                return 1
        else:
            write_report(report, args.output_json, args.output_markdown)
    except (EvaluationDatasetError, OSError, ValueError) as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
