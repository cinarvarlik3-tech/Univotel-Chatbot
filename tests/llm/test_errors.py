"""Unit tests for shared LLM error helpers."""
from app.llm.errors import is_client_error


def test_should_treat_4xx_as_client_error():
    assert is_client_error(Exception("HTTP 400 Bad Request")) is True


def test_should_not_treat_5xx_as_client_error():
    assert is_client_error(Exception("HTTP 500 Internal Server Error")) is False
