"""Unit tests for boot-time config validation (Spec 022 Part A)."""
import pytest

from app.config import validate_config


def test_should_refuse_start_when_both_testing_modes_enabled():
    with pytest.raises(RuntimeError, match="cannot both be enabled"):
        validate_config(
            live_testing_mode=True,
            testing_limitations_mode=True,
            live_testing_limit=10,
        )


def test_should_refuse_start_when_live_testing_mode_on_without_limit():
    with pytest.raises(RuntimeError, match="LIVE_TESTING_LIMIT is not set"):
        validate_config(
            live_testing_mode=True,
            testing_limitations_mode=False,
            live_testing_limit=None,
        )


def test_should_allow_start_when_limit_set_but_live_testing_mode_off():
    validate_config(
        live_testing_mode=False,
        testing_limitations_mode=False,
        live_testing_limit=10,
    )


def test_should_allow_start_when_live_testing_mode_on_with_limit():
    validate_config(
        live_testing_mode=True,
        testing_limitations_mode=False,
        live_testing_limit=10,
    )


def test_should_allow_outbound_block_in_any_combination():
    validate_config(
        live_testing_mode=False,
        testing_limitations_mode=False,
        live_testing_limit=None,
    )
