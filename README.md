# CaseLens

> **Work in Progress — V0.1 Day 4 complete**

CaseLens is an auditable e-commerce dispute review agent and policy regression lab.

CaseLens 是一个可审计的电商争议复核 Agent 与政策回归实验台。

## Core Question

How can an agent that operates business tools remain verifiable, reviewable, and replayable when policies change, evidence conflicts, and tools fail?

## Implemented

- Python 3.12 backend managed with uv.
- Pydantic case model with structured validation.
- Timezone-aware dispute timestamps.
- Deterministic missing-evidence detection for refund records.
- Structured investigation-readiness assessment for refund-not-received cases.
- Auditable fact and evidence records with explicit missing items and conflicts.
- Deterministic evidence status: complete, incomplete, or conflicted.
- Atomic SQLite persistence for cases, evidence snapshots, and investigation
  records through a SQLAlchemy repository.
- Explicit persistence failures for missing records, conflicting identifiers,
  invalid aggregate input, and rolled-back transactions.
- Typed, read-only order, payment/refund, logistics, and message tools backed by
  a replaceable business-data source.
- Explicit distinction between missing business records and source query
  failures; failed reads never become successful empty records.
- Automated pytest coverage and Ruff checks.

## Planned for V0.1

- Deterministic domain models for the remaining three dispute types.
- Single-agent investigation with structured tool calling.
- Time-sensitive, versioned policy retrieval.
- Human approval, controlled simulated actions, and final-state verification.
- Golden-case evaluation and replayable traces.
- React and TypeScript review workspace.

## Run the Current Tests

Requirements:

- Python 3.12
- [uv](https://docs.astral.sh/uv/)

```powershell
cd backend
uv sync
uv run python -m pytest
uv run ruff check .
uv run ruff format --check .
```

## Project Documentation

- [Project context](docs/PROJECT_CONTEXT.md)

The repository is being developed in small, testable increments. Planned capabilities are not presented as completed features.
