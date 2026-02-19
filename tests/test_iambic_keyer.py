from __future__ import annotations

from core.iambic_keyer import IambicAKeyer, IambicAKeyerConfig


def _samples_for_dots(cfg: IambicAKeyerConfig, dots: float) -> int:
    return int(round(cfg.sample_rate * cfg.dot_seconds * dots))


def test_single_dit_paddle_repeats_dits_while_held():
    cfg = IambicAKeyerConfig(sample_rate=8000, wpm=20.0, tone_hz=600.0, volume=0.8)
    keyer = IambicAKeyer(cfg)
    keyer.set_paddles(dit=True, dah=False)

    keyer.render_samples(_samples_for_dots(cfg, 12.0))
    started = keyer.pop_started_elements()

    assert len(started) >= 4
    assert all(el == "." for el in started)


def test_single_dah_paddle_repeats_dahs_while_held():
    cfg = IambicAKeyerConfig(sample_rate=8000, wpm=20.0, tone_hz=600.0, volume=0.8)
    keyer = IambicAKeyer(cfg)
    keyer.set_paddles(dit=False, dah=True)

    keyer.render_samples(_samples_for_dots(cfg, 20.0))
    started = keyer.pop_started_elements()

    assert len(started) >= 3
    assert all(el == "-" for el in started)


def test_iambic_alternation_starts_with_last_element_sent():
    cfg = IambicAKeyerConfig(sample_rate=8000, wpm=18.0, tone_hz=650.0, volume=0.8)
    keyer = IambicAKeyer(cfg)

    keyer.set_paddles(dit=False, dah=True)
    keyer.render_samples(_samples_for_dots(cfg, 5.0))
    keyer.set_paddles(dit=False, dah=False)
    keyer.render_samples(_samples_for_dots(cfg, 2.0))
    keyer.pop_started_elements()

    keyer.set_paddles(dit=True, dah=True)
    keyer.render_samples(_samples_for_dots(cfg, 18.0))
    seq = keyer.pop_started_elements()

    assert seq[:4] == ["-", ".", "-", "."]


def test_iambic_mode_a_stops_without_extra_element_after_release():
    cfg = IambicAKeyerConfig(sample_rate=8000, wpm=20.0, tone_hz=700.0, volume=0.8)
    keyer = IambicAKeyer(cfg)

    # Prime last element to '.' so squeeze starts with dit.
    keyer.set_paddles(dit=True, dah=False)
    keyer.render_samples(_samples_for_dots(cfg, 3.0))
    keyer.set_paddles(dit=False, dah=False)
    keyer.render_samples(_samples_for_dots(cfg, 2.0))
    keyer.pop_started_elements()

    keyer.set_paddles(dit=True, dah=True)
    # First dit + gap + half of following dah.
    keyer.render_samples(_samples_for_dots(cfg, 3.5))
    keyer.set_paddles(dit=False, dah=False)
    keyer.render_samples(_samples_for_dots(cfg, 12.0))
    seq = keyer.pop_started_elements()

    assert seq == [".", "-"]
