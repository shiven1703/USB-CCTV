# ADR 0008: Archive transaction and source deletion

## Context

Archiving may reduce storage but must not risk authoritative original recordings.

## Decision

Create, fully validate, atomically publish, and durably catalogue a separate archive before any policy-permitted source deletion.

## Alternatives considered

- In-place transcoding.
- Deleting a source after an FFmpeg success exit.

## Consequences

Archive work needs temporary headroom, checksums, full decoding, and recoverable transaction states.

## Reversal conditions

Never relax this policy without equivalent independently verified source preservation.
