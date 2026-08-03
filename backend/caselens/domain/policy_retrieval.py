import re
from typing import Annotated

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from caselens.domain.policy import PolicyTimeline, PolicyVersion

NonBlankText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class PolicyClause(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    clause_id: NonBlankText
    policy_id: NonBlankText
    version: NonBlankText
    text: NonBlankText


class PolicyClauseCorpus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    clauses: tuple[PolicyClause, ...] = ()

    @model_validator(mode="after")
    def validate_unique_clause_keys(self) -> "PolicyClauseCorpus":
        keys = [
            (clause.policy_id, clause.version, clause.clause_id)
            for clause in self.clauses
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate policy clause key.")
        return self


class PolicyRetrievalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: NonBlankText
    occurred_at: AwareDatetime
    top_k: int = Field(default=3, ge=1, le=10)


class PolicyCitation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    clause_id: NonBlankText
    policy_id: NonBlankText
    version: NonBlankText
    effective_from: AwareDatetime
    effective_to: AwareDatetime | None = None
    quote: NonBlankText
    score: float = Field(ge=0, le=1)


class PolicyRetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: NonBlankText
    selected_version: PolicyVersion
    citations: tuple[PolicyCitation, ...] = ()


_TOKEN_PATTERN = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")


def retrieve_policy_clauses(
    timeline: PolicyTimeline,
    corpus: PolicyClauseCorpus,
    request: PolicyRetrievalRequest,
) -> PolicyRetrievalResult:
    selected_version = timeline.version_at(request.occurred_at)
    query_tokens = _tokenize(request.query)
    ranked: list[tuple[float, PolicyClause]] = []

    for clause in corpus.clauses:
        if (
            clause.policy_id != selected_version.policy_id
            or clause.version != selected_version.version
        ):
            continue

        score = _overlap_score(query_tokens, _tokenize(clause.text))
        if score > 0:
            ranked.append((score, clause))

    ranked.sort(key=lambda item: (-item[0], item[1].clause_id))
    citations = tuple(
        PolicyCitation(
            clause_id=clause.clause_id,
            policy_id=clause.policy_id,
            version=clause.version,
            effective_from=selected_version.effective_from,
            effective_to=selected_version.effective_to,
            quote=clause.text,
            score=score,
        )
        for score, clause in ranked[: request.top_k]
    )
    return PolicyRetrievalResult(
        query=request.query,
        selected_version=selected_version,
        citations=citations,
    )


def _tokenize(text: str) -> frozenset[str]:
    return frozenset(_TOKEN_PATTERN.findall(text.casefold()))


def _overlap_score(
    query_tokens: frozenset[str],
    clause_tokens: frozenset[str],
) -> float:
    if not query_tokens:
        return 0.0
    return len(query_tokens & clause_tokens) / len(query_tokens)
