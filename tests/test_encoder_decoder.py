from __future__ import annotations

from difflib import SequenceMatcher

import numpy as np

from core.decoder import CWDecoder, CWDecoderConfig
from core.encoder import CWEncoder, CWEncoderConfig


def _norm(s: str) -> str:
    return " ".join(s.upper().split())


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def test_roundtrip_precision_95_percent_15_25_wpm():
    message = "CQ CQ POTA DE EA4XYZ EA4XYZ K N1MM UR 5NN 5NN <CAVE>"
    for wpm in (15.0, 20.0, 25.0):
        enc = CWEncoder(
            CWEncoderConfig(
                sample_rate=16000,
                tone_hz=700.0,
                wpm=wpm,
                volume=0.9,
                attack_ms=2.0,
                release_ms=3.0,
            )
        )
        audio = enc.encode_to_audio(message)

        dec = CWDecoder(
            CWDecoderConfig(
                sample_rate=16000,
                frame_ms=10.0,
                target_tone_hz=700.0,
                auto_tone=False,
                wpm_target=wpm,
                auto_wpm=False,
                threshold_on_mult=2.5,
                threshold_off_mult=1.8,
                message_gap_dots=8.0,
            )
        )
        recovered = dec.decode_audio(audio)
        assert _ratio(message, recovered) >= 0.95, (wpm, recovered)


def test_prosign_cave_roundtrip():
    message = "N1MM UR 5NN 5NN <CAVE>"
    enc = CWEncoder(CWEncoderConfig(sample_rate=16000, tone_hz=620.0, wpm=18.0, volume=0.8))
    dec = CWDecoder(
        CWDecoderConfig(
            sample_rate=16000,
            frame_ms=10.0,
            target_tone_hz=620.0,
            auto_tone=False,
            wpm_target=18.0,
            auto_wpm=False,
            threshold_on_mult=2.5,
            threshold_off_mult=1.7,
            message_gap_dots=8.0,
        )
    )
    recovered = dec.decode_audio(enc.encode_to_audio(message))
    assert "<CAVE>" in _norm(recovered)


def test_kn_is_sent_as_prosign_contiguous_gap():
    enc = CWEncoder(CWEncoderConfig(sample_rate=16000, wpm=20.0, tone_hz=600.0))
    pulses = enc.text_to_pulses("KN")
    dot = enc.config.dot_seconds
    off_durations = [dur for is_on, dur in pulses if not is_on]
    # KN as prosign should not contain a 3-dot inter-letter gap.
    assert not any(abs(d - (3.0 * dot)) < 0.2 * dot for d in off_durations)


def test_configured_prosign_token_is_sent_contiguous():
    enc = CWEncoder(
        CWEncoderConfig(
            sample_rate=16000,
            wpm=20.0,
            tone_hz=600.0,
            prosign_tokens=("BK",),
        )
    )
    pulses = enc.text_to_pulses("BK")
    dot = enc.config.dot_seconds
    off_durations = [dur for is_on, dur in pulses if not is_on]
    assert not any(abs(d - (3.0 * dot)) < 0.2 * dot for d in off_durations)


def test_farnsworth_slows_spacing_but_keeps_character_speed():
    cfg = CWEncoderConfig(sample_rate=16000, wpm=25.0, farnsworth_wpm=10.0, tone_hz=600.0)
    enc = CWEncoder(cfg)

    assert abs(cfg.dot_seconds - (1.2 / 25.0)) < 1e-9
    assert abs(cfg.space_dot_seconds - (1.2 / 10.0)) < 1e-9

    pulses = enc.text_to_pulses("EE")
    off_durations = [dur for is_on, dur in pulses if not is_on]
    target_gap = 3.0 * cfg.space_dot_seconds
    assert any(abs(d - target_gap) < 0.2 * cfg.space_dot_seconds for d in off_durations)

    cfg_no_effect = CWEncoderConfig(sample_rate=16000, wpm=20.0, farnsworth_wpm=25.0, tone_hz=600.0)
    assert cfg_no_effect.space_dot_seconds == cfg_no_effect.dot_seconds


def test_noise_floor_calibration_from_samples_updates_thresholds():
    cfg = CWDecoderConfig(
        sample_rate=16000,
        frame_ms=10.0,
        target_tone_hz=700.0,
        auto_tone=False,
        threshold_on_mult=4.0,
        threshold_off_mult=2.4,
        auto_wpm=False,
    )
    dec = CWDecoder(cfg)
    rng = np.random.default_rng(12345)
    noise = rng.normal(0.0, 0.02, int(cfg.sample_rate * 2.0)).astype(np.float32)
    floor = dec.calibrate_noise_floor_from_samples(noise, percentile=75.0)

    assert floor > 1e-12
    assert dec.stats.noise_floor == floor
    assert dec.stats.threshold_on == max(floor * cfg.threshold_on_mult, 1e-12)
    assert dec.stats.threshold_off == max(floor * cfg.threshold_off_mult, 1e-12)
