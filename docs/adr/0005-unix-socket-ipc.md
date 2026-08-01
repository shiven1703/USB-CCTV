# ADR 0005: Unix socket IPC

## Context

The GUI needs a local, user-restricted protocol to communicate with an independent worker.

## Decision

Use a versioned Unix-domain socket under the user runtime directory.

## Alternatives considered

- D-Bus application API.
- HTTP loopback server.

## Consequences

Filesystem permissions restrict access and the protocol exposes only schema-validated predefined commands.

## Reversal conditions

Change only if a replacement has equivalent local access control and validation.
