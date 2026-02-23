from __future__ import annotations

import random
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .exchange_patterns import ExchangePatterns, load_exchange_patterns
from .morse import PROSIGN_TOKEN, collapse_cave_tokens, tokenize_text

_S2_REPORT_RE = re.compile(r"[1-5][1-9N][9N]")


class QSOState(str, Enum):
    S0_IDLE = "S0_IDLE"
    S1_REPLY_CALL = "S1_REPLY_CALL"
    S2_WAIT_MY_ACK_CALL = "S2_WAIT_MY_ACK_CALL"
    S4_REPLY_OTHER = "S4_REPLY_OTHER"
    S5_WAIT_FINAL = "S5_WAIT_FINAL"
    S6_REPLY_EE = "S6_REPLY_EE"


@dataclass
class QSOConfig:
    my_call: str = "EA4XYZ"
    other_call: str = "N1MM"
    cq_mode: str = "POTA"  # SIMPLE, POTA, SOTA
    max_stations: int = 1
    other_calls_file: Optional[str] = None
    parks_file: Optional[str] = "data/all_parks_ext.csv"
    exchange_patterns_file: Optional[str] = "data/exchange_patterns.yaml"
    auto_incoming_after_qso: bool = False
    auto_incoming_probability: float = 0.5
    p2p_probability: float = 0.0
    my_park_ref: str = "EA-0000"
    allow_599: bool = False
    allow_tu: bool = False
    use_prosigns: bool = True
    prosign_literal: str = "CAVE"
    s4_prefix: str = "RR"  # RR or R
    ignore_bk: bool = True
    ignore_fill_tokens: Tuple[str, ...] = ("RR", "R", "DE")


@dataclass
class QSOResult:
    state: QSOState
    accepted: bool
    replies: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    info: List[str] = field(default_factory=list)


@dataclass
class QSOCompletion:
    timestamp_utc: str
    my_call: str
    other_call: str
    transcript_rx: List[str]
    transcript_tx: List[str]


class QSOStateMachine:
    def __init__(self, config: QSOConfig):
        self.config = config
        self.state = QSOState.S0_IDLE
        self.rx_transcript: List[str] = []
        self.tx_transcript: List[str] = []
        self.completions: List[QSOCompletion] = []
        self.logs: List[Dict[str, str]] = []
        self._other_call_pool: List[str] = []
        self._park_ref_pool: List[str] = []
        self._active_other_call_real = self.config.other_call.upper()
        self._active_other_call = self.config.other_call.upper()
        self._s2_rr_confirmed = False
        self._pending_callers: List[str] = []
        self._pending_p2p_real_call: Optional[str] = None
        self._active_call_selected = False
        self._active_is_p2p = False
        self._active_p2p_park_ref: Optional[str] = None
        self._exchange_patterns: ExchangePatterns
        self._exchange_patterns, pattern_error = load_exchange_patterns(self.config.exchange_patterns_file)
        if pattern_error:
            self._log("WARN", pattern_error, self.state)

    def reset(self) -> None:
        self.state = QSOState.S0_IDLE
        self.rx_transcript.clear()
        self.tx_transcript.clear()
        self._active_other_call_real = self.config.other_call.upper()
        self._active_other_call = self.config.other_call.upper()
        self._s2_rr_confirmed = False
        self._pending_callers.clear()
        self._pending_p2p_real_call = None
        self._active_call_selected = False
        self._active_is_p2p = False
        self._active_p2p_park_ref = None
        self._log("INFO", "QSO reset manual", self.state)

    def set_other_call_pool(self, calls: Sequence[str], source_file: Optional[str] = None) -> None:
        cleaned: List[str] = []
        seen = set()
        for call in calls:
            c = call.strip().upper()
            if not c or c in seen:
                continue
            seen.add(c)
            cleaned.append(c)
        self._other_call_pool = cleaned
        if self._pending_p2p_real_call and self._pending_p2p_real_call not in cleaned:
            self._pending_p2p_real_call = None
        if source_file is not None:
            self.config.other_calls_file = source_file
        if cleaned:
            self._log("INFO", f"Loaded {len(cleaned)} dynamic callsigns.", self.state)
        else:
            self._log("INFO", "Dynamic callsign pool is empty; using fixed other_call.", self.state)

    def set_park_ref_pool(self, park_refs: Sequence[str], source_file: Optional[str] = None) -> None:
        cleaned: List[str] = []
        seen = set()
        for ref in park_refs:
            r = ref.strip().upper()
            if not r or r in seen:
                continue
            seen.add(r)
            cleaned.append(r)
        self._park_ref_pool = cleaned
        if source_file is not None:
            self.config.parks_file = source_file
        if cleaned:
            self._log("INFO", f"Loaded {len(cleaned)} active park references.", self.state)
        else:
            self._log("INFO", "Active park reference pool is empty; P2P disabled.", self.state)

    @property
    def active_other_call(self) -> str:
        return self._active_other_call

    @property
    def active_other_call_real(self) -> str:
        return self._active_other_call_real

    @property
    def other_call_pool_size(self) -> int:
        return len(self._other_call_pool)

    @property
    def park_ref_pool_size(self) -> int:
        return len(self._park_ref_pool)

    def process_text(self, text: str) -> QSOResult:
        tokens = self._normalize_tokens(text)
        result = QSOResult(state=self.state, accepted=False)
        if not tokens:
            result.errors.append("No se detectaron tokens utiles.")
            return result

        self.rx_transcript.append(" ".join(tokens))
        self._log("RX", " ".join(tokens), self.state)

        if self.state == QSOState.S0_IDLE:
            return self._handle_s0(tokens)
        if self.state == QSOState.S2_WAIT_MY_ACK_CALL:
            return self._handle_s2(tokens)
        if self.state == QSOState.S5_WAIT_FINAL:
            return self._handle_s5(tokens)

        result.errors.append(f"Estado no manejado: {self.state}")
        return result

    def export_session(self) -> Dict[str, object]:
        return {
            "state": self.state.value,
            "config": asdict(self.config),
            "active_other_call": self._active_other_call,
            "active_other_call_real": self._active_other_call_real,
            "active_is_p2p": self._active_is_p2p,
            "active_p2p_park_ref": self._active_p2p_park_ref,
            "pending_callers": list(self._pending_callers),
            "pending_p2p_real_call": self._pending_p2p_real_call,
            "active_call_selected": self._active_call_selected,
            "park_ref_pool_size": len(self._park_ref_pool),
            "logs": self.logs,
            "completions": [asdict(c) for c in self.completions],
            "rx_transcript": self.rx_transcript,
            "tx_transcript": self.tx_transcript,
        }

    def _handle_s0(self, tokens: Sequence[str]) -> QSOResult:
        cq_mode = (self.config.cq_mode or "POTA").strip().upper()
        if cq_mode not in ("SIMPLE", "POTA", "SOTA"):
            cq_mode = "POTA"
        required: List[str] = ["CQ"]
        if cq_mode in ("POTA", "SOTA"):
            required.append(cq_mode)
        required.extend(["DE", self.config.my_call.upper(), "K"])
        missing = ""
        patterns = self._exchange_patterns.s0.get(cq_mode, tuple())
        if patterns:
            ok = self._match_compact_exchange_patterns(patterns, tokens)
            _, missing = _contains_subsequence_flexible(tokens, required)
        else:
            ok, missing = _contains_subsequence_flexible(tokens, required)

        result = QSOResult(state=self.state, accepted=ok)
        if not ok:
            if missing:
                result.errors.append(f"S0 invalido: falto o no coincide token '{missing}'.")
            else:
                result.errors.append(f"S0 invalido: no coincide con patron de CQ para modo '{cq_mode}'.")
            self._log("ERR", result.errors[-1], self.state)
            return result

        self._s2_rr_confirmed = False
        self._active_call_selected = False
        self._pending_callers = self._draw_new_incoming_callers()
        replies = self._emit_callers(self._pending_callers)

        result.state = self.state
        result.accepted = True
        result.replies = replies
        result.info = [f"CQ valido, {len(replies)} estaciones llamando. Selecciona una por indicativo exacto."]
        return result

    def _handle_s2(self, tokens: Sequence[str]) -> QSOResult:
        if not self._active_call_selected:
            return self._handle_s2_select_station(tokens)

        call = self._active_other_call
        if _is_full_call_query(tokens, call):
            reply = self._build_tx_from_template("ack_rr", fallback="RR")
            self.tx_transcript.append(reply)
            self._log("TX", reply, self.state)
            self._s2_rr_confirmed = True
            return QSOResult(
                state=self.state,
                accepted=True,
                replies=[reply],
                info=["RR enviado; continua con el reporte."],
            )

        if _is_repeat_request_for_call(tokens, call):
            reply = self._build_tx_from_template(
                "repeat_selected_call",
                fallback=f"{call} {call}",
                other_call=call,
                extra_values={"CALL": call},
            )
            self.tx_transcript.append(reply)
            self._log("TX", reply, self.state)
            return QSOResult(
                state=self.state,
                accepted=True,
                replies=[reply],
                info=["Solicitud de repeticion detectada; repito indicativo y sigo en S2."],
            )

        return self._handle_s2_direct_report(tokens)

    def _handle_s2_select_station(self, tokens: Sequence[str]) -> QSOResult:
        if not self._pending_callers:
            msg = "S2 invalido: no hay estaciones pendientes para seleccionar."
            self._log("ERR", msg, self.state)
            return QSOResult(state=self.state, accepted=False, errors=[msg])

        # Exact full query (e.g. EA3IMR?) selects only that station and replies RR.
        selected_query = next(
            (c for c in self._pending_callers if _is_full_call_query(tokens, self._display_call(c))),
            None,
        )
        if selected_query:
            self._select_pending_station(selected_query)
            reply = self._build_tx_from_template("ack_rr", fallback="RR")
            self.tx_transcript.append(reply)
            self._log("TX", reply, self.state)
            self._s2_rr_confirmed = True
            return QSOResult(
                state=self.state,
                accepted=True,
                replies=[reply],
                info=[f"Estacion {self._active_other_call} seleccionada. RR enviado."],
            )

        wildcard_patterns = _extract_wildcard_patterns(tokens)
        if wildcard_patterns:
            matches = self._match_pending_by_patterns(wildcard_patterns)
            if not matches:
                return QSOResult(
                    state=self.state,
                    accepted=True,
                    replies=[],
                    info=["Sin coincidencias para el patron enviado."],
                )
            replies = self._emit_callers(matches)
            return QSOResult(
                state=self.state,
                accepted=True,
                replies=replies,
                info=[f"Coincidencias: {', '.join(matches)}"],
            )

        exact_call = self._find_exact_pending_call(tokens)
        if exact_call:
            self._select_pending_station(exact_call)
            return self._handle_s2_direct_report(tokens)

        msg = "S2 invalido: indica un indicativo exacto de una estacion en cola."
        self._log("ERR", msg, self.state)
        return QSOResult(state=self.state, accepted=False, errors=[msg])

    def _handle_s2_direct_report(self, tokens: Sequence[str]) -> QSOResult:
        call = self._active_other_call
        if _is_repeat_request_for_call(tokens, call):
            reply = self._build_tx_from_template(
                "repeat_selected_call",
                fallback=f"{call} {call}",
                other_call=call,
                extra_values={"CALL": call},
            )
            self.tx_transcript.append(reply)
            self._log("TX", reply, self.state)
            return QSOResult(
                state=self.state,
                accepted=True,
                replies=[reply],
                info=["Solicitud de repeticion detectada; repito indicativo y sigo en S2."],
            )

        cleaned = _strip_fillers(
            tokens,
            ignore_bk=self.config.ignore_bk,
            ignore_tokens=self.config.ignore_fill_tokens,
        )
        if self._active_is_p2p:
            p2p_patterns = self._exchange_patterns.s2.get("p2p_ack", tuple())
            if p2p_patterns:
                if not self._match_compact_exchange_patterns(p2p_patterns, cleaned, other_call="P2P"):
                    msg = "S2 invalido: para P2P debes contestar con 'P2P'."
                    result = QSOResult(state=self.state, accepted=False, errors=[msg])
                    self._log("ERR", msg, self.state)
                    return result
            elif _count_token_flexible(cleaned, "P2P") < 1:
                msg = "S2 invalido: para P2P debes contestar con 'P2P'."
                result = QSOResult(state=self.state, accepted=False, errors=[msg])
                self._log("ERR", msg, self.state)
                return result

            reply = self._build_p2p_station_reply()
            self.state = QSOState.S4_REPLY_OTHER
            self._s2_rr_confirmed = False
            self.tx_transcript.append(reply)
            self._log("TX", reply, self.state)
            self.state = QSOState.S5_WAIT_FINAL
            return QSOResult(
                state=self.state,
                accepted=True,
                replies=[reply],
                info=["Intercambio P2P enviado. Esperando cierre final con tu referencia de parque."],
            )

        # Once a station is selected, report may omit the call.
        require_call = (not self._active_call_selected) and (not self._s2_rr_confirmed)
        pattern_key = "report_require_call" if require_call else "report_no_call"
        if self.config.allow_599:
            pattern_key += "_allow_599"
        patterns = self._exchange_patterns.s2.get(pattern_key, tuple())
        if patterns:
            if not self._match_compact_exchange_patterns(patterns, cleaned, other_call=call):
                missing = self._legacy_s2_missing_tokens(cleaned, call=call, require_call=require_call)
                msg = f"S2 invalido: no coincide con patron '{pattern_key}'."
                if missing:
                    msg += " Faltan: " + ", ".join(missing)
                result = QSOResult(state=self.state, accepted=False, errors=[msg])
                self._log("ERR", msg, self.state)
                return result
        else:
            missing = self._legacy_s2_missing_tokens(cleaned, call=call, require_call=require_call)
            if missing:
                msg = "S2 invalido: faltan tokens obligatorios: " + ", ".join(missing)
                result = QSOResult(state=self.state, accepted=False, errors=[msg])
                self._log("ERR", msg, self.state)
                return result

        tx_prosign = self._tx_closing_prosign()
        # In direct mode, report reply starts with prosign and omits my callsign.
        reply = self._build_tx_from_template(
            "report_reply",
            fallback=f"{tx_prosign} UR 5NN 5NN TU 73 {tx_prosign}",
        )
        self.state = QSOState.S4_REPLY_OTHER
        self._s2_rr_confirmed = False
        self.tx_transcript.append(reply)
        self._log("TX", reply, self.state)
        self.state = QSOState.S5_WAIT_FINAL
        return QSOResult(
            state=self.state,
            accepted=True,
            replies=[reply],
            info=["Reporte correcto, respuesta enviada. Esperando cierre final (73 EE)."],
        )

    def _handle_s5(self, tokens: Sequence[str]) -> QSOResult:
        if self._active_is_p2p and self._active_p2p_park_ref:
            p2p_query = self._handle_s5_p2p_query(tokens)
            if p2p_query is not None:
                return p2p_query

        if _is_repeat_request_for_call(tokens, self._active_other_call):
            if not self.tx_transcript:
                msg = "S5 invalido: no hay transmision previa para repetir."
                result = QSOResult(state=self.state, accepted=False, errors=[msg])
                self._log("ERR", msg, self.state)
                return result
            reply = self.tx_transcript[-1]
            self.tx_transcript.append(reply)
            self._log("TX", reply, self.state)
            return QSOResult(
                state=self.state,
                accepted=True,
                replies=[reply],
                info=["Solicitud de repeticion detectada; repito ultima transmision y sigo en S5."],
            )

        cleaned = _strip_fillers(
            _collapse_double_e(tokens),
            ignore_bk=self.config.ignore_bk and (not self.config.use_prosigns),
            ignore_tokens=self.config.ignore_fill_tokens,
        )
        if self._active_is_p2p and self._active_p2p_park_ref:
            return self._handle_s5_p2p(cleaned)

        pattern_key = "with_prosign" if self.config.use_prosigns else "without_prosign"
        if self.config.allow_tu:
            pattern_key += "_allow_tu"
        patterns = self._exchange_patterns.s5.get(pattern_key, tuple())
        if patterns:
            ok = self._match_compact_exchange_patterns(patterns, cleaned)
            if not ok:
                msg = f"S5 invalido: no coincide con patron '{pattern_key}'."
                result = QSOResult(state=self.state, accepted=False, errors=[msg])
                self._log("ERR", msg, self.state)
                return result
        else:
            prosign_token = self._prosign_token()
            if self.config.use_prosigns:
                if _count_token_direct(cleaned, prosign_token) < 1:
                    msg = f"S5 invalido: prosign {prosign_token} debe enviarse sin separacion entre letras."
                    result = QSOResult(state=self.state, accepted=False, errors=[msg])
                    self._log("ERR", msg, self.state)
                    return result
                required_basic = [prosign_token, "73", "EE"]
                required_tu = [prosign_token, "TU", "73", "EE"]
            else:
                required_basic = ["73", "EE"]
                required_tu = ["TU", "73", "EE"]

            ok_basic, missing_basic = _contains_subsequence_flexible(cleaned, required_basic)
            ok_tu = False
            if self.config.allow_tu:
                ok_tu, _ = _contains_subsequence_flexible(cleaned, required_tu)

            result = QSOResult(state=self.state, accepted=ok_basic or ok_tu)
            if not result.accepted:
                if self.config.use_prosigns:
                    expected = f"{prosign_token} 73 EE"
                else:
                    expected = "73 EE"
                msg = f"S5 invalido: cierre esperado '{expected}' (falto '{missing_basic}')."
                result.errors.append(msg)
                self._log("ERR", msg, self.state)
                return result

        return self._complete_qso_with_reply(
            reply=self._build_tx_from_template("qso_complete", fallback="EE"),
            interim_state=QSOState.S6_REPLY_EE,
            info="QSO completado. Vuelta a S0.",
        )

    def _normalize_tokens(self, text: str) -> List[str]:
        toks = collapse_cave_tokens(tokenize_text(text))
        out: List[str] = []
        configured = self._prosign_token()
        for t in toks:
            if t == PROSIGN_TOKEN:
                out.append(configured)
            elif t.startswith("<") and t.endswith(">"):
                out.append(t.upper())
            else:
                out.append(t.upper())
        return out

    def _handle_s5_p2p(self, cleaned: Sequence[str]) -> QSOResult:
        key = "p2p_with_prosign" if self.config.use_prosigns else "p2p_without_prosign"
        if self.config.allow_tu:
            key += "_allow_tu"
        patterns = self._exchange_patterns.s5.get(key, tuple())
        if patterns:
            ok = self._match_compact_exchange_patterns(patterns, cleaned)
            if not ok:
                msg = f"S5 invalido: no coincide con patron P2P '{key}'."
                result = QSOResult(state=self.state, accepted=False, errors=[msg])
                self._log("ERR", msg, self.state)
                return result
        else:
            my_park = (self.config.my_park_ref or "").strip().upper()
            if not my_park:
                my_park = "EA-0000"
            required: List[str] = []
            if self.config.use_prosigns:
                required.append(self._prosign_token())
            required.extend([self._active_other_call_real, self.config.my_call.upper(), "MY", "REF", my_park, my_park])
            if self.config.allow_tu:
                required.extend(["TU", "73"])
            ok, missing = _contains_subsequence_flexible(cleaned, required)
            if not ok:
                expected = " ".join(required)
                msg = f"S5 invalido: cierre P2P esperado '{expected}' (falto '{missing}')."
                result = QSOResult(state=self.state, accepted=False, errors=[msg])
                self._log("ERR", msg, self.state)
                return result

        return self._complete_qso_with_reply(
            reply=self._build_tx_from_template("qso_complete", fallback="EE"),
            interim_state=QSOState.S6_REPLY_EE,
            info="QSO P2P completado. Vuelta a S0.",
        )

    def _handle_s5_p2p_query(self, tokens: Sequence[str]) -> Optional[QSOResult]:
        query = _compact_join(tokens)
        if query == "CALL?":
            call = self._active_other_call_real
            reply = self._build_tx_from_template(
                "p2p_repeat_call",
                fallback=f"{call} {call}",
                other_call=call,
                extra_values={"CALL": call},
            )
            self.tx_transcript.append(reply)
            self._log("TX", reply, self.state)
            return QSOResult(
                state=self.state,
                accepted=True,
                replies=[reply],
                info=["Solicitud 'CALL?' en P2P: repito indicativo del llamante y sigo en S5."],
            )

        if query == "REF?":
            park = _compact_park_ref(self._active_p2p_park_ref or "")
            reply = self._build_tx_from_template(
                "p2p_repeat_ref",
                fallback=f"{park} {park}",
                extra_values={"PARK_REF": park},
            )
            self.tx_transcript.append(reply)
            self._log("TX", reply, self.state)
            return QSOResult(
                state=self.state,
                accepted=True,
                replies=[reply],
                info=["Solicitud 'REF?' en P2P: repito referencia de parque y sigo en S5."],
            )
        return None

    def _build_p2p_station_reply(self) -> str:
        key = "p2p_station_reply_with_tu" if self.config.allow_tu else "p2p_station_reply_without_tu"
        template = self._exchange_patterns.tx.get(key, "")
        values = dict(self._exchange_pattern_values())
        values["PARK_REF"] = _compact_park_ref(self._active_p2p_park_ref or "")
        values["MY_PARK_REF"] = _compact_park_ref(self.config.my_park_ref or "")
        if template:
            return _clean_message_spacing(_render_exchange_template(template, values))

        tx_prosign = self._tx_closing_prosign()
        parts = [tx_prosign, self._active_other_call_real, self._active_other_call_real, "MY", "REF"]
        park = _compact_park_ref(self._active_p2p_park_ref or "")
        if park:
            parts.extend([park, park])
        if self.config.allow_tu:
            parts.append("TU")
        parts.extend(["73", tx_prosign])
        return _clean_message_spacing(" ".join(parts))

    def _build_tx_from_template(
        self,
        key: str,
        *,
        fallback: str,
        other_call: Optional[str] = None,
        extra_values: Optional[Mapping[str, str]] = None,
    ) -> str:
        template = (self._exchange_patterns.tx.get(key, "") or "").strip()
        if not template:
            return _clean_message_spacing(fallback)
        values = dict(self._exchange_pattern_values(other_call=other_call))
        values["PARK_REF"] = _compact_park_ref(self._active_p2p_park_ref or "")
        values["MY_PARK_REF"] = _compact_park_ref(self.config.my_park_ref or "")
        if extra_values:
            for name, value in extra_values.items():
                values[name] = _compact_token(value)
        return _clean_message_spacing(_render_exchange_template(template, values))

    def _prosign_token(self) -> str:
        literal = "".join(ch for ch in self.config.prosign_literal.strip().upper() if ch.isalnum())
        return f"<{literal or 'CAVE'}>"

    def _tx_closing_prosign(self) -> str:
        literal = "".join(ch for ch in self.config.prosign_literal.strip().upper() if ch.isalnum())
        return literal or "KN"

    def _exchange_pattern_values(self, *, other_call: Optional[str] = None) -> Mapping[str, str]:
        my_park = (self.config.my_park_ref or "").strip().upper() or "EA-0000"
        return {
            "MY_CALL": _compact_token(self.config.my_call),
            "OTHER_CALL": _compact_token(other_call or self._active_other_call),
            "CALL": _compact_token(other_call or self._active_other_call),
            "OTHER_CALL_REAL": _compact_token(self._active_other_call_real),
            "PROSIGN": _compact_token(self._prosign_token()),
            "TX_PROSIGN": _compact_token(self._tx_closing_prosign()),
            "PARK_REF": _compact_token(self._active_p2p_park_ref or ""),
            "MY_PARK_REF": _compact_token(my_park),
        }

    def _match_compact_exchange_patterns(
        self,
        patterns: Sequence[str],
        tokens: Sequence[str],
        *,
        other_call: Optional[str] = None,
    ) -> bool:
        compact = _compact_join(tokens)
        values = self._exchange_pattern_values(other_call=other_call)
        for raw_pattern in patterns:
            rendered = _render_exchange_pattern(raw_pattern, values)
            try:
                if re.fullmatch(rendered, compact):
                    return True
            except re.error:
                self._log("WARN", f"Regex invalida en patron de intercambio: {raw_pattern}", self.state)
        return False

    def _legacy_s2_missing_tokens(self, tokens: Sequence[str], *, call: str, require_call: bool) -> List[str]:
        missing: List[str] = []
        if require_call and _count_token_flexible(tokens, call) < 1:
            missing.append(call)
        report_count = _count_valid_s2_reports(tokens)
        if report_count < 2:
            missing.append("RST RST")
        return missing

    def _log(self, level: str, message: str, state: QSOState) -> None:
        self.logs.append(
            {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "level": level,
                "state": state.value,
                "message": message,
            }
        )
        if len(self.logs) > 2000:
            self.logs = self.logs[-1000:]

    def _complete_qso_with_reply(self, reply: str, interim_state: QSOState, info: str) -> QSOResult:
        completed_call = self._formatted_completion_other_call()
        self.state = interim_state
        self.tx_transcript.append(reply)
        self._log("TX", reply, self.state)

        completion = QSOCompletion(
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            my_call=self.config.my_call.upper(),
            other_call=completed_call,
            transcript_rx=list(self.rx_transcript),
            transcript_tx=list(self.tx_transcript),
        )
        self.completions.append(completion)
        self._log("INFO", "QSO completado", self.state)

        self.state = QSOState.S0_IDLE
        self._active_other_call_real = self.config.other_call.upper()
        self._active_other_call = self.config.other_call.upper()
        self._active_call_selected = False
        self._s2_rr_confirmed = False
        self._active_is_p2p = False
        self._active_p2p_park_ref = None
        out_replies = [reply]
        out_info = [info]

        if self._pending_callers:
            replies = self._emit_callers(self._pending_callers)
            out_replies.extend(replies)
            out_info.append("Estaciones pendientes vuelven a llamar.")
        else:
            incoming_replies = self._maybe_start_incoming_call_after_qso()
            if incoming_replies:
                out_replies.extend(incoming_replies)
                out_info.append("Nueva estacion entrante. Se omite CQ y pasamos directo a contestar.")

        return QSOResult(
            state=self.state,
            accepted=True,
            replies=out_replies,
            info=out_info,
        )

    def _formatted_completion_other_call(self) -> str:
        if self._active_is_p2p and self._active_p2p_park_ref:
            return f"{self._active_other_call_real} (P2P) {self._active_p2p_park_ref}"
        return self._active_other_call_real

    def _select_other_call_for_qso(self) -> str:
        if self._other_call_pool:
            return random.choice(self._other_call_pool)
        return self.config.other_call.upper()

    def _draw_new_incoming_callers(self) -> List[str]:
        max_stations = max(int(self.config.max_stations), 1)
        requested = random.randint(1, max_stations)

        pool = [c.upper() for c in self._other_call_pool if c.strip()]
        if not pool:
            self._pending_p2p_real_call = None
            return [self.config.other_call.upper()]

        requested = min(requested, len(pool))
        if requested <= 0:
            self._pending_p2p_real_call = None
            return [self.config.other_call.upper()]
        callers = random.sample(pool, requested)
        self._pending_p2p_real_call = self._pick_p2p_caller(callers)
        return callers

    def _emit_callers(self, callers: Sequence[str]) -> List[str]:
        # Random delay ordering (0..2s per station) is represented as random order.
        ordered = list(callers)
        random.shuffle(ordered)
        if self._pending_p2p_real_call and self._pending_p2p_real_call in ordered:
            ordered.remove(self._pending_p2p_real_call)
            ordered.insert(0, self._pending_p2p_real_call)
        self.state = QSOState.S1_REPLY_CALL
        replies: List[str] = []
        for call in ordered:
            shown = self._display_call(call)
            reply = self._build_tx_from_template(
                "caller_call",
                fallback=f"{shown} {shown}",
                other_call=shown,
                extra_values={"CALL": shown},
            )
            self.tx_transcript.append(reply)
            self._log("TX", reply, self.state)
            replies.append(reply)
        self.state = QSOState.S2_WAIT_MY_ACK_CALL
        return replies

    def _pick_p2p_caller(self, callers: Sequence[str]) -> Optional[str]:
        mode = (self.config.cq_mode or "POTA").strip().upper()
        if mode != "POTA":
            return None
        if not self._park_ref_pool:
            return None
        p = max(0.0, min(1.0, float(self.config.p2p_probability)))
        if p <= 0.0:
            return None
        if random.random() >= p:
            return None
        if not callers:
            return None
        return random.choice(list(callers))

    def _display_call(self, real_call: str) -> str:
        if self._pending_p2p_real_call and real_call == self._pending_p2p_real_call:
            return "P2P"
        return real_call

    def _pick_park_ref(self) -> Optional[str]:
        if not self._park_ref_pool:
            return None
        return random.choice(self._park_ref_pool)

    def _find_exact_pending_call(self, tokens: Sequence[str]) -> Optional[str]:
        if not self._pending_callers:
            return None
        hay = _compact_join(tokens)
        best: Optional[Tuple[int, str]] = None
        for call in self._pending_callers:
            needle = _compact_token(self._display_call(call))
            pos = hay.find(needle)
            if pos < 0:
                continue
            if best is None or pos < best[0]:
                best = (pos, call)
        return best[1] if best else None

    def _select_pending_station(self, call: str) -> None:
        self._active_other_call_real = call
        self._active_is_p2p = bool(self._pending_p2p_real_call and call == self._pending_p2p_real_call)
        if self._active_is_p2p:
            self._active_other_call = "P2P"
            self._active_p2p_park_ref = self._pick_park_ref()
        else:
            self._active_other_call = call
            self._active_p2p_park_ref = None
        if self._pending_p2p_real_call and call == self._pending_p2p_real_call:
            self._pending_p2p_real_call = None
        self._active_call_selected = True
        self._s2_rr_confirmed = False
        self._pending_callers = [c for c in self._pending_callers if c != call]
        if self._pending_p2p_real_call and self._pending_p2p_real_call not in self._pending_callers:
            self._pending_p2p_real_call = None

    def _match_pending_by_patterns(self, patterns: Sequence[str]) -> List[str]:
        matches: List[str] = []
        seen = set()
        for pattern in patterns:
            for call in self._pending_callers:
                if call in seen:
                    continue
                shown = self._display_call(call)
                if _wildcard_matches_call(pattern, shown):
                    seen.add(call)
                    matches.append(call)
        return matches

    def _maybe_start_incoming_call_after_qso(self) -> List[str]:
        if not self.config.auto_incoming_after_qso:
            return []

        p = float(self.config.auto_incoming_probability)
        if p <= 0.0:
            return []
        if p < 1.0 and random.random() >= p:
            return []

        self._active_call_selected = False
        self._s2_rr_confirmed = False
        self._pending_callers = self._draw_new_incoming_callers()
        return self._emit_callers(self._pending_callers)


def _render_exchange_pattern(pattern: str, values: Mapping[str, str]) -> str:
    rendered = pattern
    for name, value in values.items():
        rendered = rendered.replace(f"{{{name}}}", re.escape(value))
    return rendered


def _render_exchange_template(template: str, values: Mapping[str, str]) -> str:
    rendered = template
    for name, value in values.items():
        rendered = rendered.replace(f"{{{name}}}", value)
    return rendered


def _clean_message_spacing(text: str) -> str:
    return " ".join(part for part in text.split(" ") if part)


def _contains_subsequence(observed: Sequence[str], required: Sequence[str]) -> Tuple[bool, str]:
    pos = 0
    for req in required:
        found = False
        while pos < len(observed):
            if observed[pos] == req:
                found = True
                pos += 1
                break
            pos += 1
        if not found:
            return False, req
    return True, ""


def _contains_subsequence_flexible(observed: Sequence[str], required: Sequence[str]) -> Tuple[bool, str]:
    ok, missing = _contains_subsequence(observed, required)
    if ok:
        return True, ""

    ok_compact, missing_compact = _contains_compact_sequence(observed, required)
    if ok_compact:
        return True, ""
    return False, missing_compact or missing


def _count_valid_s2_reports(tokens: Sequence[str]) -> int:
    direct = sum(1 for tok in tokens if _is_valid_s2_report_token(tok))
    compact = len(_S2_REPORT_RE.findall(_compact_join(tokens)))
    return max(direct, compact)


def _is_valid_s2_report_token(token: str) -> bool:
    return _S2_REPORT_RE.fullmatch(_compact_token(token)) is not None


def _count_token_flexible(tokens: Sequence[str], token: str) -> int:
    direct = sum(1 for t in tokens if t == token)
    compact = _count_compact_occurrences(tokens, token)
    return max(direct, compact)


def _count_token_direct(tokens: Sequence[str], token: str) -> int:
    return sum(1 for t in tokens if t == token)


def _count_compact_occurrences(tokens: Sequence[str], token: str) -> int:
    needle = _compact_token(token)
    if not needle:
        return 0
    hay = _compact_join(tokens)
    count = 0
    start = 0
    while True:
        idx = hay.find(needle, start)
        if idx < 0:
            break
        count += 1
        start = idx + len(needle)
    return count


def _contains_compact_sequence(observed: Sequence[str], required: Sequence[str]) -> Tuple[bool, str]:
    hay = _compact_join(observed)
    pos = 0
    for req in required:
        needle = _compact_token(req)
        if not needle:
            continue
        idx = hay.find(needle, pos)
        if idx < 0:
            return False, req
        pos = idx + len(needle)
    return True, ""


def _compact_join(tokens: Sequence[str]) -> str:
    return "".join(_compact_token(tok) for tok in tokens)


def _compact_token(token: str) -> str:
    tok = token.strip().upper()
    if tok.startswith("<") and tok.endswith(">") and len(tok) > 2:
        tok = tok[1:-1]
    return tok.replace(" ", "")


def _compact_park_ref(token: str) -> str:
    return _compact_token(token).replace("-", "")


def _is_repeat_request_for_call(tokens: Sequence[str], call: str) -> bool:
    call_u = call.strip().upper()
    for tok in tokens:
        t = tok.strip().upper()
        if not t:
            continue
        if t == "?":
            return True
        if "?" in t:
            # Be permissive: any partial with '?' means "repeat your call".
            # Example: "K2?" even if decoded prefix is not exact.
            return True
    return False


def _is_full_call_query(tokens: Sequence[str], call: str) -> bool:
    call_u = call.strip().upper()
    if not call_u:
        return False
    compact = [_compact_token(t) for t in tokens if _compact_token(t)]
    joined = "".join(compact)
    if joined == f"{call_u}?":
        return True
    for i, t in enumerate(compact):
        if t == f"{call_u}?":
            return True
        if t == call_u and i + 1 < len(compact) and compact[i + 1] == "?":
            return True
    return False


def _wildcard_matches_call(pattern_token: str, call: str) -> bool:
    if not pattern_token:
        return False
    # Ham shorthand: '?' means unknown part; treat as wildcard segment.
    pattern = "^" + re.escape(pattern_token).replace(r"\?", ".*") + "$"
    try:
        return re.match(pattern, call) is not None
    except re.error:
        return False


def _extract_wildcard_patterns(tokens: Sequence[str]) -> List[str]:
    compact = [_compact_token(t) for t in tokens if _compact_token(t)]
    patterns: List[str] = []
    seen = set()
    has_any_question = False
    for tok in compact:
        if "?" not in tok:
            continue
        has_any_question = True
        # Ignore degenerate patterns like "?" that would match everything.
        if not any(ch.isalnum() for ch in tok):
            continue
        if tok in seen:
            continue
        seen.add(tok)
        patterns.append(tok)

    joined = "".join(compact)
    if "?" in joined:
        has_any_question = True
    if "?" in joined and any(ch.isalnum() for ch in joined) and joined not in seen:
        patterns.append(joined)
    if not patterns and has_any_question:
        # Bare '?' means "repeat all callers in queue".
        patterns.append("?")
    return patterns


def _strip_fillers(tokens: Sequence[str], ignore_bk: bool, ignore_tokens: Sequence[str]) -> List[str]:
    single_char_tokens = sum(1 for t in tokens if len(_compact_token(t)) == 1)
    # In char-by-char sends (e.g. "U R"), dropping filler tokens like "R"
    # would destroy valid words. In that mode, keep the raw stream.
    if single_char_tokens >= max(4, int(0.6 * max(len(tokens), 1))):
        return list(tokens)

    fillers = set(ignore_tokens)
    if ignore_bk:
        fillers.add("BK")
    return [t for t in tokens if t not in fillers]


def _collapse_double_e(tokens: Sequence[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(tokens):
        if i + 1 < len(tokens) and tokens[i] == "E" and tokens[i + 1] == "E":
            out.append("EE")
            i += 2
            continue
        out.append(tokens[i])
        i += 1
    return out
