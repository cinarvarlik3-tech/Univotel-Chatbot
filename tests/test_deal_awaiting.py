"""Unit tests for app/tagassigner/deal_awaiting.py (spec 021)."""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.tagassigner.deal_awaiting import DEAL_AWAITING_LABEL, apply_deal_awaiting

_UNI_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


@pytest.mark.asyncio
async def test_should_add_deal_awaiting_when_university_on_list():
    with patch(
        "app.tagassigner.deal_awaiting.queries.is_deal_awaiting_university",
        new_callable=AsyncMock,
        return_value=True,
    ):
        result = await apply_deal_awaiting(_UNI_ID, ["ogrenci"])
    assert DEAL_AWAITING_LABEL in result
    assert "ogrenci" in result


@pytest.mark.asyncio
async def test_should_not_add_when_university_not_on_list():
    with patch(
        "app.tagassigner.deal_awaiting.queries.is_deal_awaiting_university",
        new_callable=AsyncMock,
        return_value=False,
    ):
        result = await apply_deal_awaiting(_UNI_ID, ["ogrenci"])
    assert DEAL_AWAITING_LABEL not in result


@pytest.mark.asyncio
async def test_should_noop_when_university_id_is_none():
    result = await apply_deal_awaiting(None, ["ogrenci"])
    assert result == ["ogrenci"]


@pytest.mark.asyncio
async def test_should_not_double_add_when_label_already_present():
    with patch(
        "app.tagassigner.deal_awaiting.queries.is_deal_awaiting_university",
        new_callable=AsyncMock,
    ) as mock_check:
        result = await apply_deal_awaiting(
            _UNI_ID, ["ogrenci", DEAL_AWAITING_LABEL]
        )
    mock_check.assert_not_called()
    assert result == ["ogrenci", DEAL_AWAITING_LABEL]


@pytest.mark.asyncio
async def test_should_never_remove_deal_awaiting_when_university_not_on_list():
    with patch(
        "app.tagassigner.deal_awaiting.queries.is_deal_awaiting_university",
        new_callable=AsyncMock,
        return_value=False,
    ):
        result = await apply_deal_awaiting(
            _UNI_ID, ["ogrenci", DEAL_AWAITING_LABEL]
        )
    assert DEAL_AWAITING_LABEL in result
