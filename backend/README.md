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
