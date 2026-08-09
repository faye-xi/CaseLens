from pathlib import Path

import pytest

from caselens.evaluation.dataset import load_golden_cases
from caselens.evaluation.models import BaselineId
from caselens.evaluation.report import render_markdown, write_report
from caselens.evaluation.runner import run_evaluation

DATASET = Path(__file__).parents[1] / "evals" / "golden_cases.json"


def test_runs_every_case_and_baseline_in_stable_order() -> None:
    report = run_evaluation(load_golden_cases(DATASET))

    assert report.schema_version == 1
    assert report.case_count == 12
    assert report.baseline_order == tuple(BaselineId)
    assert len(report.grades) == 36
    assert report.grades[0].case_id == "processing_refund_v1"
    assert report.grades[0].baseline_id is BaselineId.RULES_ONLY
    assert report.grades[1].baseline_id is BaselineId.MODEL_ONLY_SCRIPTED
    assert report.grades[2].baseline_id is BaselineId.HYBRID
    assert report.summaries[2].passed_cases == 12
    assert report.summaries[2].failed_cases == 0


def test_report_serialization_is_stable_and_has_no_runtime_metadata() -> None:
    cases = load_golden_cases(DATASET)

    first = run_evaluation(cases).model_dump_json(indent=2)
    second = run_evaluation(cases).model_dump_json(indent=2)

    assert first == second
    assert "generated_at" not in first
    assert "caselens-eval-" not in first


def test_markdown_exposes_counts_limitations_and_failure_rows() -> None:
    markdown = render_markdown(run_evaluation(load_golden_cases(DATASET)))

    assert "12 synthetic Golden Cases" in markdown
    assert "model_only_scripted" in markdown
    assert "not real LLM accuracy" in markdown
    assert "not_measured" in markdown
    assert "payment_tool_timeout" in markdown
    assert "Hybrid" in markdown
    assert "## Metric details" in markdown
    assert "| `hybrid` | `verifier_accuracy` | 2 | 2 | 1.0000 | measured |" in markdown
    assert "## Failure catalog" in markdown
    assert (
        "| `processing_refund_v1` | `model_only_scripted` | "
        "`evidence_status` | `complete` | `null` |" in markdown
    )


def test_report_pair_rolls_back_when_second_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    json_path = tmp_path / "results.json"
    markdown_path = tmp_path / "results.md"
    json_path.write_text("old-json\n", encoding="utf-8")
    markdown_path.write_text("old-markdown\n", encoding="utf-8")
    original_replace = Path.replace

    def fail_markdown_replace(source: Path, target: Path) -> Path:
        if source.name == "results.md.tmp":
            raise OSError("injected second replace failure")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_markdown_replace)

    with pytest.raises(OSError, match="second replace failure"):
        write_report(
            run_evaluation(load_golden_cases(DATASET)),
            json_path,
            markdown_path,
        )

    assert json_path.read_text(encoding="utf-8") == "old-json\n"
    assert markdown_path.read_text(encoding="utf-8") == "old-markdown\n"
    assert not (tmp_path / "results.json.tmp").exists()
    assert not (tmp_path / "results.md.tmp").exists()
