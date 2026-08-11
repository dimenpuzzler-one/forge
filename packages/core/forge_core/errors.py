class ForgeError(Exception):
    """A user-actionable Forge failure."""


class SourceError(ForgeError):
    """An upstream source failure with optional HTTP context."""

    def __init__(self, message: str, *, status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class ValidationError(ForgeError):
    """An untrusted value did not meet Forge's safety boundary."""

