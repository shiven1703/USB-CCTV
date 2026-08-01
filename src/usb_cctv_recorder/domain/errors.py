"""Errors raised when a domain invariant would be broken."""


class DomainError(ValueError):
    """Base error for invalid domain data or operations."""


class InvalidStateTransition(DomainError):
    """Raised when a lifecycle state cannot move to the requested state."""
