import pytest
from pydantic import ValidationError

from caselens.domain.policy import PolicyTimeline, PolicyVersionNotFoundError
from caselens.domain.policy_retrieval import (
    PolicyClause,
    PolicyClauseCorpus,
    PolicyRetrievalRequest,
    retrieve_policy_clauses,
)


def make_timeline() -> PolicyTimeline:
    return PolicyTimeline.model_validate(
        {
            "policy_id": "refund-policy",
            "versions": [
                {
                    "policy_id": "refund-policy",
                    "version": "v1",
                    "effective_from": "2026-01-01T00:00:00+08:00",
                    "effective_to": "2026-07-01T00:00:00+08:00",
                },
                {
                    "policy_id": "refund-policy",
                    "version": "v2",
                    "effective_from": "2026-07-01T00:00:00+08:00",
                    "effective_to": None,
                },
            ],
        }
    )


def make_gap_timeline() -> PolicyTimeline:
    return PolicyTimeline.model_validate(
        {
            "policy_id": "refund-policy",
            "versions": [
                {
                    "policy_id": "refund-policy",
                    "version": "v1",
                    "effective_from": "2026-01-01T00:00:00+08:00",
                    "effective_to": "2026-04-01T00:00:00+08:00",
                },
                {
                    "policy_id": "refund-policy",
                    "version": "v2",
                    "effective_from": "2026-07-01T00:00:00+08:00",
                    "effective_to": None,
                },
            ],
        }
    )


def make_corpus() -> PolicyClauseCorpus:
    return PolicyClauseCorpus(
        clauses=(
            PolicyClause(
                clause_id="REFUND-V1",
                policy_id="refund-policy",
                version="v1",
                text="Refund not received cases allow seven days.",
            ),
            PolicyClause(
                clause_id="REFUND-V2",
                policy_id="refund-policy",
                version="v2",
                text="Refund requests require merchant confirmation.",
            ),
        )
    )


def test_policy_clause_requires_non_blank_identifiers_and_text() -> None:
    with pytest.raises(ValidationError):
        PolicyClause(
            clause_id=" ",
            policy_id="refund-policy",
            version="v1",
            text="Refunds settle within seven days.",
        )

    with pytest.raises(ValidationError):
        PolicyClause(
            clause_id="REFUND-1",
            policy_id="refund-policy",
            version="v1",
            text=" ",
        )


def test_policy_clause_corpus_rejects_duplicate_clause_keys() -> None:
    clause = PolicyClause(
        clause_id="REFUND-1",
        policy_id="refund-policy",
        version="v1",
        text="Refunds settle within seven days.",
    )

    with pytest.raises(ValidationError, match="Duplicate policy clause"):
        PolicyClauseCorpus(clauses=(clause, clause))


def test_retrieval_request_requires_timezone_and_valid_top_k() -> None:
    with pytest.raises(ValidationError):
        PolicyRetrievalRequest(
            query="refund window",
            occurred_at="2026-06-01T00:00:00",
        )

    with pytest.raises(ValidationError):
        PolicyRetrievalRequest(
            query="refund window",
            occurred_at="2026-06-01T00:00:00+08:00",
            top_k=0,
        )


def test_retrieval_only_returns_the_version_effective_at_occurrence_time() -> None:
    result = retrieve_policy_clauses(
        make_timeline(),
        make_corpus(),
        PolicyRetrievalRequest(
            query="merchant confirmation",
            occurred_at="2026-08-01T12:00:00+08:00",
        ),
    )

    assert result.selected_version.version == "v2"
    assert [citation.clause_id for citation in result.citations] == ["REFUND-V2"]
    assert result.citations[0].version == "v2"
    assert result.citations[0].effective_from == result.selected_version.effective_from
    assert result.citations[0].quote == "Refund requests require merchant confirmation."


def test_exact_transition_boundary_uses_the_new_version() -> None:
    result = retrieve_policy_clauses(
        make_timeline(),
        make_corpus(),
        PolicyRetrievalRequest(
            query="merchant confirmation",
            occurred_at="2026-07-01T00:00:00+08:00",
        ),
    )

    assert result.selected_version.version == "v2"


def test_policy_gap_fails_without_falling_back_to_a_clause() -> None:
    with pytest.raises(PolicyVersionNotFoundError):
        retrieve_policy_clauses(
            make_gap_timeline(),
            make_corpus(),
            PolicyRetrievalRequest(
                query="refund",
                occurred_at="2026-05-01T00:00:00+08:00",
            ),
        )


def test_same_instant_in_another_timezone_uses_the_same_policy_version() -> None:
    result = retrieve_policy_clauses(
        make_timeline(),
        make_corpus(),
        PolicyRetrievalRequest(
            query="merchant confirmation",
            occurred_at="2026-06-30T16:00:00+00:00",
        ),
    )

    assert result.selected_version.version == "v2"


def test_retrieval_uses_stable_clause_id_order_and_top_k() -> None:
    corpus = PolicyClauseCorpus(
        clauses=(
            PolicyClause(
                clause_id="B",
                policy_id="refund-policy",
                version="v1",
                text="refund seven days",
            ),
            PolicyClause(
                clause_id="A",
                policy_id="refund-policy",
                version="v1",
                text="refund seven days",
            ),
        )
    )

    result = retrieve_policy_clauses(
        make_timeline(),
        corpus,
        PolicyRetrievalRequest(
            query="refund seven",
            occurred_at="2026-06-01T00:00:00+08:00",
            top_k=1,
        ),
    )

    assert [citation.clause_id for citation in result.citations] == ["A"]


def test_no_matching_clause_returns_empty_immutable_citations() -> None:
    result = retrieve_policy_clauses(
        make_timeline(),
        make_corpus(),
        PolicyRetrievalRequest(
            query="unrelated topic",
            occurred_at="2026-06-01T00:00:00+08:00",
        ),
    )

    assert result.citations == ()
    with pytest.raises(ValidationError):
        result.citations = ()


def test_other_policy_clauses_never_match_selected_version() -> None:
    corpus = PolicyClauseCorpus(
        clauses=(
            PolicyClause(
                clause_id="SHIPPING-1",
                policy_id="shipping-policy",
                version="v1",
                text="refund not received",
            ),
        )
    )

    result = retrieve_policy_clauses(
        make_timeline(),
        corpus,
        PolicyRetrievalRequest(
            query="refund not received",
            occurred_at="2026-06-01T00:00:00+08:00",
        ),
    )

    assert result.citations == ()
