"""
Shared LLM error classification for retry policy.
"""


def is_client_error(exc: Exception) -> bool:
    """Heuristic: treat 400-range API errors as non-retryable."""
    msg = str(exc).lower()
    return any(code in msg for code in ["400", "401", "403", "404", "422"])
