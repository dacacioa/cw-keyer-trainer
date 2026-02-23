from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

import yaml


PatternList = Tuple[str, ...]


@dataclass(frozen=True)
class ExchangePatterns:
    s0: Dict[str, PatternList]
    s2: Dict[str, PatternList]
    s5: Dict[str, PatternList]
    tx: Dict[str, str]


def default_exchange_patterns() -> ExchangePatterns:
    return ExchangePatterns(
        s0={
            "SIMPLE": (r"^.*(?:CQ)+.*DE.*(?:{MY_CALL})+.*K.*$",),
            "POTA": (r"^.*(?:CQ)+.*POTA.*DE.*(?:{MY_CALL})+.*K.*$",),
            "SOTA": (r"^.*(?:CQ)+.*SOTA.*DE.*(?:{MY_CALL})+.*K.*$",),
        },
        s2={
            "report_require_call": (r"^.*{OTHER_CALL}.*(?:[1-5][1-9N][9N]).*(?:[1-5][1-9N][9N]).*$",),
            "report_require_call_allow_599": (
                r"^.*{OTHER_CALL}.*(?:[1-5][1-9N][9N]).*(?:[1-5][1-9N][9N]).*$",
            ),
            "report_no_call": (r"^.*(?:[1-5][1-9N][9N]).*(?:[1-5][1-9N][9N]).*$",),
            "report_no_call_allow_599": (r"^.*(?:[1-5][1-9N][9N]).*(?:[1-5][1-9N][9N]).*$",),
            "p2p_ack": (r"^{OTHER_CALL}$",),
        },
        s5={
            "with_prosign": (r"^.*{PROSIGN}.*73.*EE.*$",),
            "with_prosign_allow_tu": (r"^.*{PROSIGN}.*TU.*73.*EE.*$",),
            "without_prosign": (r"^.*73.*EE.*$",),
            "without_prosign_allow_tu": (r"^.*TU.*73.*EE.*$",),
            "p2p_with_prosign": (
                r"^.*{PROSIGN}.*{OTHER_CALL_REAL}.*{MY_CALL}.*MY.*REF.*{MY_PARK_REF}.*{MY_PARK_REF}.*$",
            ),
            "p2p_with_prosign_allow_tu": (
                r"^.*{PROSIGN}.*{OTHER_CALL_REAL}.*{MY_CALL}.*MY.*REF.*{MY_PARK_REF}.*{MY_PARK_REF}.*TU.*73.*{PROSIGN}.*$",
            ),
            "p2p_without_prosign": (
                r"^.*{OTHER_CALL_REAL}.*{MY_CALL}.*MY.*REF.*{MY_PARK_REF}.*{MY_PARK_REF}.*$",
            ),
            "p2p_without_prosign_allow_tu": (
                r"^.*{OTHER_CALL_REAL}.*{MY_CALL}.*MY.*REF.*{MY_PARK_REF}.*{MY_PARK_REF}.*TU.*73.*$",
            ),
        },
        tx={
            "caller_call": "{CALL} {CALL}",
            "repeat_selected_call": "{OTHER_CALL} {OTHER_CALL}",
            "ack_rr": "RR",
            "report_reply": "{TX_PROSIGN} UR 5NN 5NN TU 73 {TX_PROSIGN}",
            "qso_complete": "EE",
            "p2p_repeat_call": "{OTHER_CALL_REAL} {OTHER_CALL_REAL}",
            "p2p_repeat_ref": "{PARK_REF} {PARK_REF}",
            "p2p_station_reply_without_tu": (
                "{TX_PROSIGN} {OTHER_CALL_REAL} {OTHER_CALL_REAL} MY REF "
                "{PARK_REF} {PARK_REF} 73 {TX_PROSIGN}"
            ),
            "p2p_station_reply_with_tu": (
                "{TX_PROSIGN} {OTHER_CALL_REAL} {OTHER_CALL_REAL} MY REF "
                "{PARK_REF} {PARK_REF} TU 73 {TX_PROSIGN}"
            ),
        },
    )


def load_exchange_patterns(path: Optional[str | Path]) -> Tuple[ExchangePatterns, Optional[str]]:
    defaults = default_exchange_patterns()
    path_str = str(path or "").strip()
    if not path_str:
        return defaults, None

    p = Path(path_str)
    if not p.exists():
        return defaults, f"Pattern file not found: {p}. Using built-in defaults."

    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return defaults, f"Pattern file could not be read: {p} ({exc}). Using built-in defaults."

    if not isinstance(raw, Mapping):
        return defaults, f"Pattern file has invalid format: {p}. Using built-in defaults."

    node = raw.get("patterns", raw)
    if not isinstance(node, Mapping):
        return defaults, f"Pattern file has invalid root: {p}. Using built-in defaults."

    s0 = _merge_pattern_section(defaults.s0, node.get("s0"), uppercase_keys=True)
    s2 = _merge_pattern_section(defaults.s2, node.get("s2"), uppercase_keys=False)
    s5 = _merge_pattern_section(defaults.s5, node.get("s5"), uppercase_keys=False)
    tx = _merge_template_section(defaults.tx, node.get("tx"), uppercase_keys=False)
    return ExchangePatterns(s0=s0, s2=s2, s5=s5, tx=tx), None


def _merge_pattern_section(
    defaults: Mapping[str, PatternList],
    updates: Any,
    *,
    uppercase_keys: bool,
) -> Dict[str, PatternList]:
    merged: Dict[str, PatternList] = dict(defaults)
    if not isinstance(updates, Mapping):
        return merged

    for raw_key, raw_patterns in updates.items():
        if not isinstance(raw_key, str):
            continue
        key = raw_key.strip().upper() if uppercase_keys else raw_key.strip()
        if not key:
            continue
        patterns = _as_pattern_list(raw_patterns)
        if patterns:
            merged[key] = patterns
    return merged


def _as_pattern_list(raw: Any) -> PatternList:
    if isinstance(raw, str):
        item = raw.strip()
        return (item,) if item else tuple()
    if not isinstance(raw, Sequence):
        return tuple()

    out = []
    for item in raw:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if text:
            out.append(text)
    return tuple(out)


def _merge_template_section(
    defaults: Mapping[str, str],
    updates: Any,
    *,
    uppercase_keys: bool,
) -> Dict[str, str]:
    merged: Dict[str, str] = dict(defaults)
    if not isinstance(updates, Mapping):
        return merged

    for raw_key, raw_value in updates.items():
        if not isinstance(raw_key, str):
            continue
        if not isinstance(raw_value, str):
            continue
        key = raw_key.strip().upper() if uppercase_keys else raw_key.strip()
        value = raw_value.strip()
        if not key or not value:
            continue
        merged[key] = value
    return merged
