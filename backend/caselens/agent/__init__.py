"""Bounded single-agent investigation orchestration."""

from caselens.agent.loop import run_investigation
from caselens.agent.protocol import (
    InvestigationResult,
    InvestigationStatus,
    InvestigationTerminationReason,
)

__all__ = [
    "InvestigationResult",
    "InvestigationStatus",
    "InvestigationTerminationReason",
    "run_investigation",
]
