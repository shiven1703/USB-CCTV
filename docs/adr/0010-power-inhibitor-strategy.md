# ADR 0010: Power-inhibitor strategy

## Context

Overnight recording must prevent suspend without permanently changing desktop power preferences.

## Decision

The worker will hold verified logind inhibitor handles while recording and release them after finalization.

## Alternatives considered

- Editing KDE power settings.
- Disabling global USB autosuspend.

## Consequences

Screen-off and locking remain allowed; inhibition failures must be visible to the user.

## Reversal conditions

Revisit only if a supported API offers equal runtime-only semantics and has been validated.
