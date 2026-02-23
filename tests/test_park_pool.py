from __future__ import annotations

from pathlib import Path

from core.park_pool import (
    load_active_park_refs_file,
    parse_active_park_refs_csv_lines,
    parse_active_park_refs_csv_text,
)


CSV_SAMPLE = """
"reference","name","active","entityId"
"US-0001","A","1","291"
"ES-0002","B","0","291"
"ES-0003","C","1","291"
"US-0001","A2","1","291"
""".strip()


def test_parse_active_park_refs_csv_text_filters_only_active_and_unique():
    refs = parse_active_park_refs_csv_text(CSV_SAMPLE)
    assert refs == ["US-0001", "ES-0003"]


def test_parse_active_park_refs_csv_lines_works():
    refs = parse_active_park_refs_csv_lines(CSV_SAMPLE.splitlines())
    assert refs == ["US-0001", "ES-0003"]


def test_load_active_park_refs_file(tmp_path: Path):
    path = tmp_path / "parks.csv"
    path.write_text(CSV_SAMPLE, encoding="utf-8")
    refs = load_active_park_refs_file(path)
    assert refs == ["US-0001", "ES-0003"]
