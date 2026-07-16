"""Unit tests for app/tagassigner/fiyat_soruyor.py (spec 027, Mode B)."""
import uuid
from datetime import datetime, timedelta, timezone

from app.db.models import Message
from app.tagassigner.fiyat_soruyor import FIYAT_SORUYOR_LABEL, compute_fiyat_soruyor

_CONV_ID = uuid.uuid4()
_T0 = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


def _msg(content: str, message_type: str, offset_seconds: int) -> Message:
    return Message(
        id=uuid.uuid4(),
        conversation_id=_CONV_ID,
        chatwoot_message_id=offset_seconds,
        content=content,
        message_type=message_type,
        created_at=_T0 + timedelta(seconds=offset_seconds),
    )


def test_widget_bilgi_opener_alone_does_not_apply():
    """Mode B1 regression: Büşra / Ben Kısaca — 'bilgi'/'detay' openers are not price asks."""
    messages = [
        _msg("Academia Residence 1+1 bilgi alabilir miyim? Detayları öğrenebilir miyim?",
             "inbound", 0),
        _msg("Academia Residence... Detaylar ve fiyat bilgisi: https://drive.google.com/x",
             "outbound", 10),
    ]
    result = compute_fiyat_soruyor(messages, [])
    assert FIYAT_SORUYOR_LABEL not in result


def test_explicit_price_ask_with_no_delivery_applies():
    messages = [
        _msg("fiyat ne kadar acaba", "inbound", 0),
    ]
    result = compute_fiyat_soruyor(messages, [])
    assert FIYAT_SORUYOR_LABEL in result


def test_price_ask_then_typed_tl_removes():
    """Mode B2 regression: Muhammet — typed TL amount clears the label."""
    messages = [
        _msg("Önemli değil fiyatı öğrenebilir miyim", "inbound", 0),
        _msg("15000 TL'den başlıyor", "outbound", 10),
    ]
    result = compute_fiyat_soruyor(messages, [FIYAT_SORUYOR_LABEL])
    assert FIYAT_SORUYOR_LABEL not in result


def test_price_ask_then_canned_line_with_drive_removes():
    """Mode B2 regression: Büşra — canned pricing line + drive link clears the label."""
    messages = [
        _msg("Academia Residence bilgi alabilir miyim", "inbound", 0),
        _msg("fiyat nedir", "inbound", 5),
        _msg("Detaylar ve fiyat bilgisi: https://drive.google.com/abc",
             "outbound", 10),
    ]
    result = compute_fiyat_soruyor(messages, [])
    assert FIYAT_SORUYOR_LABEL not in result


def test_bare_drive_link_without_canned_line_does_not_count_as_delivery():
    """A drive link alone (photos/location) must not count as price delivery."""
    messages = [
        _msg("fiyat ne kadar", "inbound", 0),
        _msg("Oda ve mekan fotoğrafları: https://drive.google.com/photos",
             "outbound", 10),
    ]
    result = compute_fiyat_soruyor(messages, [])
    assert FIYAT_SORUYOR_LABEL in result


def test_ask_after_delivery_reapplies():
    messages = [
        _msg("fiyat ne kadar", "inbound", 0),
        _msg("15000 TL", "outbound", 10),
        _msg("peki başka fiyat seçeneği var mı", "inbound", 20),
    ]
    result = compute_fiyat_soruyor(messages, [])
    assert FIYAT_SORUYOR_LABEL in result


def test_bare_kac_para_phrasing_applies():
    """Code-review regression: 'kaç para' without 'aylık' must still count as a price ask."""
    messages = [_msg("bu oda kaç para?", "inbound", 0)]
    result = compute_fiyat_soruyor(messages, [])
    assert FIYAT_SORUYOR_LABEL in result


def test_lira_wording_counts_as_delivered():
    """Code-review regression: 'lira' (not just 'tl') must count as price delivery."""
    messages = [
        _msg("fiyat ne kadar", "inbound", 0),
        _msg("15000 lira", "outbound", 10),
    ]
    result = compute_fiyat_soruyor(messages, [])
    assert FIYAT_SORUYOR_LABEL not in result


def test_try_symbol_counts_as_delivered():
    """Code-review regression: the ₺ symbol must count as price delivery."""
    messages = [
        _msg("fiyat ne kadar", "inbound", 0),
        _msg("₺15000'den başlıyor", "outbound", 10),
    ]
    result = compute_fiyat_soruyor(messages, [])
    assert FIYAT_SORUYOR_LABEL not in result


def test_no_price_mention_at_all_never_applies():
    messages = [
        _msg("merhaba nasılsınız", "inbound", 0),
        _msg("iyiyiz siz nasılsınız", "outbound", 5),
    ]
    result = compute_fiyat_soruyor(messages, [FIYAT_SORUYOR_LABEL])
    assert FIYAT_SORUYOR_LABEL not in result


def test_empty_content_messages_are_ignored():
    messages = [
        _msg("", "inbound", 0),
        _msg(None, "outbound", 5),  # type: ignore[arg-type]
        _msg("fiyat ne kadar", "inbound", 10),
    ]
    result = compute_fiyat_soruyor(messages, [])
    assert FIYAT_SORUYOR_LABEL in result


def test_preserves_other_labels():
    messages = [_msg("fiyat ne kadar", "inbound", 0)]
    result = compute_fiyat_soruyor(messages, ["ogrenci", "universitede"])
    assert set(result) == {"ogrenci", "universitede", FIYAT_SORUYOR_LABEL}
