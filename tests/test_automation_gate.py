"""Unit tests for app/layers/automation_gate.py (Spec 031 C1)."""
import pytest

from app.layers.automation_gate import is_automation_message

_FULL_AUTOMATION = (
    "Size daha iyi yardımcı olabilmem için hangi üniversite ve hangi kampüsteydeniz "
    "efendim? O sırada univotel.com'u incelemiş miydiniz?"
)


@pytest.mark.parametrize(
    "content",
    [
        _FULL_AUTOMATION,
        "  " + _FULL_AUTOMATION + "  ",
        _FULL_AUTOMATION.replace("univotel.com'u", "univotel.com\u2019u"),
    ],
)
def test_should_match_chatwoot_automation_template(content: str):
    assert is_automation_message(content) is True


def test_should_not_match_partial_university_phrase_alone():
    assert is_automation_message("hangi üniversite") is False


@pytest.mark.parametrize("content", [None, "", "   "])
def test_should_return_false_for_empty_content(content):
    assert is_automation_message(content) is False
