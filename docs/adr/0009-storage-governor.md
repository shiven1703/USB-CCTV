# ADR 0009: 90 GB dynamic storage governor

## Context

The application must coexist with the operating system on a filesystem whose available space changes.

## Decision

Enforce a 90,000,000,000-byte managed ceiling and calculate a lower effective cap from availability, managed usage, OS reserve, and emergency-finalization reserve.

## Alternatives considered

- A fixed minimum-free-space requirement.
- Using total filesystem capacity.

## Consequences

Three original nights and seven total-history nights are measured feasibility targets, not guarantees.

## Reversal conditions

Change only with an approved replacement safety calculation and updated environment contract.
