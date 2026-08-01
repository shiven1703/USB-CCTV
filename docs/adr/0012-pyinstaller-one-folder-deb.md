# ADR 0012: PyInstaller one-folder inside Debian package

## Context

The final product must install as one `.deb` without requiring the user to create a Python environment.

## Decision

Package a PyInstaller one-folder build inside the Debian artifact.

## Alternatives considered

- PyInstaller one-file mode.
- Requiring an external virtual environment.

## Consequences

The package includes the Python/PySide runtime while retaining declared system dependencies such as FFmpeg.

## Reversal conditions

Revisit if a supported packaging method improves reliability without breaking the single-package requirement.
