# ADR 0011: Hardware encoder selection and fallback

## Context

Encoder listings do not prove that a selected hardware encoder is reliable on the target laptop.

## Decision

Choose an encoder only after a runtime smoke test; use validated software `libx264` or `libx265` fallback otherwise.

## Alternatives considered

- Selecting NVENC, QSV, VAAPI, or V4L2 solely from `ffmpeg -encoders`.
- Assuming all camera profiles are sustainable.

## Consequences

Every profile fallback is explicit, recorded, and subject to measured storage and visual-quality review.

## Reversal conditions

Change after repeatable target-hardware validation proves a new selection policy safer.
