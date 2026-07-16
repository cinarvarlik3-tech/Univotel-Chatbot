"""Unit tests for app/tagassigner/sweep_clean.py."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tagassigner.sweep_clean import _chatwoot_clear_payload, run_sweep_clean


def test_should_include_all_tagassigner_attribute_keys_in_clear_payload():
    payload = _chatwoot_clear_payload()
    assert payload["university"] == "bilinmiyor"
    assert payload["ogrenci_cinsiyet"] == "Bilinmiyor"
    assert payload["oda_tiipi"] == "boş"
    assert payload["ilgili_otel"] == "boş"
    assert payload["butce"] == "boş"


@pytest.mark.asyncio
async def test_should_wipe_database_after_clearing_chatwoot():
    rows = [
        {"id": "a", "chatwoot_conversation_id": 101},
        {"id": "b", "chatwoot_conversation_id": 102},
    ]
    pool = MagicMock()
    pool.fetch = AsyncMock(return_value=rows)

    conn = MagicMock()
    conn.transaction = MagicMock(return_value=AsyncMock())
    conn.transaction.return_value.__aenter__ = AsyncMock(return_value=None)
    conn.transaction.return_value.__aexit__ = AsyncMock(return_value=None)
    conn.execute = AsyncMock(side_effect=[
        None,  # null last_processed_log_id
        "DELETE 3", "DELETE 5", "DELETE 2", "DELETE 1", "DELETE 10", "DELETE 4", "DELETE 2",
    ])
    pool.acquire = MagicMock(return_value=AsyncMock())
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    ok = MagicMock(ok=True)
    with patch("app.tagassigner.sweep_clean.get_pool", return_value=pool), \
         patch("app.tagassigner.sweep_clean.set_labels", new_callable=AsyncMock, return_value=ok), \
         patch("app.tagassigner.sweep_clean.set_custom_attributes", new_callable=AsyncMock, return_value=ok), \
         patch("app.tagassigner.sweep_clean.asyncio.sleep", new_callable=AsyncMock):
        result = await run_sweep_clean()

    assert result.conversations_found == 2
    assert result.chatwoot_cleared == 2
    assert result.chatwoot_failed == 0
    assert result.db_deleted["conversations"] == 2
