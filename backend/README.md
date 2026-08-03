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
evidence conflicts, policy timing, and final recommendations are intentionally
outside this contract.

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
HTTP APIs, tool traces, Agent execution, and policy retrieval remain later
Roadmap work.

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
persistence and Agent execution remain later Roadmap work.
