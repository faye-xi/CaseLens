from pathlib import Path

from caselens.evaluation.__main__ import main

DATASET = Path(__file__).parents[1] / "evals" / "golden_cases.json"


def test_cli_writes_json_and_markdown_then_check_detects_no_drift(
    tmp_path: Path,
) -> None:
    json_path = tmp_path / "results.json"
    markdown_path = tmp_path / "results.md"
    arguments = [
        "--dataset",
        str(DATASET),
        "--output-json",
        str(json_path),
        "--output-markdown",
        str(markdown_path),
    ]

    assert main(arguments) == 0
    assert json_path.read_text(encoding="utf-8").endswith("\n")
    assert "hybrid" in json_path.read_text(encoding="utf-8")
    assert "Evaluation Results" in markdown_path.read_text(encoding="utf-8")
    assert main([*arguments, "--check"]) == 0


def test_cli_check_returns_failure_when_report_drifted(tmp_path: Path) -> None:
    json_path = tmp_path / "results.json"
    markdown_path = tmp_path / "results.md"
    arguments = [
        "--dataset",
        str(DATASET),
        "--baseline",
        "hybrid",
        "--output-json",
        str(json_path),
        "--output-markdown",
        str(markdown_path),
    ]
    assert main(arguments) == 0
    json_path.write_text("drifted\n", encoding="utf-8")

    assert main([*arguments, "--check"]) == 1
    assert json_path.read_text(encoding="utf-8") == "drifted\n"


def test_cli_returns_failure_for_missing_dataset(tmp_path: Path) -> None:
    assert (
        main(
            [
                "--dataset",
                str(tmp_path / "missing.json"),
                "--output-json",
                str(tmp_path / "result.json"),
                "--output-markdown",
                str(tmp_path / "result.md"),
            ]
        )
        == 1
    )
