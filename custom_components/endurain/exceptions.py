"""Exceptions for the Endurain integration."""

from __future__ import annotations


class EndurainApiError(Exception):
    """Base Endurain API error."""


class EndurainAuthError(EndurainApiError):
    """Raised when authentication fails."""


class EndurainMfaRequiredError(EndurainAuthError):
    """Raised when MFA is required."""


class EndurainRateLimitError(EndurainApiError):
    """Raised when the Endurain API rate-limits the client."""

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        """Initialize the rate-limit error."""
        super().__init__(message)
        self.retry_after = retry_after
