# CaseLens V0.1 Evaluation

## What this evaluation proves

The Day 15 suite verifies that the implemented `refund_not_received` workflow
behaves predictably across normal decisions, policy boundaries, missing or
conflicting evidence, tool/model failures, approval gating, idempotent replay,
and verifier mismatch.

It is an engineering regression suite, not a production-quality estimate. The
dataset contains 12 synthetic Golden Cases for one dispute type. No external
model, business system, or payment provider is called.

## Dataset and grader

[`golden_cases.json`](../backend/evals/golden_cases.json) is a strict,
versioned, synthetic-only dataset. Each case contains the complete case input,
payment/refund records, policy versions, policy clauses, deterministic fault or
operation script, applicable baselines, and a Golden Expectation.

The grader sees only the normalized baseline outcome and the Golden
Expectation. It checks review status, termination reason, recommendation,
evidence status, policy version, packet presence, required and forbidden tools,
workflow/verifier state, illegal execution, state changes, ungrounded
finalization, and false success claims. Every percentage is accompanied by its
numerator and denominator; non-applicable rows remain visible.

## Baselines

- `rules_only` chooses the required read-only payment query deterministically,
  then reuses the real evidence assembly, time-sensitive policy retrieval, and
  `DecisionPacket` validation. It does not call a model.
- `model_only_scripted` sends one tool-free structured request through
  `MockModel`. It does not use business tools, time filtering, trusted citation
  validation, approval policy, SQLite actions, or verifier read-back. It is a
  deterministic ablation/protocol baseline, not real LLM accuracy.
- `hybrid` runs the implemented CaseLens chain: Mock Tool Calling, the real
  read-only tool executor, evidence assembly, time-sensitive retrieval,
  structured draft validation, human approval, SQLite idempotency, and verifier
  read-back.

The current Rules-only result is intentionally reported without spin: it passes
all six core decision cases. That shows the narrow V0.1 domain is sufficiently
structured for deterministic logic to be strong. Hybrid additionally covers
the six Agent, tool, approval, idempotency, and verification failure cases.

## Reproduce

Requirements are Python 3.12 and [uv](https://docs.astral.sh/uv/).

```powershell
Set-Location backend
$env:UV_CACHE_DIR = "$PWD\..\.codex\uv-cache"
uv sync
uv run python -m caselens.evaluation
uv run python -m caselens.evaluation --check
```

The generated reports are committed at:

- [human-readable results](../backend/evals/results/day15-baseline.md);
- [machine-readable results](../backend/evals/results/day15-baseline.json).

The JSON and Markdown omit timestamps, temporary database paths, and machine
paths. Consecutive runs must be byte-identical. The test suite also exercises a
single-baseline run, missing dataset handling, and report-drift detection.

## Metrics and limitations

The report includes decision and terminal-state accuracy, policy-version
accuracy, required-tool recall, illegal-tool and side-effect rates, ungrounded
finalization, duplicate state change, verifier accuracy, average tool calls,
and explicit not-applicable counts.

Real model token cost and latency are `not_measured`; zero is never substituted
for missing measurements. The committed Mock timings must not be interpreted as
provider latency.

The suite does not establish statistical generalization, real-model quality,
production authorization, external-provider reliability, or coverage of the
three dispute types planned after V0.1. A future provider adapter can reuse the
same dataset, normalized outcome, and independent grader while adding repeated
sampling and cost/latency measurements.
