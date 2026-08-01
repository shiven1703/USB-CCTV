# ADR 0010: Power-inhibitor strategy

## Context

Overnight recording must prevent suspend without permanently changing desktop power preferences.

## Decision

The worker owns two `systemd-inhibit` wrapper processes while recording: a `block` inhibitor for
`sleep:idle` (and `handle-lid-switch` only when the user enabled that option), and a `delay`
inhibitor for `shutdown`. The wrapper is supported by the target's locally checked systemd 255
manual and holds logind's handle only for its child-process lifetime. The worker releases both
after safe stop or failure. Its systemd user unit allows 40 seconds for the bounded stop path.

The read-only Linux power-supply adapter reports AC/battery state. At 5% battery or lower while
off AC, the worker safely finalizes and stops rather than starting or continuing a recording.

## Alternatives considered

- Editing KDE power settings.
- Disabling global USB autosuspend.

## Consequences

Screen-off and locking remain allowed; inhibition failures must be visible to the user. The
5% threshold is a conservative Phase 6 constant because the approved plan did not specify a
user-configurable threshold; a later settings change must validate and document any replacement.

## Reversal conditions

Revisit only if a supported API offers equal runtime-only semantics and has been validated.
