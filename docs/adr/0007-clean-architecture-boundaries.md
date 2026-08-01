# ADR 0007: Clean Architecture boundaries

## Context

The recorder combines GUI, hardware, media, persistence, and recovery concerns that need independent testing.

## Decision

Keep dependencies inward: standard-library-only domain, application ports, infrastructure adapters, and PySide6 presentation.

## Alternatives considered

- A Qt-centric application with direct FFmpeg calls.
- Framework-specific business logic.

## Consequences

Domain and application packages cannot import Qt; presentation does not directly invoke hardware or persistence adapters.

## Reversal conditions

Alter the boundary only through an ADR showing simpler testable dependency flow.
