from __future__ import annotations

import csv
from pathlib import Path
from typing import List, Sequence


def parse_active_park_refs_csv_lines(lines: Sequence[str]) -> List[str]:
    text = "\n".join(lines)
    return parse_active_park_refs_csv_text(text)


def parse_active_park_refs_csv_text(text: str) -> List[str]:
    refs: List[str] = []
    seen = set()
    reader = csv.DictReader(text.splitlines())
    for row in reader:
        reference = str(row.get("reference", "")).strip().upper()
        active = str(row.get("active", "")).strip()
        if not reference or reference in seen:
            continue
        if active != "1":
            continue
        seen.add(reference)
        refs.append(reference)
    return refs


def load_active_park_refs_file(path: str | Path) -> List[str]:
    p = Path(path)
    data = p.read_text(encoding="utf-8", errors="ignore")
    return parse_active_park_refs_csv_text(data)
