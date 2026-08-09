from pathlib import Path
from typing import Literal

from caselens.evaluation.grader import BaselineSummary, CaseGrade
from caselens.evaluation.models import BaselineId, EvaluationModel


class EvaluationReport(EvaluationModel):
    schema_version: Literal[1] = 1
    scope: str = "refund_not_received"
    case_count: int
    baseline_order: tuple[BaselineId, ...]
    grades: tuple[CaseGrade, ...]
    summaries: tuple[BaselineSummary, ...]
    limitations: tuple[str, ...]


def render_json(report: EvaluationReport) -> str:
    return report.model_dump_json(indent=2) + "\n"


def render_markdown(report: EvaluationReport) -> str:
    lines = [
        "# CaseLens Day 15 Evaluation Results",
        "",
        (
            f"This offline run contains {report.case_count} synthetic Golden Cases "
            "for the single `refund_not_received` dispute type."
        ),
        "",
        "## Baseline summary",
        "",
        "| Baseline | Passed | Failed | Not applicable | Pass rate | Avg. tool calls |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    display_names = {
        BaselineId.RULES_ONLY: "Rules-only",
        BaselineId.MODEL_ONLY_SCRIPTED: "model_only_scripted",
        BaselineId.HYBRID: "Hybrid",
    }
    for summary in report.summaries:
        pass_rate = summary.metrics["case_pass_rate"]
        value = "not_measured" if pass_rate.value is None else str(pass_rate.value)
        average = (
            "not_measured"
            if summary.average_tool_calls is None
            else str(summary.average_tool_calls)
        )
        lines.append(
            "| "
            f"{display_names[summary.baseline_id]} | {summary.passed_cases} | "
            f"{summary.failed_cases} | {summary.not_applicable_cases} | "
            f"{pass_rate.numerator}/{pass_rate.denominator} ({value}) | {average} |"
        )

    lines.extend(
        [
            "",
            "## Golden Case results",
            "",
            "| Case | Baseline | Status | Failed assertions |",
            "| --- | --- | --- | --- |",
        ]
    )
    for grade in report.grades:
        failed = ", ".join(
            assertion.name for assertion in grade.assertions if not assertion.passed
        )
        lines.append(
            f"| `{grade.case_id}` | `{grade.baseline_id.value}` | "
            f"{grade.status.value} | {failed or 'none'} |"
        )

    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in report.limitations)
    lines.extend(
        [
            "",
            (
                "`model_only_scripted` is a deterministic protocol/ablation "
                "baseline, not real LLM accuracy."
            ),
            "",
            "Real-model token cost and latency are `not_measured`.",
            "",
            "## Reproduce",
            "",
            "```powershell",
            "Set-Location backend",
            "uv run python -m caselens.evaluation --check",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(
    report: EvaluationReport,
    json_path: str | Path,
    markdown_path: str | Path,
) -> None:
    json_target = Path(json_path)
    markdown_target = Path(markdown_path)
    json_target.parent.mkdir(parents=True, exist_ok=True)
    markdown_target.parent.mkdir(parents=True, exist_ok=True)
    json_temp = json_target.with_name(f"{json_target.name}.tmp")
    markdown_temp = markdown_target.with_name(f"{markdown_target.name}.tmp")
    try:
        json_temp.write_text(render_json(report), encoding="utf-8", newline="\n")
        markdown_temp.write_text(
            render_markdown(report), encoding="utf-8", newline="\n"
        )
        json_temp.replace(json_target)
        markdown_temp.replace(markdown_target)
    finally:
        json_temp.unlink(missing_ok=True)
        markdown_temp.unlink(missing_ok=True)


def reports_match(
    report: EvaluationReport,
    json_path: str | Path,
    markdown_path: str | Path,
) -> bool:
    try:
        existing_json = Path(json_path).read_text(encoding="utf-8")
        existing_markdown = Path(markdown_path).read_text(encoding="utf-8")
    except OSError:
        return False
    return existing_json == render_json(
        report
    ) and existing_markdown == render_markdown(report)
