# ADR 0004: On-demand systemd user worker

## Context

Recording must continue after the GUI closes without creating a permanently running daemon.

## Decision

Use a static, on-demand systemd user service for the worker.

## Alternatives considered

- A GUI-owned subprocess.
- A login-started daemon.

## Consequences

The GUI remains separate from recording ownership. Service behaviour is implemented and tested in Phase 5.

## Reversal conditions

Reconsider only if validated user-service operation cannot provide the required lifecycle guarantees.
