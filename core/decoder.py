from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional, Sequence, Tuple

import numpy as np

from .morse import MORSE_CODE, MORSE_DECODE


@dataclass
class CWDecoderConfig:
    sample_rate: int = 48000
    frame_ms: float = 10.0
    target_tone_hz: float = 650.0
    auto_tone: bool = False
    tone_search_min_hz: float = 300.0
    tone_search_max_hz: float = 1200.0
    threshold_on_mult: float = 4.0
    threshold_off_mult: float = 2.4
    agc_alpha: float = 0.03
    power_smooth_alpha: float = 1.0
    wpm_target: float = 20.0
    auto_wpm: bool = True
    dot_ms_min: float = 25.0
    dot_ms_max: float = 220.0
    min_key_down_ms: float = 12.0
    min_key_up_ms: float = 12.0
    min_key_down_dot_ratio: float = 0.0
    min_key_up_dot_ratio: float = 0.0
    dash_threshold_dots: float = 2.0
    gap_char_threshold_dots: float = 1.8
    gap_word_threshold_dots: float = 5.0
    message_gap_dots: float = 12.0
    message_gap_seconds: Optional[float] = None
    prosign_literal: str = "CAVE"

    @property
    def dot_seconds_fixed(self) -> float:
        return 1.2 / max(self.wpm_target, 1.0)


@dataclass
class DecoderStats:
    level_db: float = -120.0
    tone_hz: float = 0.0
    tone_power: float = 0.0
    noise_floor: float = 1e-8
    key_down: bool = False
    dot_ms: float = 60.0
    wpm_est: float = 20.0
    threshold_on: float = 0.0
    threshold_off: float = 0.0


class CWDecoder:
    """
    Streaming CW decoder based on tone-power keying detection.
    """

    def __init__(self, config: CWDecoderConfig):
        self.config = config
        self.frame_len = max(int(round(config.sample_rate * config.frame_ms / 1000.0)), 16)
        self.frame_duration = self.frame_len / float(config.sample_rate)
        self._buffer = np.zeros(0, dtype=np.float32)

        self._tone_hz = float(config.target_tone_hz)
        self._tone_update_every = 5
        self._tone_update_countdown = 0

        self._noise_floor = 1e-8
        self._tone_power_smooth = 0.0
        self._state_down = False
        self._state_duration = 0.0

        self._dot_estimate = float(config.dot_seconds_fixed)
        self._down_durations: Deque[float] = deque(maxlen=256)
        self._up_durations: Deque[float] = deque(maxlen=256)

        self._current_symbol = ""
        self._current_word = ""
        self._message_words: List[str] = []

        self._morse_decode = dict(MORSE_DECODE)
        self._register_configured_prosign(config.prosign_literal)

        self._gap_flushed_symbol = False
        self._gap_flushed_word = False
        self._gap_emitted_message = False

        self.stats = DecoderStats(
            tone_hz=self._tone_hz,
            dot_ms=self._dot_estimate * 1000.0,
            wpm_est=1.2 / self._dot_estimate,
        )

    def reset(self) -> None:
        self._buffer = np.zeros(0, dtype=np.float32)
        self._noise_floor = 1e-8
        self._tone_power_smooth = 0.0
        self._state_down = False
        self._state_duration = 0.0
        self._dot_estimate = float(self.config.dot_seconds_fixed)
        self._down_durations.clear()
        self._up_durations.clear()
        self._current_symbol = ""
        self._current_word = ""
        self._message_words.clear()
        self._gap_flushed_symbol = False
        self._gap_flushed_word = False
        self._gap_emitted_message = False

    def recalibrate(self) -> None:
        self._tone_hz = float(self.config.target_tone_hz)
        self._noise_floor = 1e-8
        self._tone_power_smooth = 0.0
        self._down_durations.clear()
        self._up_durations.clear()

    def process_samples(self, samples: np.ndarray) -> List[str]:
        if samples.size == 0:
            return []
        mono = _to_mono_float32(samples)
        self._buffer = np.concatenate([self._buffer, mono], dtype=np.float32)
        out_messages: List[str] = []

        while self._buffer.size >= self.frame_len:
            frame = self._buffer[: self.frame_len]
            self._buffer = self._buffer[self.frame_len :]
            self._process_frame(frame, out_messages)
        return out_messages

    def finalize(self) -> List[str]:
        out: List[str] = []
        self._flush_symbol()
        self._flush_word()
        msg = self._flush_message()
        if msg:
            out.append(msg)
        return out

    def decode_audio(self, samples: np.ndarray) -> str:
        messages: List[str] = []
        messages.extend(self.process_samples(samples))
        messages.extend(self.finalize())
        return " ".join(m for m in messages if m).strip()

    def _process_frame(self, frame: np.ndarray, out_messages: List[str]) -> None:
        frame = frame.astype(np.float32, copy=False)
        rms = float(np.sqrt(np.mean(frame * frame) + 1e-12))
        self.stats.level_db = 20.0 * np.log10(max(rms, 1e-12))

        if self.config.auto_tone:
            if self._tone_update_countdown <= 0:
                tone = _dominant_freq_fft(
                    frame,
                    self.config.sample_rate,
                    self.config.tone_search_min_hz,
                    self.config.tone_search_max_hz,
                )
                if tone is not None:
                    self._tone_hz = 0.8 * self._tone_hz + 0.2 * tone
                self._tone_update_countdown = self._tone_update_every
            else:
                self._tone_update_countdown -= 1

        tone_power_raw = _goertzel_power(frame, self.config.sample_rate, self._tone_hz)
        alpha_p = float(np.clip(self.config.power_smooth_alpha, 0.01, 1.0))
        if self._tone_power_smooth <= 0.0:
            self._tone_power_smooth = tone_power_raw
        else:
            self._tone_power_smooth = (1.0 - alpha_p) * self._tone_power_smooth + alpha_p * tone_power_raw
        tone_power = self._tone_power_smooth

        if not self._state_down:
            alpha = float(np.clip(self.config.agc_alpha, 0.001, 0.5))
            self._noise_floor = (1.0 - alpha) * self._noise_floor + alpha * tone_power

        threshold_on = max(self._noise_floor * self.config.threshold_on_mult, 1e-12)
        threshold_off = max(self._noise_floor * self.config.threshold_off_mult, 1e-12)

        if self._state_down:
            raw_down = tone_power >= threshold_off
        else:
            raw_down = tone_power >= threshold_on

        if raw_down == self._state_down:
            self._state_duration += self.frame_duration
        else:
            prev_state = self._state_down
            prev_duration = self._state_duration
            self._state_down = raw_down
            self._state_duration = self.frame_duration
            self._on_transition(prev_state, prev_duration)
            if self._state_down:
                self._gap_flushed_symbol = False
                self._gap_flushed_word = False
                self._gap_emitted_message = False

        if not self._state_down:
            self._handle_gap_progress(out_messages)

        self.stats.tone_hz = self._tone_hz
        self.stats.tone_power = tone_power
        self.stats.noise_floor = self._noise_floor
        self.stats.key_down = self._state_down
        self.stats.dot_ms = self._dot_estimate * 1000.0
        self.stats.wpm_est = 1.2 / max(self._dot_estimate, 1e-6)
        self.stats.threshold_on = threshold_on
        self.stats.threshold_off = threshold_off

    def _on_transition(self, prev_state_down: bool, duration: float) -> None:
        if duration <= 0.0:
            return
        dot_ref = max(self._dot_estimate, self.config.dot_ms_min / 1000.0)
        min_down = max(
            self.config.min_key_down_ms / 1000.0,
            float(np.clip(self.config.min_key_down_dot_ratio, 0.0, 1.0)) * dot_ref,
        )
        min_up = max(
            self.config.min_key_up_ms / 1000.0,
            float(np.clip(self.config.min_key_up_dot_ratio, 0.0, 1.0)) * dot_ref,
        )

        if prev_state_down:
            if duration < min_down:
                return
            self._down_durations.append(duration)
            self._maybe_update_dot_estimate()
            dot = self._dot_estimate
            dash_threshold = max(1.6, float(self.config.dash_threshold_dots)) * dot
            self._current_symbol += "." if duration < dash_threshold else "-"
            return

        if duration < min_up:
            return
        self._up_durations.append(duration)
        self._maybe_update_dot_estimate()
        self._classify_gap(duration)

    def _classify_gap(self, gap_seconds: float) -> None:
        dot = self._dot_estimate
        char_threshold = max(1.6, float(self.config.gap_char_threshold_dots)) * dot
        word_threshold = max(char_threshold + 0.8 * dot, float(self.config.gap_word_threshold_dots) * dot)
        if gap_seconds < char_threshold:
            return
        if gap_seconds < word_threshold:
            self._flush_symbol()
            return
        self._flush_symbol()
        self._flush_word()

    def _handle_gap_progress(self, out_messages: List[str]) -> None:
        dot = self._dot_estimate
        gap = self._state_duration
        char_threshold = max(1.6, float(self.config.gap_char_threshold_dots)) * dot
        word_threshold = max(char_threshold + 0.8 * dot, float(self.config.gap_word_threshold_dots) * dot)
        if gap >= char_threshold and not self._gap_flushed_symbol:
            self._flush_symbol()
            self._gap_flushed_symbol = True
        if gap >= word_threshold and not self._gap_flushed_word:
            self._flush_word()
            self._gap_flushed_word = True

        msg_gap = self._resolve_message_gap_seconds(dot)
        if gap >= msg_gap and not self._gap_emitted_message:
            msg = self._flush_message()
            if msg:
                out_messages.append(msg)
            self._gap_emitted_message = True

    def _resolve_message_gap_seconds(self, dot_seconds: float) -> float:
        sec = self.config.message_gap_seconds
        if sec is not None and sec > 0.0:
            return max(float(sec), self.frame_duration)
        return max(float(self.config.message_gap_dots) * dot_seconds, self.frame_duration)

    def _flush_symbol(self) -> None:
        if not self._current_symbol:
            return
        char = self._morse_decode.get(self._current_symbol, "")
        if char:
            self._current_word += char
        self._current_symbol = ""

    def _flush_word(self) -> None:
        if self._current_word:
            self._message_words.append(self._current_word)
            self._current_word = ""

    def _flush_message(self) -> str:
        if not self._message_words:
            return ""
        msg = " ".join(self._message_words).strip()
        self._message_words.clear()
        return msg

    def _maybe_update_dot_estimate(self) -> None:
        if not self.config.auto_wpm or len(self._down_durations) < 6:
            return
        down = np.array(self._down_durations, dtype=np.float32)
        down.sort()
        half = max(len(down) // 2, 1)
        short = down[:half]
        dot = float(np.median(short))

        dot_min = self.config.dot_ms_min / 1000.0
        dot_max = self.config.dot_ms_max / 1000.0
        dot = float(np.clip(dot, dot_min, dot_max))
        self._dot_estimate = 0.85 * self._dot_estimate + 0.15 * dot

    def _register_configured_prosign(self, literal: str) -> None:
        lit = "".join(ch for ch in literal.strip().upper() if ch.isalnum())
        if not lit:
            return
        pattern_parts: List[str] = []
        for ch in lit:
            code = MORSE_CODE.get(ch)
            if not code:
                return
            pattern_parts.append(code)
        pattern = "".join(pattern_parts)
        self._morse_decode[pattern] = f"<{lit}>"


def _to_mono_float32(samples: np.ndarray) -> np.ndarray:
    arr = np.asarray(samples, dtype=np.float32)
    if arr.ndim == 1:
        return arr
    if arr.ndim == 2:
        return arr.mean(axis=1, dtype=np.float32)
    return arr.reshape(-1).astype(np.float32, copy=False)


def _dominant_freq_fft(
    frame: np.ndarray,
    sample_rate: int,
    min_hz: float,
    max_hz: float,
) -> Optional[float]:
    n = frame.size
    if n < 32:
        return None
    win = np.hanning(n).astype(np.float32)
    spec = np.fft.rfft(frame * win)
    freqs = np.fft.rfftfreq(n, 1.0 / sample_rate)
    mask = (freqs >= min_hz) & (freqs <= max_hz)
    if not np.any(mask):
        return None
    mags = np.abs(spec[mask])
    if mags.size == 0:
        return None
    idx = int(np.argmax(mags))
    tone = float(freqs[mask][idx])
    return tone


def _goertzel_power(frame: np.ndarray, sample_rate: int, freq_hz: float) -> float:
    n = frame.size
    if n == 0:
        return 0.0
    omega = 2.0 * np.pi * freq_hz / sample_rate
    coeff = 2.0 * np.cos(omega)
    q0 = 0.0
    q1 = 0.0
    q2 = 0.0
    for sample in frame:
        q0 = coeff * q1 - q2 + float(sample)
        q2 = q1
        q1 = q0
    power = q1 * q1 + q2 * q2 - coeff * q1 * q2
    return float(max(power, 0.0) / max(n * n, 1))
