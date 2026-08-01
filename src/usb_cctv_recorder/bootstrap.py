"""Composition root for the desktop application."""

from .presentation.qt.app import run_application


def run_gui() -> int:
    """Start the presentation shell; application services are added in later phases."""
    return run_application()
