from __future__ import annotations

from unittest.mock import patch

from core.qso_state_machine import QSOConfig, QSOState, QSOStateMachine


def test_s0_requires_double_my_call():
    sm = QSOStateMachine(QSOConfig(my_call="EA4XYZ", other_call="N1MM"))
    res = sm.process_text("CQ CQ POTA DE EA4XYZ K")
    assert not res.accepted
    assert sm.state == QSOState.S0_IDLE
    assert any("EA4XYZ" in err for err in res.errors)


def test_valid_cq_moves_to_s2_and_replies_double_other_call():
    sm = QSOStateMachine(QSOConfig(my_call="EA4XYZ", other_call="N1MM"))
    res = sm.process_text("CQ CQ POTA DE EA4XYZ EA4XYZ K")
    assert res.accepted
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL
    assert res.replies == ["N1MM N1MM"]


def test_s0_simple_mode_accepts_cq_without_pota_or_sota():
    sm = QSOStateMachine(QSOConfig(my_call="EA4XYZ", other_call="N1MM", cq_mode="SIMPLE"))
    res = sm.process_text("CQ CQ EA4XYZ EA4XYZ K")
    assert res.accepted
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL


def test_s0_sota_mode_requires_sota_keyword():
    sm = QSOStateMachine(QSOConfig(my_call="EA4XYZ", other_call="N1MM", cq_mode="SOTA"))
    bad = sm.process_text("CQ CQ POTA DE EA4XYZ EA4XYZ K")
    assert not bad.accepted
    assert sm.state == QSOState.S0_IDLE
    assert any("SOTA" in err for err in bad.errors)

    good = sm.process_text("CQ CQ SOTA DE EA4XYZ EA4XYZ K")
    assert good.accepted
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL


def test_full_qso_flow_success():
    sm = QSOStateMachine(
        QSOConfig(
            my_call="EA4XYZ",
            other_call="N1MM",
            require_k1=False,
            allow_599=False,
            allow_tu=True,
            direct_report_mode=False,
            s4_prefix="RR",
        )
    )
    assert sm.process_text("CQ CQ POTA DE EA4XYZ EA4XYZ K").accepted
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL

    assert sm.process_text("N1MM").accepted
    assert sm.state == QSOState.S3_WAIT_MY_REPORT

    r3 = sm.process_text("N1MM UR 5NN 5NN <CAVE>")
    assert r3.accepted
    assert sm.state == QSOState.S5_WAIT_FINAL
    assert r3.replies == ["RR UR 5NN 5NN <CAVE>"]

    r5 = sm.process_text("<CAVE> TU 73 EE")
    assert r5.accepted
    assert r5.replies == ["EE"]
    assert sm.state == QSOState.S0_IDLE
    assert len(sm.completions) == 1


def test_require_k1_enforced():
    sm = QSOStateMachine(QSOConfig(my_call="EA4XYZ", other_call="N1MM", require_k1=True))
    bad = sm.process_text("CQ CQ POTA DE EA4XYZ EA4XYZ K")
    assert not bad.accepted
    assert sm.state == QSOState.S0_IDLE

    good = sm.process_text("CQ CQ POTA DE EA4XYZ EA4XYZ K1")
    assert good.accepted
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL


def test_accepts_character_spaced_cq_and_report():
    sm = QSOStateMachine(
        QSOConfig(
            my_call="EA4XYZ",
            other_call="N1MM",
            allow_tu=True,
            direct_report_mode=False,
        )
    )
    assert sm.process_text("C Q C Q P O T A D E E A 4 X Y Z E A 4 X Y Z K").accepted
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL

    assert sm.process_text("N 1 M M").accepted
    assert sm.state == QSOState.S3_WAIT_MY_REPORT

    r3 = sm.process_text("N 1 M M U R 5 N N 5 N N <CAVE>")
    assert r3.accepted
    assert sm.state == QSOState.S5_WAIT_FINAL

    r5 = sm.process_text("<CAVE> T U 7 3 E E")
    assert r5.accepted
    assert sm.state == QSOState.S0_IDLE


def test_prosign_char_by_char_is_rejected():
    sm = QSOStateMachine(QSOConfig(my_call="EA4XYZ", other_call="N1MM", direct_report_mode=False))
    assert sm.process_text("CQ CQ POTA DE EA4XYZ EA4XYZ K").accepted
    assert sm.process_text("N1MM").accepted

    bad = sm.process_text("N1MM UR 5NN 5NN C A V E")
    assert not bad.accepted
    assert any("<CAVE>" in err for err in bad.errors)


def test_flow_without_prosigns():
    sm = QSOStateMachine(
        QSOConfig(
            my_call="EA4XYZ",
            other_call="N1MM",
            direct_report_mode=False,
            use_prosigns=False,
            allow_tu=True,
        )
    )
    assert sm.process_text("CQ CQ POTA DE EA4XYZ EA4XYZ K").accepted
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL

    assert sm.process_text("N1MM").accepted
    assert sm.state == QSOState.S3_WAIT_MY_REPORT

    r3 = sm.process_text("N1MM UR 5NN 5NN")
    assert r3.accepted
    assert r3.replies == ["RR UR 5NN 5NN"]
    assert sm.state == QSOState.S5_WAIT_FINAL

    r5 = sm.process_text("TU 73 EE")
    assert r5.accepted
    assert r5.replies == ["EE"]
    assert sm.state == QSOState.S0_IDLE


def test_missing_end_key_reports_k_not_pota():
    sm = QSOStateMachine(QSOConfig(my_call="EA3IPX", other_call="N1MM"))
    res = sm.process_text("CQ CQ CQ P OTA D E EA3IPX EA3IPX N")
    assert not res.accepted
    assert sm.state == QSOState.S0_IDLE
    assert any("'K'" in err for err in res.errors)


def test_direct_report_flow_waits_for_73_ee_before_closing():
    sm = QSOStateMachine(
        QSOConfig(
            my_call="EA3IPX",
            other_call="N1MM",
            direct_report_mode=True,
            use_prosigns=False,
            prosign_literal="KN",
        )
    )
    assert sm.process_text("CQ CQ POTA DE EA3IPX EA3IPX K").accepted
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL

    r2 = sm.process_text("N1MM 5NN 5NN")
    assert r2.accepted
    assert r2.replies == ["KN UR 5NN 5NN TU 73 KN"]
    assert sm.state == QSOState.S5_WAIT_FINAL

    r5 = sm.process_text("73 EE")
    assert r5.accepted
    assert r5.replies == ["EE"]
    assert sm.state == QSOState.S0_IDLE
    assert len(sm.completions) == 1


def test_dynamic_other_call_pool_is_used_in_new_qso():
    sm = QSOStateMachine(
        QSOConfig(
            my_call="EA3IPX",
            other_call="N1MM",
            direct_report_mode=True,
            use_prosigns=False,
            prosign_literal="KN",
        )
    )
    sm.set_other_call_pool(["W1AW", "K1ABC"])

    with patch("core.qso_state_machine.random.choice", return_value="K1ABC"):
        s0 = sm.process_text("CQ CQ POTA DE EA3IPX EA3IPX K")
    assert s0.accepted
    assert s0.replies == ["K1ABC K1ABC"]
    assert sm.active_other_call == "K1ABC"

    bad = sm.process_text("N1MM 5NN 5NN")
    assert not bad.accepted
    assert any("K1ABC" in err for err in bad.errors)

    good = sm.process_text("K1ABC 5NN 5NN")
    assert good.accepted
    assert sm.state == QSOState.S5_WAIT_FINAL
    assert good.replies == ["KN UR 5NN 5NN TU 73 KN"]


def test_direct_report_uses_configured_closing_prosign():
    sm = QSOStateMachine(
        QSOConfig(
            my_call="EA3IPX",
            other_call="N1MM",
            direct_report_mode=True,
            use_prosigns=False,
            prosign_literal="BK",
        )
    )
    assert sm.process_text("CQ CQ POTA DE EA3IPX EA3IPX K").accepted
    r2 = sm.process_text("N1MM 5NN 5NN")
    assert r2.accepted
    assert r2.replies == ["BK UR 5NN 5NN TU 73 BK"]


def test_s2_repeat_request_with_question_mark_repeats_call_direct_mode():
    sm = QSOStateMachine(
        QSOConfig(
            my_call="EA3IPX",
            other_call="K2LYV",
            direct_report_mode=True,
            use_prosigns=False,
        )
    )
    assert sm.process_text("CQ CQ POTA DE EA3IPX EA3IPX K").accepted
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL

    r = sm.process_text("K2?")
    assert r.accepted
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL
    assert r.replies == ["K2LYV K2LYV"]


def test_s2_repeat_request_with_question_mark_repeats_call_legacy_mode():
    sm = QSOStateMachine(
        QSOConfig(
            my_call="EA3IPX",
            other_call="K2LYV",
            direct_report_mode=False,
            use_prosigns=False,
        )
    )
    assert sm.process_text("CQ CQ POTA DE EA3IPX EA3IPX K").accepted
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL

    r = sm.process_text("?")
    assert r.accepted
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL
    assert r.replies == ["K2LYV K2LYV"]


def test_s2_full_call_with_question_mark_sends_rr_and_continues_direct_mode():
    sm = QSOStateMachine(
        QSOConfig(
            my_call="EA3IPX",
            other_call="K2LYV",
            direct_report_mode=True,
            use_prosigns=False,
        )
    )
    assert sm.process_text("CQ CQ POTA DE EA3IPX EA3IPX K").accepted
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL

    r = sm.process_text("K2LYV?")
    assert r.accepted
    assert r.replies == ["RR"]
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL

    # After RR confirm, call may be omitted in direct mode.
    r2 = sm.process_text("5NN 5NN")
    assert r2.accepted
    assert sm.state == QSOState.S5_WAIT_FINAL


def test_s2_full_call_with_question_mark_split_chars_sends_rr_and_continues_direct_mode():
    sm = QSOStateMachine(
        QSOConfig(
            my_call="EA3IPX",
            other_call="K2LYV",
            direct_report_mode=True,
            use_prosigns=False,
        )
    )
    assert sm.process_text("CQ CQ POTA DE EA3IPX EA3IPX K").accepted
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL

    r = sm.process_text("K 2 L Y V ?")
    assert r.accepted
    assert r.replies == ["RR"]
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL

    r2 = sm.process_text("5 N N 5 N N")
    assert r2.accepted
    assert sm.state == QSOState.S5_WAIT_FINAL


def test_s2_full_call_with_question_mark_sends_rr_and_continues_legacy_mode():
    sm = QSOStateMachine(
        QSOConfig(
            my_call="EA3IPX",
            other_call="K2LYV",
            direct_report_mode=False,
            use_prosigns=False,
        )
    )
    assert sm.process_text("CQ CQ POTA DE EA3IPX EA3IPX K").accepted
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL

    r = sm.process_text("K2LYV ?")
    assert r.accepted
    assert r.replies == ["RR"]
    assert sm.state == QSOState.S3_WAIT_MY_REPORT


def test_auto_incoming_after_qso_enabled_triggers_new_call_50pct_branch():
    sm = QSOStateMachine(
        QSOConfig(
            my_call="EA3IPX",
            other_call="N1MM",
            direct_report_mode=True,
            use_prosigns=False,
            auto_incoming_after_qso=True,
            auto_incoming_probability=0.5,
        )
    )
    assert sm.process_text("CQ CQ POTA DE EA3IPX EA3IPX K").accepted
    assert sm.process_text("N1MM 5NN 5NN").accepted

    with patch("core.qso_state_machine.random.random", return_value=0.1):
        r5 = sm.process_text("73 EE")
    assert r5.accepted
    assert r5.replies == ["EE", "N1MM N1MM"]
    assert sm.state == QSOState.S2_WAIT_MY_ACK_CALL


def test_auto_incoming_after_qso_enabled_no_call_branch():
    sm = QSOStateMachine(
        QSOConfig(
            my_call="EA3IPX",
            other_call="N1MM",
            direct_report_mode=True,
            use_prosigns=False,
            auto_incoming_after_qso=True,
            auto_incoming_probability=0.5,
        )
    )
    assert sm.process_text("CQ CQ POTA DE EA3IPX EA3IPX K").accepted
    assert sm.process_text("N1MM 5NN 5NN").accepted

    with patch("core.qso_state_machine.random.random", return_value=0.9):
        r5 = sm.process_text("73 EE")
    assert r5.accepted
    assert r5.replies == ["EE"]
    assert sm.state == QSOState.S0_IDLE
