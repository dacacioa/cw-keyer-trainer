from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from core.qso_state_machine import QSOConfig, QSOState, QSOStateMachine


def _cfg(**kwargs) -> QSOConfig:
    base = QSOConfig(
        my_call="EA3IPX",
        other_call="N1MM",
        use_prosigns=False,
        prosign_literal="KN",
        max_stations=1,
        exchange_patterns_file=None,
    )
    for k, v in kwargs.items():
        setattr(base, k, v)
    return base


def test_s0_requires_de_token():
    sm = QSOStateMachine(_cfg())
    res = sm.process_text("CQ POTA EA3IPX K")
    assert not res.accepted
    assert sm.state == QSOState.S0_IDLE
    assert any("DE" in err for err in res.errors)


def test_valid_cq_moves_to_s2_and_single_call_when_max_stations_is_1():
    sm = QSOStateMachine(_cfg(max_stations=1))
    res = sm.process_text("CQ POTA DE EA3IPX K")
    assert res.accepted
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL
    assert res.replies == ["N1MM N1MM"]


def test_direct_qso_flow_success_single_station():
    sm = QSOStateMachine(_cfg(max_stations=1))
    assert sm.process_text("CQ POTA DE EA3IPX K").accepted

    r2 = sm.process_text("N1MM 5NN 5NN")
    assert r2.accepted
    assert r2.replies == ["KN UR 5NN 5NN TU 73 KN"]
    assert sm.state == QSOState.S5_WAIT_FINAL

    r5 = sm.process_text("73 EE")
    assert r5.accepted
    assert r5.replies == ["EE"]
    assert sm.state == QSOState.S0_IDLE
    assert len(sm.completions) == 1


def test_s2_accepts_rst_with_new_digit_ranges():
    sm = QSOStateMachine(_cfg(max_stations=1))
    assert sm.process_text("CQ POTA DE EA3IPX K").accepted

    r2 = sm.process_text("N1MM 57N 519")
    assert r2.accepted
    assert sm.state == QSOState.S5_WAIT_FINAL


def test_s2_rejects_rst_outside_new_digit_ranges():
    sm = QSOStateMachine(_cfg(max_stations=1))
    assert sm.process_text("CQ POTA DE EA3IPX K").accepted

    r2 = sm.process_text("N1MM 6NN 5NN")
    assert not r2.accepted
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL


def test_p2p_station_uses_alias_and_adds_my_ref_in_s2_and_s5():
    sm = QSOStateMachine(_cfg(max_stations=2, p2p_probability=1.0, my_park_ref="EA-8888"))
    sm.set_other_call_pool(["EA1AFV", "EA3IMR"])
    sm.set_park_ref_pool(["US-1234"])

    with patch("core.qso_state_machine.random.randint", return_value=2), patch(
        "core.qso_state_machine.random.sample",
        return_value=["EA1AFV", "EA3IMR"],
    ), patch("core.qso_state_machine.random.random", return_value=0.0), patch(
        "core.qso_state_machine.random.choice",
        side_effect=["EA3IMR", "US-1234"],
    ), patch("core.qso_state_machine.random.shuffle", lambda seq: None):
        r0 = sm.process_text("CQ POTA DE EA3IPX K")

    assert r0.accepted
    assert r0.replies == ["P2P P2P", "EA1AFV EA1AFV"]
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL

    r2 = sm.process_text("P2P")
    assert r2.accepted
    assert r2.replies == ["KN EA3IMR EA3IMR MY REF US1234 US1234 73 KN"]
    assert sm.state == QSOState.S5_WAIT_FINAL

    r5 = sm.process_text("EA3IMR EA3IPX MY REF EA-8888 EA-8888")
    assert r5.accepted
    assert r5.replies == ["EE", "EA1AFV EA1AFV"]
    assert sm.completions[-1].other_call == "EA3IMR (P2P) US-1234"


def test_p2p_with_allow_tu_requires_tu_in_s5_and_adds_tu_in_s2_reply():
    sm = QSOStateMachine(
        _cfg(
            max_stations=1,
            p2p_probability=1.0,
            my_park_ref="EA-1234",
            allow_tu=True,
            use_prosigns=True,
            prosign_literal="BK",
        )
    )
    sm.set_other_call_pool(["EA1AFV"])
    sm.set_park_ref_pool(["US-0001"])

    with patch("core.qso_state_machine.random.randint", return_value=1), patch(
        "core.qso_state_machine.random.sample",
        return_value=["EA1AFV"],
    ), patch("core.qso_state_machine.random.random", return_value=0.0), patch(
        "core.qso_state_machine.random.choice",
        side_effect=["EA1AFV", "US-0001"],
    ), patch("core.qso_state_machine.random.shuffle", lambda seq: None):
        sm.process_text("CQ POTA DE EA3IPX K")

    r2 = sm.process_text("P2P")
    assert r2.accepted
    assert r2.replies == ["BK EA1AFV EA1AFV MY REF US0001 US0001 TU 73 BK"]
    assert sm.state == QSOState.S5_WAIT_FINAL

    r5_bad = sm.process_text("BK EA1AFV EA3IPX MY REF EA-1234 EA-1234 73 BK")
    assert not r5_bad.accepted
    assert sm.state == QSOState.S5_WAIT_FINAL

    r5 = sm.process_text("BK EA1AFV EA3IPX MY REF EA-1234 EA-1234 TU 73 BK")
    assert r5.accepted
    assert sm.state == QSOState.S0_IDLE


def test_p2p_can_be_applied_to_post_qso_incoming_when_mode_is_pota():
    sm = QSOStateMachine(
        _cfg(
            max_stations=1,
            p2p_probability=1.0,
            my_park_ref="EA-7777",
            auto_incoming_after_qso=True,
            auto_incoming_probability=1.0,
        )
    )
    sm.set_other_call_pool(["EA1AFV"])
    sm.set_park_ref_pool(["US-1111"])

    with patch("core.qso_state_machine.random.randint", side_effect=[1, 1]), patch(
        "core.qso_state_machine.random.sample",
        side_effect=[["EA1AFV"], ["EA1AFV"]],
    ), patch("core.qso_state_machine.random.random", return_value=0.0), patch(
        "core.qso_state_machine.random.choice",
        side_effect=["EA1AFV", "US-1111", "EA1AFV"],
    ), patch("core.qso_state_machine.random.shuffle", lambda seq: None):
        sm.process_text("CQ POTA DE EA3IPX K")
        sm.process_text("P2P")
        r5 = sm.process_text("EA1AFV EA3IPX MY REF EA-7777 EA-7777")

    assert r5.accepted
    assert r5.replies == ["EE", "P2P P2P"]
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL


def test_s5_question_mark_repeats_last_transmission_in_normal_qso():
    sm = QSOStateMachine(_cfg(max_stations=1))
    assert sm.process_text("CQ POTA DE EA3IPX K").accepted
    assert sm.process_text("N1MM 5NN 5NN").accepted
    assert sm.state == QSOState.S5_WAIT_FINAL

    r_repeat = sm.process_text("?")
    assert r_repeat.accepted
    assert r_repeat.replies == ["KN UR 5NN 5NN TU 73 KN"]
    assert sm.state == QSOState.S5_WAIT_FINAL

    r5 = sm.process_text("73 EE")
    assert r5.accepted
    assert sm.state == QSOState.S0_IDLE


def test_s5_question_mark_repeats_last_transmission_in_p2p_qso():
    sm = QSOStateMachine(_cfg(max_stations=1, p2p_probability=1.0))
    sm.set_other_call_pool(["EA1AFV"])
    sm.set_park_ref_pool(["US-0001"])

    with patch("core.qso_state_machine.random.randint", return_value=1), patch(
        "core.qso_state_machine.random.sample",
        return_value=["EA1AFV"],
    ), patch("core.qso_state_machine.random.random", return_value=0.0), patch(
        "core.qso_state_machine.random.choice",
        side_effect=["EA1AFV", "US-0001"],
    ), patch("core.qso_state_machine.random.shuffle", lambda seq: None):
        assert sm.process_text("CQ POTA DE EA3IPX K").accepted

    r2 = sm.process_text("P2P")
    assert r2.accepted
    assert sm.state == QSOState.S5_WAIT_FINAL

    r_repeat = sm.process_text("?")
    assert r_repeat.accepted
    assert r_repeat.replies == ["KN EA1AFV EA1AFV MY REF US0001 US0001 73 KN"]
    assert sm.state == QSOState.S5_WAIT_FINAL


def test_s5_p2p_call_query_repeats_calling_station_callsign():
    sm = QSOStateMachine(_cfg(max_stations=1, p2p_probability=1.0))
    sm.set_other_call_pool(["EA1AFV"])
    sm.set_park_ref_pool(["US-0001"])

    with patch("core.qso_state_machine.random.randint", return_value=1), patch(
        "core.qso_state_machine.random.sample",
        return_value=["EA1AFV"],
    ), patch("core.qso_state_machine.random.random", return_value=0.0), patch(
        "core.qso_state_machine.random.choice",
        side_effect=["EA1AFV", "US-0001"],
    ), patch("core.qso_state_machine.random.shuffle", lambda seq: None):
        assert sm.process_text("CQ POTA DE EA3IPX K").accepted

    assert sm.process_text("P2P").accepted
    r_call = sm.process_text("CALL?")
    assert r_call.accepted
    assert r_call.replies == ["EA1AFV EA1AFV"]
    assert sm.state == QSOState.S5_WAIT_FINAL


def test_s5_p2p_ref_query_repeats_park_reference_without_dash():
    sm = QSOStateMachine(_cfg(max_stations=1, p2p_probability=1.0))
    sm.set_other_call_pool(["EA1AFV"])
    sm.set_park_ref_pool(["US-0001"])

    with patch("core.qso_state_machine.random.randint", return_value=1), patch(
        "core.qso_state_machine.random.sample",
        return_value=["EA1AFV"],
    ), patch("core.qso_state_machine.random.random", return_value=0.0), patch(
        "core.qso_state_machine.random.choice",
        side_effect=["EA1AFV", "US-0001"],
    ), patch("core.qso_state_machine.random.shuffle", lambda seq: None):
        assert sm.process_text("CQ POTA DE EA3IPX K").accepted

    assert sm.process_text("P2P").accepted
    r_ref = sm.process_text("REF?")
    assert r_ref.accepted
    assert r_ref.replies == ["US0001 US0001"]
    assert sm.state == QSOState.S5_WAIT_FINAL

def test_full_call_query_selects_station_and_sends_rr():
    sm = QSOStateMachine(_cfg(max_stations=2))
    sm.set_other_call_pool(["EA1AFV", "EA3IMR"])

    with patch("core.qso_state_machine.random.randint", return_value=2), patch(
        "core.qso_state_machine.random.sample",
        return_value=["EA1AFV", "EA3IMR"],
    ), patch("core.qso_state_machine.random.shuffle", lambda seq: None):
        sm.process_text("CQ POTA DE EA3IPX K")

    r = sm.process_text("EA3IMR?")
    assert r.accepted
    assert r.replies == ["RR"]
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL

    # After RR, report may omit the callsign.
    r2 = sm.process_text("5NN 5NN")
    assert r2.accepted
    assert sm.state == QSOState.S5_WAIT_FINAL


def test_partial_query_replies_only_matching_station():
    sm = QSOStateMachine(_cfg(max_stations=2))
    sm.set_other_call_pool(["EA1AFV", "EA3IMR"])

    with patch("core.qso_state_machine.random.randint", return_value=2), patch(
        "core.qso_state_machine.random.sample",
        return_value=["EA1AFV", "EA3IMR"],
    ), patch("core.qso_state_machine.random.shuffle", lambda seq: None):
        sm.process_text("CQ POTA DE EA3IPX K")

    r = sm.process_text("EA3?")
    assert r.accepted
    assert r.replies == ["EA3IMR EA3IMR"]
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL


def test_partial_query_prefix_can_match_multiple():
    sm = QSOStateMachine(_cfg(max_stations=2))
    sm.set_other_call_pool(["EA1AFV", "EA3IMR"])

    with patch("core.qso_state_machine.random.randint", return_value=2), patch(
        "core.qso_state_machine.random.sample",
        return_value=["EA1AFV", "EA3IMR"],
    ), patch("core.qso_state_machine.random.shuffle", lambda seq: None):
        sm.process_text("CQ POTA DE EA3IPX K")

    r = sm.process_text("EA?")
    assert r.accepted
    assert sorted(r.replies) == sorted(["EA1AFV EA1AFV", "EA3IMR EA3IMR"])
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL


def test_partial_query_char_by_char_matches_only_expected_station():
    sm = QSOStateMachine(_cfg(max_stations=2))
    sm.set_other_call_pool(["EA1AFV", "EA3IMR"])

    with patch("core.qso_state_machine.random.randint", return_value=2), patch(
        "core.qso_state_machine.random.sample",
        return_value=["EA1AFV", "EA3IMR"],
    ), patch("core.qso_state_machine.random.shuffle", lambda seq: None):
        sm.process_text("CQ POTA DE EA3IPX K")

    r = sm.process_text("E A 3 ?")
    assert r.accepted
    assert r.replies == ["EA3IMR EA3IMR"]
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL


def test_question_mark_alone_replies_all_pending_callers():
    sm = QSOStateMachine(_cfg(max_stations=2))
    sm.set_other_call_pool(["EA1AFV", "EA3IMR"])

    with patch("core.qso_state_machine.random.randint", return_value=2), patch(
        "core.qso_state_machine.random.sample",
        return_value=["EA1AFV", "EA3IMR"],
    ), patch("core.qso_state_machine.random.shuffle", lambda seq: None):
        sm.process_text("CQ POTA DE EA3IPX K")
        r = sm.process_text("?")

    assert r.accepted
    assert sorted(r.replies) == sorted(["EA1AFV EA1AFV", "EA3IMR EA3IMR"])
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL


def test_partial_query_without_matches_keeps_silence():
    sm = QSOStateMachine(_cfg(max_stations=2))
    sm.set_other_call_pool(["EA1AFV", "EA3IMR"])

    with patch("core.qso_state_machine.random.randint", return_value=2), patch(
        "core.qso_state_machine.random.sample",
        return_value=["EA1AFV", "EA3IMR"],
    ), patch("core.qso_state_machine.random.shuffle", lambda seq: None):
        sm.process_text("CQ POTA DE EA3IPX K")

    r = sm.process_text("W9?")
    assert r.accepted
    assert r.replies == []
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL


def test_exact_callsign_selects_that_station_only_for_qso():
    sm = QSOStateMachine(_cfg(max_stations=2))
    sm.set_other_call_pool(["EA1AFV", "EA3IMR"])

    with patch("core.qso_state_machine.random.randint", return_value=2), patch(
        "core.qso_state_machine.random.sample",
        return_value=["EA1AFV", "EA3IMR"],
    ), patch("core.qso_state_machine.random.shuffle", lambda seq: None):
        sm.process_text("CQ POTA DE EA3IPX K")

    r2 = sm.process_text("EA3IMR 5NN 5NN")
    assert r2.accepted
    assert r2.replies == ["KN UR 5NN 5NN TU 73 KN"]
    assert sm.state == QSOState.S5_WAIT_FINAL

    r5 = sm.process_text("73 EE")
    assert r5.accepted
    # Remaining pending station calls regardless of incoming_%.
    assert r5.replies == ["EE", "EA1AFV EA1AFV"]
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL


def test_pending_queue_has_priority_over_incoming_probability():
    sm = QSOStateMachine(
        _cfg(
            max_stations=2,
            auto_incoming_after_qso=True,
            auto_incoming_probability=1.0,
        )
    )
    sm.set_other_call_pool(["EA1AFV", "EA3IMR"])

    with patch("core.qso_state_machine.random.randint", return_value=2), patch(
        "core.qso_state_machine.random.sample",
        return_value=["EA1AFV", "EA3IMR"],
    ), patch("core.qso_state_machine.random.shuffle", lambda seq: None):
        sm.process_text("CQ POTA DE EA3IPX K")

    sm.process_text("EA3IMR 5NN 5NN")
    r5 = sm.process_text("73 EE")
    assert r5.accepted
    assert r5.replies == ["EE", "EA1AFV EA1AFV"]


def test_auto_incoming_after_qso_when_no_pending():
    sm = QSOStateMachine(
        _cfg(
            max_stations=1,
            auto_incoming_after_qso=True,
            auto_incoming_probability=0.5,
        )
    )
    sm.process_text("CQ POTA DE EA3IPX K")
    sm.process_text("N1MM 5NN 5NN")

    with patch("core.qso_state_machine.random.random", return_value=0.1):
        r5 = sm.process_text("73 EE")
    assert r5.accepted
    assert r5.replies == ["EE", "N1MM N1MM"]
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL


def test_auto_incoming_after_qso_draws_random_number_of_callers():
    sm = QSOStateMachine(
        _cfg(
            max_stations=3,
            auto_incoming_after_qso=True,
            auto_incoming_probability=1.0,
        )
    )
    sm.set_other_call_pool(["EA1AFV", "EA2BBB", "EA3IMR"])

    with patch("core.qso_state_machine.random.randint", side_effect=[1, 2]), patch(
        "core.qso_state_machine.random.sample",
        side_effect=[["EA2BBB"], ["EA1AFV", "EA3IMR"]],
    ), patch("core.qso_state_machine.random.shuffle", lambda seq: None):
        sm.process_text("CQ POTA DE EA3IPX K")
        sm.process_text("EA2BBB 5NN 5NN")
        r5 = sm.process_text("73 EE")

    assert r5.accepted
    assert r5.replies == ["EE", "EA1AFV EA1AFV", "EA3IMR EA3IMR"]
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL


def test_max_stations_controls_random_amount_of_callers():
    sm = QSOStateMachine(_cfg(max_stations=3))
    sm.set_other_call_pool(["EA1AFV", "EA2BBB", "EA3IMR"])

    with patch("core.qso_state_machine.random.randint", return_value=2), patch(
        "core.qso_state_machine.random.sample",
        return_value=["EA1AFV", "EA3IMR"],
    ), patch("core.qso_state_machine.random.shuffle", lambda seq: None):
        r0 = sm.process_text("CQ POTA DE EA3IPX K")

    assert r0.accepted
    assert len(r0.replies) == 2
    assert r0.replies == ["EA1AFV EA1AFV", "EA3IMR EA3IMR"]


def test_exchange_patterns_file_can_override_s0_with_regex(tmp_path: Path):
    patterns_file = tmp_path / "exchange_patterns.yaml"
    patterns_file.write_text(
        """
patterns:
  s0:
    SIMPLE:
      - '^QRL\\?{MY_CALL}K$'
""".strip(),
        encoding="utf-8",
    )

    sm = QSOStateMachine(
        _cfg(
            cq_mode="SIMPLE",
            max_stations=1,
            exchange_patterns_file=str(patterns_file),
        )
    )
    r_ok = sm.process_text("QRL? EA3IPX K")
    assert r_ok.accepted
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL

    sm_fail = QSOStateMachine(
        _cfg(
            cq_mode="SIMPLE",
            max_stations=1,
            exchange_patterns_file=str(patterns_file),
        )
    )
    r_fail = sm_fail.process_text("CQ DE EA3IPX K")
    assert not r_fail.accepted
    assert sm_fail.state == QSOState.S0_IDLE


def test_exchange_patterns_file_supports_regex_quantifiers_in_s2(tmp_path: Path):
    patterns_file = tmp_path / "exchange_patterns.yaml"
    patterns_file.write_text(
        """
patterns:
  s2:
    report_no_call:
      - '^(?:5NN){2}$'
""".strip(),
        encoding="utf-8",
    )

    sm = QSOStateMachine(_cfg(max_stations=1, exchange_patterns_file=str(patterns_file)))
    assert sm.process_text("CQ POTA DE EA3IPX K").accepted

    r_fail = sm.process_text("N1MM 5NN TEST 5NN")
    assert not r_fail.accepted
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL

    r_ok = sm.process_text("5NN 5NN")
    assert r_ok.accepted
    assert sm.state == QSOState.S5_WAIT_FINAL


def test_exchange_patterns_file_can_override_tx_templates(tmp_path: Path):
    patterns_file = tmp_path / "exchange_patterns.yaml"
    patterns_file.write_text(
        """
patterns:
  tx:
    report_reply: 'CUSTOM REPORT {TX_PROSIGN}'
    qso_complete: 'TU EE'
""".strip(),
        encoding="utf-8",
    )

    sm = QSOStateMachine(
        _cfg(
            max_stations=1,
            exchange_patterns_file=str(patterns_file),
        )
    )
    assert sm.process_text("CQ POTA DE EA3IPX K").accepted

    r2 = sm.process_text("N1MM 5NN 5NN")
    assert r2.accepted
    assert r2.replies == ["CUSTOM REPORT KN"]
    assert sm.state == QSOState.S5_WAIT_FINAL

    r5 = sm.process_text("73 EE")
    assert r5.accepted
    assert r5.replies == ["TU EE"]
    assert sm.state == QSOState.S0_IDLE

