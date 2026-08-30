"""Domain errors with safe, structured handling paths."""


class CopilotError(Exception):
    """Base error for known workflow failures."""


class DataNotFoundError(CopilotError):
    """Requested synthetic data does not exist."""


class ToolUnavailableError(CopilotError):
    """A controlled tool is unavailable after bounded retry attempts."""
