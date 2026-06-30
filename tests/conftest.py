"""
Shared pytest configuration.
Tests that require a live DB connection are integration tests and not run by default.
Mark them with @pytest.mark.integration and run with: pytest -m integration
"""
import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: requires live Supabase DB connection")
