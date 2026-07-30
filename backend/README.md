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
