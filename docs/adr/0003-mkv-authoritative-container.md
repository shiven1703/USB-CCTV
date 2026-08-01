# ADR 0003: MKV authoritative container

## Context

Live recordings must survive segmented capture and safely preserve audio and video.

## Decision

Use Matroska (`.mkv`) for authoritative recordings and archives.

## Alternatives considered

- MP4.
- AVI.

## Consequences

Each finalized segment is independently verifiable and remains directly playable. Container validation is mandatory before publication.

## Reversal conditions

Change only after an approved ADR establishes equivalent failure resilience and stream support.
