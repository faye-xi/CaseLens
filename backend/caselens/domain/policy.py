from datetime import datetime
from itertools import pairwise
from typing import Annotated

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

NonBlankText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class PolicyVersionNotFoundError(LookupError):
    def __init__(self, policy_id: str, occurred_at: datetime) -> None:
        self.policy_id = policy_id
        self.occurred_at = occurred_at
        super().__init__(
            f"No version of policy {policy_id!r} is effective at "
            f"{occurred_at.isoformat()}."
        )


class PolicyVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_id: NonBlankText
    version: NonBlankText
    effective_from: AwareDatetime
    effective_to: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_effective_window(self) -> "PolicyVersion":
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be after effective_from.")
        return self


class PolicyTimeline(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_id: NonBlankText
    versions: tuple[PolicyVersion, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_versions(self) -> "PolicyTimeline":
        if any(version.policy_id != self.policy_id for version in self.versions):
            raise ValueError("All versions must have the same policy_id.")

        labels = [version.version for version in self.versions]
        if len(labels) != len(set(labels)):
            raise ValueError("Duplicate policy version label.")

        ordered_versions = sorted(
            self.versions,
            key=lambda version: version.effective_from,
        )
        for previous, current in pairwise(ordered_versions):
            if (
                previous.effective_to is None
                or current.effective_from < previous.effective_to
            ):
                raise ValueError("Policy version effective periods overlap.")

        return self

    def version_at(self, occurred_at: datetime) -> PolicyVersion:
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware.")

        for version in self.versions:
            if version.effective_from <= occurred_at and (
                version.effective_to is None or occurred_at < version.effective_to
            ):
                return version

        raise PolicyVersionNotFoundError(self.policy_id, occurred_at)
