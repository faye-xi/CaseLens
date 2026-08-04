from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from caselens.resolution.models import ApprovalDecision

Identifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HealthResponse(ApiModel):
    status: Literal["ok"] = "ok"


class StartReviewRequest(ApiModel):
    review_id: Identifier
    workflow_id: Identifier


class ApprovalRequest(ApiModel):
    decision: ApprovalDecision
    decided_by: Identifier


class ErrorDetail(ApiModel):
    code: Identifier
    message: Identifier


class ErrorResponse(ApiModel):
    error: ErrorDetail
