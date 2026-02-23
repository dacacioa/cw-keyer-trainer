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
    input_mode: str = "audio"  # audio | keyboard


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
    encoder_raw = raw.get("encoder", {})
    _apply_dataclass_updates(cfg.encoder, encoder_raw)
    _apply_dataclass_updates(cfg.qso, raw.get("qso", {}))
    cfg.qso.max_stations = max(1, int(cfg.qso.max_stations))
    cfg.qso.p2p_probability = max(0.0, min(1.0, float(cfg.qso.p2p_probability)))

    # Backward compatibility: old configs only had fixed wpm/tone_hz.
    has_wpm_start = "wpm_out_start" in encoder_raw
    has_wpm_end = "wpm_out_end" in encoder_raw
    if not has_wpm_start and not has_wpm_end:
        cfg.encoder.wpm_out_start = cfg.encoder.wpm
        cfg.encoder.wpm_out_end = cfg.encoder.wpm
    elif not has_wpm_start:
        cfg.encoder.wpm_out_start = cfg.encoder.wpm_out_end
    elif not has_wpm_end:
        cfg.encoder.wpm_out_end = cfg.encoder.wpm_out_start
    if cfg.encoder.wpm_out_start > cfg.encoder.wpm_out_end:
        cfg.encoder.wpm_out_start, cfg.encoder.wpm_out_end = (
            cfg.encoder.wpm_out_end,
            cfg.encoder.wpm_out_start,
        )

    has_tone_start = "tone_hz_out_start" in encoder_raw
    has_tone_end = "tone_hz_out_end" in encoder_raw
    if not has_tone_start and not has_tone_end:
        cfg.encoder.tone_hz_out_start = cfg.encoder.tone_hz
        cfg.encoder.tone_hz_out_end = cfg.encoder.tone_hz
    elif not has_tone_start:
        cfg.encoder.tone_hz_out_start = cfg.encoder.tone_hz_out_end
    elif not has_tone_end:
        cfg.encoder.tone_hz_out_end = cfg.encoder.tone_hz_out_start
    if cfg.encoder.tone_hz_out_start > cfg.encoder.tone_hz_out_end:
        cfg.encoder.tone_hz_out_start, cfg.encoder.tone_hz_out_end = (
            cfg.encoder.tone_hz_out_end,
            cfg.encoder.tone_hz_out_start,
        )

    # Keep sample rates aligned unless explicitly diverging in YAML.
    if "sample_rate" not in raw.get("decoder", {}):
        cfg.decoder.sample_rate = cfg.audio.sample_rate
    if "sample_rate" not in raw.get("encoder", {}):
        cfg.encoder.sample_rate = cfg.audio.sample_rate

    mode = str(cfg.audio.input_mode or "audio").strip().lower()
    cfg.audio.input_mode = mode if mode in {"audio", "keyboard"} else "audio"

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
