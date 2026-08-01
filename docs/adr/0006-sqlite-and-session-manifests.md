# ADR 0006: SQLite and per-session manifests

## Context

The library requires searchable state while each recording session needs media-adjacent evidence metadata.

## Decision

Use SQLite for the catalogue and a JSON manifest plus append-only JSONL events per session.

## Alternatives considered

- SQLite alone.
- Flat files alone.

## Consequences

Multi-record changes use SQLite transactions; manifests support recovery and reconciliation without replacing the catalogue.

## Reversal conditions

Reconsider only after a migration plan preserves all authoritative evidence metadata.
