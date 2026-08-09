from pathlib import Path

import pytest

from caselens.evaluation.dataset import load_golden_cases
from caselens.evaluation.fixtures import build_fixture
from caselens.evaluation.models import ScenarioId
from caselens.tools.source import SourceTimeoutError

DATASET = Path(__file__).parents[1] / "evals" / "golden_cases.json"
CASES = load_golden_cases(DATASET)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.case_id)
def test_builds_every_fixture_from_public_input(case) -> None:
    fixture = build_fixture(case)

    assert fixture.case is case
    assert fixture.timeline.policy_id == case.input.policy_versions[0].policy_id
    assert fixture.corpus.clauses == case.input.policy_clauses
    assert fixture.collected_at.tzinfo is not None


def test_timeout_fixture_uses_the_real_source_timeout_signal() -> None:
    case = next(
        case for case in CASES if case.scenario is ScenarioId.PAYMENT_TOOL_TIMEOUT
    )
    fixture = build_fixture(case)

    with pytest.raises(SourceTimeoutError):
        fixture.source.get_payment(case.input.case.payment_id)
