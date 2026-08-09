import json
from pathlib import Path

import pytest
from test_evaluation_models import valid_golden_case

from caselens.evaluation.dataset import EvaluationDatasetError, load_golden_cases


def dataset_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "synthetic": True,
        "cases": [valid_golden_case().model_dump(mode="json")],
    }


def test_loads_a_strict_versioned_synthetic_dataset(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(dataset_payload()), encoding="utf-8")

    cases = load_golden_cases(path)

    assert tuple(case.case_id for case in cases) == ("processing_refund_v1",)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema_version", 2, "schema_version"),
        ("synthetic", False, "synthetic"),
        ("cases", [], "cases"),
    ],
)
def test_rejects_invalid_dataset_envelope(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    path = tmp_path / "cases.json"
    payload = dataset_payload()
    payload[field] = value
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(EvaluationDatasetError, match=message):
        load_golden_cases(path)


def test_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    payload = dataset_payload()
    payload["cases"] = [payload["cases"][0], payload["cases"][0]]  # type: ignore[index]
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(EvaluationDatasetError, match="Duplicate Golden Case"):
        load_golden_cases(path)


def test_rejects_malformed_json_without_exposing_the_path(tmp_path: Path) -> None:
    path = tmp_path / "secret-location.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(EvaluationDatasetError) as exc_info:
        load_golden_cases(path)

    assert str(path) not in str(exc_info.value)
