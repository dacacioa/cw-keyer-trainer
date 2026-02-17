from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np

from .morse import token_to_morse_letters, tokenize_text

try:
    import sounddevice as sd
except Exception:  # pragma: no cover - optional runtime dependency
    sd = None


Pulse = Tuple[bool, float]  # (key_down, duration_seconds)


@dataclass
class CWEncoderConfig:
    sample_rate: int = 48000
    tone_hz: float = 650.0
    wpm: float = 20.0
    farnsworth_wpm: Optional[float] = None
    volume: float = 0.25
    attack_ms: float = 4.0
    release_ms: float = 6.0
    prosign_tokens: Tuple[str, ...] = ("KN",)

    @property
    def dot_seconds(self) -> float:
        return 1.2 / max(self.wpm, 1.0)

    @property
    def space_dot_seconds(self) -> float:
        if self.farnsworth_wpm and 1.0 <= self.farnsworth_wpm < self.wpm:
            return 1.2 / self.farnsworth_wpm
        return self.dot_seconds


class CWEncoder:
    def __init__(self, config: CWEncoderConfig):
        self.config = config

    def text_to_pulses(self, text: str) -> List[Pulse]:
        tokens = tokenize_text(text)
        pulses: List[Pulse] = []
        dot = self.config.dot_seconds
        char_gap = 3.0 * self.config.space_dot_seconds
        word_gap = 7.0 * self.config.space_dot_seconds
        prosign_tokens = {tok.upper() for tok in self.config.prosign_tokens}

        for token_idx, token in enumerate(tokens):
            letters = token_to_morse_letters(token)
            if not letters:
                continue

            is_prosign = (token.startswith("<") and token.endswith(">")) or (token in prosign_tokens)
            letter_gap = dot if is_prosign else char_gap
            for letter_idx, morse in enumerate(letters):
                for element_idx, element in enumerate(morse):
                    pulses.append((True, dot if element == "." else 3.0 * dot))
                    if element_idx < len(morse) - 1:
                        pulses.append((False, dot))
                if letter_idx < len(letters) - 1:
                    pulses.append((False, letter_gap))

            if token_idx < len(tokens) - 1:
                pulses.append((False, word_gap))

        return _merge_same_state_pulses(pulses)

    def encode_to_audio(self, text: str) -> np.ndarray:
        pulses = self.text_to_pulses(text)
        if not pulses:
            return np.zeros(1, dtype=np.float32)

        sr = self.config.sample_rate
        tone = self.config.tone_hz
        volume = float(np.clip(self.config.volume, 0.0, 1.0))
        attack_samples = max(int(sr * self.config.attack_ms / 1000.0), 0)
        release_samples = max(int(sr * self.config.release_ms / 1000.0), 0)

        chunks: List[np.ndarray] = []
        phase = 0.0
        phase_step = 2.0 * np.pi * tone / sr

        for is_on, duration_sec in pulses:
            n = max(int(round(duration_sec * sr)), 1)
            if not is_on:
                chunks.append(np.zeros(n, dtype=np.float32))
                continue

            t = np.arange(n, dtype=np.float32)
            wave = np.sin(phase + phase_step * t, dtype=np.float32)
            phase = float((phase + phase_step * n) % (2.0 * np.pi))

            env = np.ones(n, dtype=np.float32)
            a = min(attack_samples, n)
            r = min(release_samples, n)
            if a > 0:
                env[:a] = np.linspace(0.0, 1.0, a, endpoint=False, dtype=np.float32)
            if r > 0:
                env[-r:] *= np.linspace(1.0, 0.0, r, endpoint=False, dtype=np.float32)
            if a + r > n and n > 1:
                mid = n // 2
                env[:mid] = np.linspace(0.0, 1.0, mid, endpoint=False, dtype=np.float32)
                env[mid:] = np.linspace(1.0, 0.0, n - mid, endpoint=False, dtype=np.float32)

            chunks.append((wave * env * volume).astype(np.float32))

        audio = np.concatenate(chunks, dtype=np.float32)
        # tail silence for decoder flush / playback comfort
        tail = np.zeros(max(int(0.3 * sr), 1), dtype=np.float32)
        return np.concatenate([audio, tail], dtype=np.float32)

    def play_text(self, text: str, device: Optional[int] = None, blocking: bool = True) -> None:
        if sd is None:
            raise RuntimeError("sounddevice is not installed; cannot play audio.")
        audio = self.encode_to_audio(text)
        sd.play(audio, samplerate=self.config.sample_rate, device=device, blocking=blocking)


def _merge_same_state_pulses(pulses: Sequence[Pulse]) -> List[Pulse]:
    if not pulses:
        return []
    merged: List[Pulse] = [pulses[0]]
    for state, duration in pulses[1:]:
        prev_state, prev_dur = merged[-1]
        if prev_state == state:
            merged[-1] = (state, prev_dur + duration)
        else:
            merged.append((state, duration))
    return merged
