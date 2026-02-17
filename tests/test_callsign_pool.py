from __future__ import annotations

from core.callsign_pool import parse_callsign_text


def test_parse_callsign_text_ignores_comments_and_uses_first_csv_field():
    text = "\ufeff" + """
# this is a comment
N1MM,John,MA

K1ABC,Anna
  # another comment
EA4XYZ
N1MM,duplicate
"""
    calls = parse_callsign_text(text)
    assert calls == ["N1MM", "K1ABC", "EA4XYZ"]
