from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from .decoder import CWDecoderConfig
from .encoder import CWEncoderConfig
from .qso_state_machine import QSOConfig


@dataclass
class AudioRuntimeConfig:
    sample_rate: int = 48000
    input_device: Optional[int] = None
    output_device: Optional[int] = None
    blocksize: int = 1024
    channels: int = 1


@dataclass
class AppConfig:
    audio: AudioRuntimeConfig = field(default_factory=AudioRuntimeConfig)
    decoder: CWDecoderConfig = field(default_factory=CWDecoderConfig)
    encoder: CWEncoderConfig = field(default_factory=CWEncoderConfig)
    qso: QSOConfig = field(default_factory=QSOConfig)


def load_config(path: str | Path) -> AppConfig:
    p = Path(path)
    if not p.exists():
        cfg = AppConfig()
        save_config(p, cfg)
        return cfg

    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    cfg = AppConfig()

    _apply_dataclass_updates(cfg.audio, raw.get("audio", {}))
    _apply_dataclass_updates(cfg.decoder, raw.get("decoder", {}))
    _apply_dataclass_updates(cfg.encoder, raw.get("encoder", {}))
    _apply_dataclass_updates(cfg.qso, raw.get("qso", {}))

    # Keep sample rates aligned unless explicitly diverging in YAML.
    if "sample_rate" not in raw.get("decoder", {}):
        cfg.decoder.sample_rate = cfg.audio.sample_rate
    if "sample_rate" not in raw.get("encoder", {}):
        cfg.encoder.sample_rate = cfg.audio.sample_rate

    return cfg


def save_config(path: str | Path, config: AppConfig) -> None:
    payload = {
        "audio": asdict(config.audio),
        "decoder": asdict(config.decoder),
        "encoder": asdict(config.encoder),
        "qso": asdict(config.qso),
    }
    p = Path(path)
    p.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=False), encoding="utf-8")


def _apply_dataclass_updates(target: Any, updates: Dict[str, Any]) -> None:
    for key, value in updates.items():
        if hasattr(target, key):
            setattr(target, key, value)
