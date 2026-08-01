"""On-demand worker process entrypoint."""

import logging


def run_worker() -> int:
    """Start and exit cleanly until worker responsibilities are implemented."""
    logging.getLogger(__name__).info("Worker entrypoint started")
    return 0
