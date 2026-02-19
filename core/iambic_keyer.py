from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np


@dataclass
class IambicAKeyerConfig:
    sample_rate: int = 48000
    wpm: float = 20.0
    tone_hz: float = 600.0
    volume: float = 0.25
    attack_ms: float = 2.0
    release_ms: float = 3.0

    @property
    def dot_seconds(self) -> float:
        return 1.2 / max(self.wpm, 1.0)


class IambicAKeyer:
    """
    Real-time iambic mode A keyer.

    Paddle mapping:
    - dit paddle (left): '.'
    - dah paddle (right): '-'

    Mode A behavior:
    - Single paddle held: repeats its own element continuously.
    - Both paddles held: alternates dot/dash starting from the last element sent.
    - Releasing both paddles stops after the element currently in progress.
    """

    def __init__(self, config: IambicAKeyerConfig):
        self.config = config
        self.dit_pressed = False
        self.dah_pressed = False

        self._phase = "idle"  # idle, mark, space
        self._remaining_samples = 0
        self._current_element: Optional[str] = None
        self._last_element_sent: Optional[str] = None
        self._iambic_active = False
        self._tone_phase = 0.0
        self._started_elements: List[str] = []
        self._mark_elapsed_samples = 0
        self._mark_total_samples = 0

    def reset(self) -> None:
        self.dit_pressed = False
        self.dah_pressed = False
        self._phase = "idle"
        self._remaining_samples = 0
        self._current_element = None
        self._iambic_active = False
        self._tone_phase = 0.0
        self._started_elements.clear()
        self._mark_elapsed_samples = 0
        self._mark_total_samples = 0

    @property
    def key_down(self) -> bool:
        return self._phase == "mark"

    def set_paddles(self, *, dit: bool, dah: bool) -> None:
        self.dit_pressed = bool(dit)
        self.dah_pressed = bool(dah)

    def render_seconds(self, duration_sec: float) -> np.ndarray:
        n = max(int(round(max(0.0, float(duration_sec)) * self.config.sample_rate)), 0)
        return self.render_samples(n)

    def render_samples(self, num_samples: int) -> np.ndarray:
        if num_samples <= 0:
            return np.zeros(0, dtype=np.float32)

        out = np.zeros(num_samples, dtype=np.float32)
        amp = float(np.clip(self.config.volume, 0.0, 1.0))
        sr = max(int(self.config.sample_rate), 1)
        tone_hz = max(float(self.config.tone_hz), 1.0)
        tone_step = 2.0 * np.pi * tone_hz / float(sr)

        pos = 0
        while pos < num_samples:
            if self._phase == "idle":
                if not self._start_next_element():
                    break

            seg = min(self._remaining_samples, num_samples - pos)
            if seg <= 0:
                self._advance_phase()
                continue

            if self._phase == "mark":
                t = np.arange(seg, dtype=np.float32)
                wave = np.sin(self._tone_phase + tone_step * t).astype(np.float32, copy=False)
                env = self._mark_envelope(seg)
                out[pos : pos + seg] = wave * env * amp
                self._tone_phase = float((self._tone_phase + tone_step * seg) % (2.0 * np.pi))
                self._mark_elapsed_samples += seg

            pos += seg
            self._remaining_samples -= seg
            if self._remaining_samples <= 0:
                self._advance_phase()

        return out

    def pop_started_elements(self) -> List[str]:
        out = list(self._started_elements)
        self._started_elements.clear()
        return out

    def _dot_samples(self) -> int:
        return max(int(round(self.config.dot_seconds * self.config.sample_rate)), 1)

    def _dash_samples(self) -> int:
        return max(3 * self._dot_samples(), 1)

    def _start_next_element(self) -> bool:
        element = self._choose_next_element()
        if element is None:
            self._phase = "idle"
            self._remaining_samples = 0
            self._current_element = None
            return False

        self._current_element = element
        self._phase = "mark"
        self._remaining_samples = self._dot_samples() if element == "." else self._dash_samples()
        self._mark_elapsed_samples = 0
        self._mark_total_samples = self._remaining_samples
        self._started_elements.append(element)
        return True

    def _advance_phase(self) -> None:
        if self._phase == "mark":
            self._last_element_sent = self._current_element
            self._phase = "space"
            self._remaining_samples = self._dot_samples()
            self._mark_elapsed_samples = 0
            self._mark_total_samples = 0
            return
        if self._phase == "space":
            self._phase = "idle"
            self._remaining_samples = 0
            self._current_element = None

    def _choose_next_element(self) -> Optional[str]:
        dit = self.dit_pressed
        dah = self.dah_pressed

        if dit and not dah:
            self._iambic_active = False
            return "."
        if dah and not dit:
            self._iambic_active = False
            return "-"
        if dit and dah:
            if not self._iambic_active:
                self._iambic_active = True
                if self._last_element_sent in (".", "-"):
                    return self._last_element_sent
                return "."
            if self._last_element_sent == ".":
                return "-"
            if self._last_element_sent == "-":
                return "."
            return "."

        self._iambic_active = False
        return None

    def _mark_envelope(self, seg: int) -> np.ndarray:
        n = max(int(seg), 1)
        env = np.ones(n, dtype=np.float32)
        sr = max(int(self.config.sample_rate), 1)
        attack_samples = max(int(round(sr * max(float(self.config.attack_ms), 0.0) / 1000.0)), 0)
        release_samples = max(int(round(sr * max(float(self.config.release_ms), 0.0) / 1000.0)), 0)
        if attack_samples <= 0 and release_samples <= 0:
            return env

        idx = np.arange(n, dtype=np.float32) + float(self._mark_elapsed_samples)
        if attack_samples > 0:
            env *= np.clip((idx + 1.0) / float(attack_samples), 0.0, 1.0)
        if release_samples > 0 and self._mark_total_samples > 0:
            rem = float(self._mark_total_samples) - idx
            env *= np.clip(rem / float(release_samples), 0.0, 1.0)
        return env
