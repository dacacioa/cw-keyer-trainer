from __future__ import annotations

from pathlib import Path
from typing import List, Sequence


def parse_callsign_lines(lines: Sequence[str]) -> List[str]:
    calls: List[str] = []
    seen = set()
    for raw in lines:
        line = raw.strip().lstrip("\ufeff")
        if not line or line.startswith("#"):
            continue
        first = line.split(",", 1)[0].strip().upper()
        if not first or first.startswith("#"):
            continue
        if first in seen:
            continue
        seen.add(first)
        calls.append(first)
    return calls


def parse_callsign_text(text: str) -> List[str]:
    return parse_callsign_lines(text.splitlines())


def load_callsigns_file(path: str | Path) -> List[str]:
    p = Path(path)
    data = p.read_text(encoding="utf-8", errors="ignore")
    return parse_callsign_text(data)
