class ToolError(Exception):
    """Raised when a tool encounters an error."""

    def __init__(self, message):
        self.message = message


class AgentError(Exception):
    """Base exception for agent runtime failures."""


class TokenLimitExceeded(AgentError):
    """Exception raised when the token limit is exceeded"""
