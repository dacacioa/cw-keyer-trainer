from __future__ import annotations

from pathlib import Path

from core.config import load_config


def _write_yaml(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_load_config_migrates_fixed_tx_values_to_ranges(tmp_path: Path):
    cfg_path = tmp_path / "config.yaml"
    _write_yaml(
        cfg_path,
        """
encoder:
  wpm: 27.5
  tone_hz: 710.0
""".strip(),
    )

    cfg = load_config(cfg_path)

    assert cfg.encoder.wpm == 27.5
    assert cfg.encoder.tone_hz == 710.0
    assert cfg.encoder.wpm_out_start == 27.5
    assert cfg.encoder.wpm_out_end == 27.5
    assert cfg.encoder.tone_hz_out_start == 710.0
    assert cfg.encoder.tone_hz_out_end == 710.0


def test_load_config_sorts_out_ranges(tmp_path: Path):
    cfg_path = tmp_path / "config.yaml"
    _write_yaml(
        cfg_path,
        """
encoder:
  wpm_out_start: 35.0
  wpm_out_end: 20.0
  tone_hz_out_start: 900.0
  tone_hz_out_end: 500.0
""".strip(),
    )

    cfg = load_config(cfg_path)

    assert cfg.encoder.wpm_out_start == 20.0
    assert cfg.encoder.wpm_out_end == 35.0
    assert cfg.encoder.tone_hz_out_start == 500.0
    assert cfg.encoder.tone_hz_out_end == 900.0
