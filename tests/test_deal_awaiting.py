"""Unit tests for app/tagassigner/deal_awaiting.py (spec 021, gate spec 027)."""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.tagassigner.deal_awaiting import DEAL_AWAITING_LABEL, apply_deal_awaiting

_UNI_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


def _patched(on_list: bool, hotels_for_gender: list = None, any_property: bool = False):
    """Context manager patching both DB checks apply_deal_awaiting depends on."""
    return patch.multiple(
        "app.tagassigner.deal_awaiting.queries",
        is_deal_awaiting_university=AsyncMock(return_value=on_list),
        find_hotels_by_gender_and_university=AsyncMock(
            return_value=hotels_for_gender or []
        ),
        has_any_serviceable_property=AsyncMock(return_value=any_property),
    )


@pytest.mark.asyncio
async def test_should_add_when_on_list_and_no_property_for_known_gender():
    with _patched(on_list=True, hotels_for_gender=[]):
        result = await apply_deal_awaiting(_UNI_ID, "female", ["ogrenci"])
    assert DEAL_AWAITING_LABEL in result
    assert "ogrenci" in result


@pytest.mark.asyncio
async def test_should_not_add_when_on_list_but_property_exists_for_gender():
    with _patched(on_list=True, hotels_for_gender=[object()]):
        result = await apply_deal_awaiting(_UNI_ID, "female", ["ogrenci"])
    assert DEAL_AWAITING_LABEL not in result


@pytest.mark.asyncio
async def test_should_not_add_when_gender_unknown_and_any_property_exists():
    with _patched(on_list=True, any_property=True):
        result = await apply_deal_awaiting(_UNI_ID, None, ["ogrenci"])
    assert DEAL_AWAITING_LABEL not in result


@pytest.mark.asyncio
async def test_should_add_when_gender_unknown_and_no_property_exists():
    with _patched(on_list=True, any_property=False):
        result = await apply_deal_awaiting(_UNI_ID, None, ["ogrenci"])
    assert DEAL_AWAITING_LABEL in result


@pytest.mark.asyncio
async def test_should_not_add_when_university_not_on_list():
    with _patched(on_list=False):
        result = await apply_deal_awaiting(_UNI_ID, "male", ["ogrenci"])
    assert DEAL_AWAITING_LABEL not in result


@pytest.mark.asyncio
async def test_should_noop_when_university_id_is_none():
    result = await apply_deal_awaiting(None, "female", ["ogrenci"])
    assert result == ["ogrenci"]


@pytest.mark.asyncio
async def test_should_not_double_add_when_label_already_present():
    with patch(
        "app.tagassigner.deal_awaiting.queries.is_deal_awaiting_university",
        new_callable=AsyncMock,
    ) as mock_check:
        result = await apply_deal_awaiting(
            _UNI_ID, "female", ["ogrenci", DEAL_AWAITING_LABEL]
        )
    mock_check.assert_not_called()
    assert result == ["ogrenci", DEAL_AWAITING_LABEL]


@pytest.mark.asyncio
async def test_should_never_remove_deal_awaiting_when_now_serviceable():
    with _patched(on_list=True, hotels_for_gender=[object()]):
        result = await apply_deal_awaiting(
            _UNI_ID, "female", ["ogrenci", DEAL_AWAITING_LABEL]
        )
    assert DEAL_AWAITING_LABEL in result


@pytest.mark.asyncio
async def test_should_never_remove_deal_awaiting_when_university_not_on_list():
    with _patched(on_list=False):
        result = await apply_deal_awaiting(
            _UNI_ID, "male", ["ogrenci", DEAL_AWAITING_LABEL]
        )
    assert DEAL_AWAITING_LABEL in result


@pytest.mark.asyncio
async def test_yeditepe_class_male_lead_still_gets_label_when_only_female_inventory():
    """Regression guard: schools with gendered-only inventory must still gate correctly."""
    with _patched(on_list=True, hotels_for_gender=[]):
        result = await apply_deal_awaiting(_UNI_ID, "male", [])
    assert DEAL_AWAITING_LABEL in result
