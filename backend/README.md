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

The current repository is deliberately synchronous and small. Schema migration,
HTTP APIs, Agent execution, and policy-clause retrieval outside the domain
baseline remain later Roadmap work.

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

Every result includes an immutable in-memory trace with the call ID, requested
tool, canonical JSON arguments, timezone-aware start and completion times,
non-negative duration, terminal status, and error code when failed. Trace
persistence remains later Roadmap work; the Day 10 Agent loop records model
traces in its in-memory investigation result.

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

Day 11 remains in memory and does not approve or execute refunds. Approval,
controlled actions, idempotency, final-state reads, and verifier behavior remain
Day 12 work.

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
