# ADR 0002: FFmpeg media engine

## Context

The recorder needs local capture, encoding, segmentation, and verification on the supported Ubuntu baseline.

## Decision

Use FFmpeg and ffprobe as infrastructure adapters for media processing and verification.

## Alternatives considered

- A Qt multimedia capture implementation.
- A custom GStreamer pipeline.

## Consequences

Media commands remain outside presentation and are built from validated structured settings. Runtime encoder tests remain required.

## Reversal conditions

Revisit only if FFmpeg cannot meet verified capture or packaging requirements.
