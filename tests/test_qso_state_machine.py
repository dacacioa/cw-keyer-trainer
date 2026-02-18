from __future__ import annotations

from unittest.mock import patch

from core.qso_state_machine import QSOConfig, QSOState, QSOStateMachine


def _cfg(**kwargs) -> QSOConfig:
    base = QSOConfig(
        my_call="EA3IPX",
        other_call="N1MM",
        use_prosigns=False,
        prosign_literal="KN",
        max_stations=1,
    )
    for k, v in kwargs.items():
        setattr(base, k, v)
    return base


def test_s0_requires_double_my_call():
    sm = QSOStateMachine(_cfg())
    res = sm.process_text("CQ CQ POTA DE EA3IPX K")
    assert not res.accepted
    assert sm.state == QSOState.S0_IDLE
    assert any("EA3IPX" in err for err in res.errors)


def test_valid_cq_moves_to_s2_and_single_call_when_max_stations_is_1():
    sm = QSOStateMachine(_cfg(max_stations=1))
    res = sm.process_text("CQ CQ POTA DE EA3IPX EA3IPX K")
    assert res.accepted
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL
    assert res.replies == ["N1MM N1MM"]


def test_direct_qso_flow_success_single_station():
    sm = QSOStateMachine(_cfg(max_stations=1))
    assert sm.process_text("CQ CQ POTA DE EA3IPX EA3IPX K").accepted

    r2 = sm.process_text("N1MM 5NN 5NN")
    assert r2.accepted
    assert r2.replies == ["KN UR 5NN 5NN TU 73 KN"]
    assert sm.state == QSOState.S5_WAIT_FINAL

    r5 = sm.process_text("73 EE")
    assert r5.accepted
    assert r5.replies == ["EE"]
    assert sm.state == QSOState.S0_IDLE
    assert len(sm.completions) == 1


def test_full_call_query_selects_station_and_sends_rr():
    sm = QSOStateMachine(_cfg(max_stations=2))
    sm.set_other_call_pool(["EA1AFV", "EA3IMR"])

    with patch("core.qso_state_machine.random.randint", return_value=2), patch(
        "core.qso_state_machine.random.sample",
        return_value=["EA1AFV", "EA3IMR"],
    ), patch("core.qso_state_machine.random.shuffle", lambda seq: None):
        sm.process_text("CQ CQ POTA DE EA3IPX EA3IPX K")

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
        sm.process_text("CQ CQ POTA DE EA3IPX EA3IPX K")

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
        sm.process_text("CQ CQ POTA DE EA3IPX EA3IPX K")

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
        sm.process_text("CQ CQ POTA DE EA3IPX EA3IPX K")

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
        sm.process_text("CQ CQ POTA DE EA3IPX EA3IPX K")
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
        sm.process_text("CQ CQ POTA DE EA3IPX EA3IPX K")

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
        sm.process_text("CQ CQ POTA DE EA3IPX EA3IPX K")

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
        sm.process_text("CQ CQ POTA DE EA3IPX EA3IPX K")

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
    sm.process_text("CQ CQ POTA DE EA3IPX EA3IPX K")
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
        sm.process_text("CQ CQ POTA DE EA3IPX EA3IPX K")
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
        r0 = sm.process_text("CQ CQ POTA DE EA3IPX EA3IPX K")

    assert r0.accepted
    assert len(r0.replies) == 2
    assert r0.replies == ["EA1AFV EA1AFV", "EA3IMR EA3IMR"]
