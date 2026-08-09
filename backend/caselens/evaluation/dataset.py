import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from caselens.evaluation.models import GoldenCase


class EvaluationDatasetError(ValueError):
    """The public synthetic evaluation dataset is invalid."""


class EvaluationDataset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    synthetic: Literal[True]
    cases: tuple[GoldenCase, ...] = Field(min_length=1)


def load_golden_cases(path: str | Path) -> tuple[GoldenCase, ...]:
    try:
        raw = Path(path).read_text(encoding="utf-8")
        dataset = EvaluationDataset.model_validate_json(raw)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
        raise EvaluationDatasetError(f"Invalid evaluation dataset: {exc}") from None

    case_ids = tuple(case.case_id for case in dataset.cases)
    if len(case_ids) != len(set(case_ids)):
        raise EvaluationDatasetError("Duplicate Golden Case ID.")
    return dataset.cases
