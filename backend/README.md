# Refund-not-received business contract

The first supported case type is `refund_not_received`: a customer claims that
an expected refund has not reached them.

## Input

`Case` requires:

- a case ID and the fixed `refund_not_received` case type;
- a timezone-aware occurrence time and non-empty customer statement;
- a positive claim amount and currency;
- order and payment IDs;
- an optional refund ID.

A missing refund ID does not make the customer's claim invalid. It means the
investigation must first locate a refund record.

## Output

`assess_refund_not_received()` returns a
`RefundNotReceivedAssessment` with:

- the case ID;
- `ready_for_investigation` when a refund ID is available;
- `needs_evidence` with `refund_record` when it is not.

This assessment is investigation triage, not a refund decision. Refund status,
evidence conflicts, policy timing, and final recommendations are handled by
separate domain models so this intake contract remains small.

## Failure paths

Pydantic rejects malformed intake data, including unknown fields, timestamps
without a timezone, non-positive amounts, and missing order or payment IDs.
Valid claims without a refund ID remain accepted and produce a structured
missing-evidence result.

## Investigation evidence

After intake, `EvidenceBundle` organizes investigation material into:

- typed facts that record what a named source claims;
- evidence records that preserve each fact's source and collection time;
- missing-evidence items that do not pretend an unavailable record is a
  negative fact;
- conflicts that point to two incompatible facts without deciding which source
  is correct.

The bundle reports `complete` when material is present and consistent,
`incomplete` when evidence is missing, and `conflicted` when facts disagree.
Conflicts take priority over missing items so callers cannot overlook known
contradictions.

Pydantic rejects empty evidence bundles, duplicate evidence or fact IDs,
invalid fact value types, timezone-naive collection times, and conflicts with
missing, self-referencing, unrelated, or equal-valued facts. These deterministic
checks do not call an LLM and do not make a refund decision.

## Auditable decision packets

`DecisionDraft` represents a structured candidate recommendation. It contains
only the case ID, rationale, risk level, fact references, and policy clause IDs.
`build_decision_packet()` checks that those references exist in the trusted
`EvidenceBundle` and `PolicyRetrievalResult`, then creates an immutable
`DecisionPacket` with copied evidence status, missing items, conflicts, the
selected policy version, and trusted policy citations.

Final `approve_refund` and `deny_refund` recommendations require complete,
non-conflicted evidence, at least one resolvable fact reference, and a matching
citation from the selected policy version. Missing evidence produces a
`request_evidence` path, conflicts require `manual_review`, and a policy
no-match cannot be replaced by a citation from another version. `approve_refund`
is always high risk and is marked as requiring approval; this domain layer does
not execute any action or implement the approval workflow.

These checks reject untraceable or unsafe recommendations deterministically.
They do not call an LLM and do not allow a model to invent fact values, policy
versions, effective periods, or policy quotes.

## Persistence repository

`SqliteRepository` stores one case, evidence snapshot, and investigation record
as a single transaction. SQLAlchemy records remain private to the persistence
adapter: callers provide and receive the same validated Pydantic domain models.

SQLite foreign-key checks reject broken ownership references. Duplicate
identifiers become an explicit `RecordConflictError`, missing records become
`RecordNotFoundError`, and mismatched case/evidence input becomes
`RepositoryInputError`. If any child write fails, the complete transaction is
rolled back rather than leaving a partial investigation that looks successful.

The repository remains deliberately synchronous and small. Higher application
layers now add Agent execution, policy retrieval, product APIs, and replay while
keeping SQLAlchemy records behind this adapter. Schema migrations remain out of
scope for the local V0.1 Demo.

## Read-only business tools

Four typed query tools now expose the external records needed by the first
investigation flow:

- order records by `order_id`;
- payment records and their refunds by `payment_id`;
- shipment records and chronologically ordered tracking events by `order_id`;
- chronologically ordered message histories by `order_id`.

Requests and records are immutable Pydantic models that reject blank identifiers,
unknown fields, non-positive amounts, and timezone-naive timestamps. The initial
`InMemoryBusinessDataSource` contains only deterministic synthetic records and
can be replaced by another read-only adapter without changing tool callers.

A missing record raises `RecordNotFoundError`; a source query failure raises
`SourceQueryError`. A known order may legitimately have an empty message history,
but an unavailable history never becomes an empty successful result. A source
timeout raises the distinct `SourceTimeoutError` signal.

## Tool execution and trace protocol

`execute_tool()` is the single synchronous entry point for the four read-only
tools. It resolves the requested tool, validates its JSON arguments with the
existing Pydantic query model, calls the Day 4 service, and always returns a
validated `ToolExecutionResult` for expected outcomes.

Failures are explicit `unknown_tool`, `invalid_input`, `not_found`, `timeout`,
`source_error`, or safe `internal_error` values. Raw validation details, stack
traces, and unexpected exception messages do not cross the execution boundary.
Concrete data-source adapters own their I/O timeout and report
`SourceTimeoutError`; the dispatcher does not create worker threads or claim to
terminate blocked synchronous work.

Every result includes an immutable trace with the call ID, requested
tool, canonical JSON arguments, timezone-aware start and completion times,
non-negative duration, terminal status, and error code when failed. The original
tool boundary is in-memory; the Day 13 product layer now persists complete review
snapshots and exposes normalized model/tool traces through durable replay.

## Mock model and Tool Calling protocol

`caselens.model` defines a small internal Pydantic protocol for model messages,
requests, responses, structured output errors, and in-memory model traces.
`MockModel` consumes only an in-memory response script, records the immutable
requests it received, and returns deterministic errors when a scripted response
is malformed or the script is exhausted. It has no real-model fallback or
network transport.

Model tool calls reuse Day 5's immutable `ToolCall` directly. `tool_definitions()`
derives the advertised JSON Schemas from the same read-only registry and query
models used by `execute_tool()`. `execute_tool_calls()` rejects duplicate or
unauthorized calls before dispatch, then preserves Day 5's parameter
validation, structured error codes, per-call results, and `ToolTrace` values.
Malformed model responses stop at the model boundary rather than guessing or
executing a partial call. This layer handles one model response and one tool
call batch. The Agent layer uses it to run a bounded investigation loop
without adding a second tool registry or bypassing the structured failure
protocol.

## Single-agent investigation loop

`caselens.agent.run_investigation()` owns one synchronous investigation run.
It builds each `ModelRequest` from the current message protocol, advertises
the schemas from `tool_definitions()`, and records each model trace. A
`tool_calls` response is appended as an assistant message, executed through
`execute_tool_calls()`, and returned to the next model step as one structured
`ModelRole.TOOL` message per result.

The loop counts one model completion as one step and defaults to a maximum of
eight steps. A valid `STOP` returns `completed`; model invocation errors return
`error` without tool execution; duplicate or unauthorized batches and the
step budget return `safe_terminated`. Individual invalid-input, missing-data,
timeout, source, and internal tool results remain explicit messages so the
model can decide whether another read-only step is useful.

Day 10 stops at an in-memory `InvestigationResult` containing the message
history and traces. It does not build a `DecisionPacket`, execute side effects,
request approval, or connect to a real model.

## Case review vertical loop

Day 11 adds `caselens.agent.run_case_review()` as the first vertical orchestration
entry point for the supported `refund_not_received` case. It converts the case
into deterministic system/user messages, runs the Day 10 read-only investigation,
and reads facts only from structured `ToolExecutionResult` messages rather than
from the model's prose.

The evidence adapter always records the customer's claim, maps a retrieved
payment/refund record into typed refund facts, and compares the customer's
`refund_received=False` claim with the refund status. `RefundStatus.SUCCEEDED`
is the only status mapped to `refund_received=True`; missing records remain
explicit missing evidence, and source failures never become empty successful
records.

After investigation, policy retrieval uses the case occurrence time to select
the effective version before searching the fixed `refund not received` query.
Complete evidence with at least one policy citation receives a second,
tool-free structured `DecisionDraft` model request. Missing evidence produces
`request_evidence`; conflicting evidence produces `manual_review`; an effective
policy version with no matching clause produces a citation-free `manual_review`.
All paths go through `build_decision_packet()`, which validates references and
computes high-risk approval requirements. Model errors, policy gaps, invalid
drafts, unauthorized tool batches, and maximum-step termination do not create a
final packet.

At the Day 11 boundary, case review remains in memory and does not approve or
execute refunds. The following Day 12 layer consumes its immutable result
without giving the Agent a write tool.

## Approval, idempotent action, and verification

Day 12 adds `caselens.resolution` as a durable safety boundary after case
review. An immutable `DecisionPacket` is fingerprinted and stored alongside a
separate approval request, so a human decision authorizes one exact packet and
planned action rather than a case in the abstract. The Agent and model retain
only their existing read-only tools.

The only simulated side effect completes one existing refund from `requested`
or `processing` to `succeeded`; it never creates a second refund. The action is
planned deterministically from the validated case and unique trusted refund
evidence. Its business idempotency key is
`complete_refund:{payment_id}:{refund_id}`, preventing two workflows from
independently completing the same refund.

`SqliteResolutionStore` persists workflow snapshots and simulated refund state.
The refund mutation, action receipt, idempotency ledger entry, and transition to
verification-ready state share one transaction. Identical retries return the
stored receipt without repeating the mutation, while a different command under
the same key is rejected. Missing refunds and amount, currency, or state
precondition failures produce durable failed receipts without changing business
state.

An action receipt is not final proof of success. The verifier re-reads the
simulated refund through a read-only protocol and compares its identity, status,
amount, currency, and completion time with the approved command. Only a matching
read-back reaches `completed_verified`; mismatches and safe read failures end as
`verification_failed`.

Day 12 remains synchronous and does not add authentication, background jobs, a
real payment provider, or UI behavior. Day 13 wraps these stable service
boundaries without changing their transition rules.

## FastAPI product API and replay

Day 13 adds a thin, versioned FastAPI adapter over `CaseLensApplication`. The
application service coordinates the case/review repository and the independent
resolution store; routes do not reproduce domain rules or state transitions.
Full immutable `CaseReviewResult` snapshots are stored for restart-safe replay,
and every `ResolutionRun` records the exact `review_id` that produced its
authorized packet.

Run the default deterministic demo API:

```powershell
$env:CASELENS_DB_PATH = "$PWD\caselens-demo.db"
uv sync
uv run uvicorn main:app --reload
```

The demo seeds `CASE-DEMO-001`, an existing processing refund, and two policy
versions. Each review gets a fresh scripted `MockModel` and still passes through
the real read-only tool executor, evidence assembly, time-aware policy
retrieval, `DecisionPacket` validation, approval boundary, SQLite action ledger,
and verifier. It never calls a real model, payment provider, or network service.

Day 13 adds durable review-to-workflow linkage to the SQLite schema. V0.1 does
not yet ship migrations, so delete and recreate a database produced by the
Day 12 prototype before starting this API.

All product routes are under `/api/v1`:

- `GET /health`, `GET /cases`, and `GET /cases/{case_id}`;
- `POST /cases/{case_id}/reviews` with client-chosen `review_id` and
  `workflow_id`;
- `GET /reviews/{review_id}` and `GET /workflows/{workflow_id}`;
- `POST /workflows/{workflow_id}/approval` with `decision` and `decided_by`;
- `POST /workflows/{workflow_id}/execute` and
  `POST /workflows/{workflow_id}/verify`;
- `GET /workflows/{workflow_id}/replay` for the case, full review, durable
  resolution snapshot, and normalized model/tool traces.

A complete demo request sequence is:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/cases

$review = @{
  review_id = "review-demo-1"
  workflow_id = "workflow-demo-1"
} | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/cases/CASE-DEMO-001/reviews `
  -ContentType application/json -Body $review

$approval = @{
  decision = "approved"
  decided_by = "demo-reviewer"
} | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/workflows/workflow-demo-1/approval `
  -ContentType application/json -Body $approval

Invoke-RestMethod -Method Post `
  http://127.0.0.1:8000/api/v1/workflows/workflow-demo-1/execute
Invoke-RestMethod -Method Post `
  http://127.0.0.1:8000/api/v1/workflows/workflow-demo-1/verify
Invoke-RestMethod `
  http://127.0.0.1:8000/api/v1/workflows/workflow-demo-1/replay
```

The application clock owns operation timestamps; clients cannot backdate
approval, execution, or verification. Expected missing resources return `404`,
conflicts and illegal transitions return `409`, malformed requests return
`422`, and safe persistence failures return `503`. Business failures use a
stable `{ "error": { "code": ..., "message": ... } }` envelope.
The review response includes `created`: a new review returns `201` with `true`,
while an identical retry returns the same durable result as `200` with `false`.

This API is intentionally synchronous and unauthenticated for the local V0.1
demo. It does not claim production identity, authorization, background-job,
migration, or external-provider support.

## Policy version timeline

`PolicyVersion` records a policy ID, version label, timezone-aware start, and an
optional end. Effective periods use a half-open interval: the start instant is
included and the end instant is excluded. When one version ends exactly as the
next starts, a dispute at that boundary therefore selects only the new version.

`PolicyTimeline.version_at()` accepts the dispute occurrence time and returns
the unique version effective at that instant. Input order does not affect the
selection, and timezone offsets are compared as absolute instants.

Timelines reject empty input, mixed policy IDs, duplicate version labels, and
overlapping effective periods. Invalid or timezone-naive timestamps are also
rejected. A legitimate gap between versions is allowed, but a dispute inside
that gap raises `PolicyVersionNotFoundError` instead of falling back to the
nearest or latest policy.

This deterministic time filter is the first stage of time-sensitive RAG. The
Day 7 retrieval service selects the effective version before scanning a small
in-memory policy-clause corpus. It uses transparent token-overlap scoring with
stable ordering and returns the clause ID, policy version, effective period,
score, and exact original text as a citation. A missing match returns an empty
citation tuple; a policy timeline gap remains an explicit
`PolicyVersionNotFoundError`. Day 8's `DecisionPacket` consumes these trusted
citations but does not add embeddings, a vector database, Agent execution, or
provider-specific model integration.

## Offline Golden-Case evaluation

Day 15 adds `caselens.evaluation`, an offline deterministic evaluation package.
It loads 12 clearly synthetic `refund_not_received` Golden Cases, runs
`rules_only`, `model_only_scripted`, and `hybrid` through one normalized outcome
contract, and grades them independently.

Run or verify the committed reports from this `backend` directory:

```powershell
uv run python -m caselens.evaluation
uv run python -m caselens.evaluation --check
```

Canonical outputs are:

- `evals/results/day15-baseline.json` for machine consumption;
- `evals/results/day15-baseline.md` for human review.

The report contains no generated timestamp or machine-specific path. Two runs
must produce byte-identical files. `--check` returns `0` only when both committed
outputs match a fresh run; invalid datasets, runtime failures, missing results,
or drift return `1` without overwriting the canonical files.

`model_only_scripted` uses fixed `MockModel` responses to expose what is lost
without tools, time-sensitive retrieval, trusted citations, backend policy
checks, and verification. It is not a measurement of real LLM accuracy. Real
token usage and real-model latency are reported as `not_measured`.
