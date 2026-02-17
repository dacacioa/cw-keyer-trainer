from __future__ import annotations

import argparse
import json
import queue
import shutil
import sys
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, List, Optional, Sequence, Tuple

import numpy as np

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from core.config import AppConfig, load_config, save_config
from core.callsign_pool import load_callsigns_file
from core.decoder import CWDecoder
from core.encoder import CWEncoder
from core.qso_state_machine import QSOStateMachine

try:
    import sounddevice as sd
except Exception:  # pragma: no cover - optional runtime dependency
    sd = None

try:
    from PySide6 import QtCore, QtWidgets
except Exception:  # pragma: no cover - optional runtime dependency
    QtCore = None
    QtWidgets = None

if QtWidgets is not None:
    MainWindowBase = QtWidgets.QMainWindow
else:  # pragma: no cover - fallback for non-GUI modes
    class MainWindowBase:  # type: ignore[too-many-ancestors]
        pass


LOCAL_CALLS_DIR = Path("data")
LOCAL_CALLS_FILENAME = "other_calls.csv"


class AudioInputWorker:
    def __init__(self, sample_rate: int, blocksize: int, channels: int = 1):
        self.sample_rate = sample_rate
        self.blocksize = blocksize
        self.channels = channels
        self.queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=256)
        self.stream = None
        self.last_status = ""
        self.lock = threading.Lock()

    def start(self, device: Optional[int]) -> None:
        if sd is None:
            raise RuntimeError("sounddevice is not available.")
        with self.lock:
            self._stop_unlocked()
            self.stream = sd.InputStream(
                samplerate=self.sample_rate,
                blocksize=self.blocksize,
                channels=self.channels,
                device=device,
                dtype="float32",
                callback=self._callback,
            )
            self.stream.start()

    def stop(self) -> None:
        with self.lock:
            self._stop_unlocked()

    def _stop_unlocked(self) -> None:
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            finally:
                self.stream = None

    def _callback(self, indata, _frames, _time_info, status) -> None:
        if status:
            self.last_status = str(status)
        mono = np.copy(indata[:, 0] if indata.ndim == 2 else indata)
        try:
            self.queue.put_nowait(mono.astype(np.float32, copy=False))
        except queue.Full:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.queue.put_nowait(mono.astype(np.float32, copy=False))
            except queue.Full:
                pass


class AudioOutputWorker:
    def __init__(self, encoder: CWEncoder, device: Optional[int]):
        self.encoder = encoder
        self.device = device
        self.queue: queue.Queue[str] = queue.Queue(maxsize=128)
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        if not self.thread.is_alive():
            self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        try:
            self.queue.put_nowait("__STOP__")
        except queue.Full:
            pass
        if self.thread.is_alive():
            self.thread.join(timeout=1.5)

    def set_device(self, device: Optional[int]) -> None:
        self.device = device

    def enqueue(self, text: str) -> None:
        try:
            self.queue.put_nowait(text)
        except queue.Full:
            pass

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                text = self.queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if text == "__STOP__":
                break
            if sd is None:
                continue
            audio = self.encoder.encode_to_audio(text)
            try:
                sd.play(audio, samplerate=self.encoder.config.sample_rate, device=self.device, blocking=True)
            except Exception:
                pass


def list_audio_devices() -> Tuple[List[Tuple[int, str]], List[Tuple[int, str]]]:
    if sd is None:
        return [], []
    devs = sd.query_devices()
    inputs: List[Tuple[int, str]] = []
    outputs: List[Tuple[int, str]] = []
    for i, d in enumerate(devs):
        name = d.get("name", f"device-{i}")
        if d.get("max_input_channels", 0) > 0:
            inputs.append((i, name))
        if d.get("max_output_channels", 0) > 0:
            outputs.append((i, name))
    return inputs, outputs


def _find_device_position(devices: Sequence[Tuple[int, str]], device_id: Optional[int]) -> Optional[int]:
    if device_id is None:
        return None
    for pos, (idx, _) in enumerate(devices):
        if idx == device_id:
            return pos
    return None


def _load_dynamic_calls_from_config(
    state_machine: QSOStateMachine,
    cfg: AppConfig,
    log_fn,
) -> None:
    path_str = cfg.qso.other_calls_file
    if not path_str:
        return
    p = Path(path_str)
    if not p.exists():
        log_fn(f"Dynamic calls file not found: {p}")
        return
    calls = load_callsigns_file(p)
    state_machine.set_other_call_pool(calls, str(p))
    log_fn(f"Dynamic calls loaded: {len(calls)} from {p}")


def _print_devices_cli() -> int:
    ins, outs = list_audio_devices()
    print("Input devices:")
    for idx, name in ins:
        print(f"  [{idx}] {name}")
    print("Output devices:")
    for idx, name in outs:
        print(f"  [{idx}] {name}")
    return 0


def _run_simulation_cli(cfg: AppConfig, cfg_path: Path) -> int:
    state_machine = QSOStateMachine(cfg.qso)
    _load_dynamic_calls_from_config(state_machine, cfg, print)
    print("Simulation mode (stdin). Commands: /reset /k1 /export /quit")
    while True:
        try:
            line = input("rx> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        cmd = line.lower()
        if cmd == "/quit":
            break
        if cmd == "/reset":
            state_machine.reset()
            print("Reset applied.")
            continue
        if cmd == "/k1":
            state_machine.config.require_k1 = not state_machine.config.require_k1
            print(f"require_k1={state_machine.config.require_k1}")
            continue
        if cmd == "/export":
            out_dir = Path("logs")
            out_dir.mkdir(exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            out_file = out_dir / f"qso_session_sim_{stamp}.json"
            out_file.write_text(json.dumps(state_machine.export_session(), indent=2), encoding="utf-8")
            print(f"Exported to {out_file}")
            continue
        result = state_machine.process_text(line)
        print(f"state: {result.state.value}")
        for err in result.errors:
            print(f"ERR {err}")
        for info in result.info:
            print(f"INFO {info}")
        for reply in result.replies:
            print(f"TX {reply}")
    save_config(cfg_path, cfg)
    return 0


class PotaTrainerWindow(MainWindowBase):
    def __init__(self, cfg: AppConfig, cfg_path: Path):
        super().__init__()
        self.cfg = cfg
        self.cfg_path = cfg_path
        self.logs_expanded = False

        self.decoder = CWDecoder(self.cfg.decoder)
        self.encoder = CWEncoder(self.cfg.encoder)
        self._sync_encoder_prosign_tokens()
        self.state_machine = QSOStateMachine(self.cfg.qso)

        self.last_decoded = ""
        self.last_tx = ""
        self.decoded_buffer: Deque[str] = deque(maxlen=30)
        self.app_logs: Deque[str] = deque(maxlen=500)

        self.input_devices, self.output_devices = list_audio_devices()
        self.input_worker: Optional[AudioInputWorker] = None
        self.output_worker: Optional[AudioOutputWorker] = None

        self._build_ui()
        self._populate_devices()
        self._load_dynamic_calls_on_startup()
        self._sync_widgets_from_config()
        self._start_audio_pipeline()

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._on_timer)
        self.timer.start()

        self.setWindowTitle("CW Key trainer")
        self.resize(1100, 760)
        self._log("App started.")

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget(self)
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        root.setSpacing(6)
        root.setContentsMargins(8, 8, 8, 8)

        top_row = QtWidgets.QHBoxLayout()
        top_row.setSpacing(6)
        root.addLayout(top_row)

        left_col = QtWidgets.QVBoxLayout()
        left_col.setSpacing(6)
        right_col = QtWidgets.QVBoxLayout()
        right_col.setSpacing(6)
        top_row.addLayout(left_col, 1)
        top_row.addLayout(right_col, 3)

        qso_box = QtWidgets.QGroupBox("QSO Status")
        qso_grid = QtWidgets.QGridLayout(qso_box)
        self.state_label = QtWidgets.QLabel("-")
        qso_grid.addWidget(QtWidgets.QLabel("State"), 0, 0)
        qso_grid.addWidget(self.state_label, 0, 1)
        left_col.addWidget(qso_box, 0)

        sig_box = QtWidgets.QGroupBox("Signal")
        sig_grid = QtWidgets.QGridLayout(sig_box)
        self.level_bar = QtWidgets.QProgressBar()
        self.level_bar.setRange(0, 100)
        self.level_text = QtWidgets.QLabel("-120.0 dBFS")
        self.tone_label = QtWidgets.QLabel("- Hz")
        self.wpm_label = QtWidgets.QLabel("-")
        self.key_label = QtWidgets.QLabel("UP")
        sig_grid.addWidget(QtWidgets.QLabel("Audio level"), 0, 0)
        sig_grid.addWidget(self.level_bar, 0, 1)
        sig_grid.addWidget(self.level_text, 0, 2)
        sig_grid.addWidget(QtWidgets.QLabel("Tone"), 1, 0)
        sig_grid.addWidget(self.tone_label, 1, 1, 1, 2)
        sig_grid.addWidget(QtWidgets.QLabel("WPM"), 2, 0)
        sig_grid.addWidget(self.wpm_label, 2, 1, 1, 2)
        sig_grid.addWidget(QtWidgets.QLabel("Key"), 3, 0)
        sig_grid.addWidget(self.key_label, 3, 1, 1, 2)
        left_col.addWidget(sig_box, 1)

        ctrl_box = QtWidgets.QGroupBox("Runtime Controls")
        ctrl_grid = QtWidgets.QGridLayout(ctrl_box)
        self.input_combo = QtWidgets.QComboBox()
        self.output_combo = QtWidgets.QComboBox()
        self.reset_button = QtWidgets.QPushButton("Reset")
        self.restart_qso_button = QtWidgets.QPushButton("Restart QSO")
        self.cal_button = QtWidgets.QPushButton("Calibrate")
        self.export_button = QtWidgets.QPushButton("Export Log")
        self.load_calls_file_button = QtWidgets.QPushButton("Load Calls File")
        self.auto_wpm_cb = QtWidgets.QCheckBox("Auto WPM")
        self.auto_tone_cb = QtWidgets.QCheckBox("Auto Tone")
        self.require_k1_cb = QtWidgets.QCheckBox("Require K1")
        self.calls_file_label = QtWidgets.QLabel("(none)")
        self.calls_file_label.setWordWrap(True)
        self.calls_pool_label = QtWidgets.QLabel("0")
        ctrl_grid.addWidget(QtWidgets.QLabel("Input"), 0, 0)
        ctrl_grid.addWidget(self.input_combo, 0, 1, 1, 5)
        ctrl_grid.addWidget(QtWidgets.QLabel("Output"), 1, 0)
        ctrl_grid.addWidget(self.output_combo, 1, 1, 1, 5)
        ctrl_grid.addWidget(self.auto_wpm_cb, 2, 0)
        ctrl_grid.addWidget(self.auto_tone_cb, 2, 1)
        ctrl_grid.addWidget(self.require_k1_cb, 2, 2)
        ctrl_grid.addWidget(self.reset_button, 3, 0)
        ctrl_grid.addWidget(self.cal_button, 3, 1)
        ctrl_grid.addWidget(self.restart_qso_button, 3, 2)
        ctrl_grid.addWidget(self.export_button, 3, 3)
        ctrl_grid.addWidget(self.load_calls_file_button, 3, 4, 1, 2)
        ctrl_grid.addWidget(QtWidgets.QLabel("Calls file"), 4, 0)
        ctrl_grid.addWidget(self.calls_file_label, 4, 1, 1, 4)
        ctrl_grid.addWidget(QtWidgets.QLabel("Pool"), 4, 5)
        ctrl_grid.addWidget(self.calls_pool_label, 4, 6)
        right_col.addWidget(ctrl_box, 0)

        settings_box = QtWidgets.QGroupBox("QSO/Decoder/Encoder Settings")
        settings_grid = QtWidgets.QGridLayout(settings_box)
        self.my_call_edit = QtWidgets.QLineEdit()
        self.cq_simple_cb = QtWidgets.QCheckBox("Simple")
        self.cq_pota_cb = QtWidgets.QCheckBox("POTA")
        self.cq_sota_cb = QtWidgets.QCheckBox("SOTA")
        self.cq_mode_group = QtWidgets.QButtonGroup(self)
        self.cq_mode_group.setExclusive(True)
        self.cq_mode_group.addButton(self.cq_simple_cb, 0)
        self.cq_mode_group.addButton(self.cq_pota_cb, 1)
        self.cq_mode_group.addButton(self.cq_sota_cb, 2)
        self.cq_pota_cb.setChecked(True)
        self.prosign_edit = QtWidgets.QLineEdit()
        self.wpm_target_spin = QtWidgets.QDoubleSpinBox()
        self.wpm_target_spin.setRange(5.0, 60.0)
        self.wpm_target_spin.setDecimals(1)
        self.tone_rx_spin = QtWidgets.QDoubleSpinBox()
        self.tone_rx_spin.setRange(300.0, 2000.0)
        self.tone_rx_spin.setDecimals(1)
        self.th_on_spin = QtWidgets.QDoubleSpinBox()
        self.th_on_spin.setRange(1.0, 20.0)
        self.th_on_spin.setDecimals(2)
        self.th_off_spin = QtWidgets.QDoubleSpinBox()
        self.th_off_spin.setRange(1.0, 20.0)
        self.th_off_spin.setDecimals(2)
        self.power_smooth_spin = QtWidgets.QDoubleSpinBox()
        self.power_smooth_spin.setRange(0.05, 1.0)
        self.power_smooth_spin.setDecimals(2)
        self.gap_char_spin = QtWidgets.QDoubleSpinBox()
        self.gap_char_spin.setRange(1.2, 4.0)
        self.gap_char_spin.setDecimals(2)
        self.min_up_ratio_spin = QtWidgets.QDoubleSpinBox()
        self.min_up_ratio_spin.setRange(0.0, 1.0)
        self.min_up_ratio_spin.setDecimals(2)
        self.message_gap_sec_spin = QtWidgets.QDoubleSpinBox()
        self.message_gap_sec_spin.setRange(0.05, 30.0)
        self.message_gap_sec_spin.setDecimals(2)
        self.message_gap_sec_spin.setSingleStep(0.05)
        self.message_gap_sec_spin.setSuffix(" s")
        self.wpm_tx_spin = QtWidgets.QDoubleSpinBox()
        self.wpm_tx_spin.setRange(5.0, 60.0)
        self.wpm_tx_spin.setDecimals(1)
        self.tone_tx_spin = QtWidgets.QDoubleSpinBox()
        self.tone_tx_spin.setRange(300.0, 2000.0)
        self.tone_tx_spin.setDecimals(1)
        self.allow_599_cb = QtWidgets.QCheckBox("Allow 599")
        self.allow_tu_cb = QtWidgets.QCheckBox("Allow TU")
        self.use_prosigns_cb = QtWidgets.QCheckBox("Use Prosigns")
        self.incoming_prob_combo = QtWidgets.QComboBox()
        for pct in (0, 25, 50, 75, 100):
            self.incoming_prob_combo.addItem(f"{pct} %", pct)
        self.apply_button = QtWidgets.QPushButton("Apply Settings")

        # Keep settings compact and aligned in the top panel.
        self.my_call_edit.setMaximumWidth(140)
        self.prosign_edit.setMaximumWidth(80)
        for spin in (
            self.wpm_target_spin,
            self.tone_rx_spin,
            self.th_on_spin,
            self.th_off_spin,
            self.power_smooth_spin,
            self.gap_char_spin,
            self.min_up_ratio_spin,
            self.message_gap_sec_spin,
            self.wpm_tx_spin,
            self.tone_tx_spin,
        ):
            spin.setMaximumWidth(90)
        self.incoming_prob_combo.setMaximumWidth(100)

        cq_mode_row = QtWidgets.QHBoxLayout()
        cq_mode_row.addWidget(self.cq_simple_cb)
        cq_mode_row.addWidget(self.cq_pota_cb)
        cq_mode_row.addWidget(self.cq_sota_cb)
        cq_mode_row.setContentsMargins(0, 0, 0, 0)
        options_row = QtWidgets.QHBoxLayout()
        options_row.addWidget(self.allow_599_cb)
        options_row.addWidget(self.allow_tu_cb)
        options_row.addWidget(self.use_prosigns_cb)
        options_row.setContentsMargins(0, 0, 0, 0)

        settings_grid.addWidget(QtWidgets.QLabel("my_call"), 0, 0)
        settings_grid.addWidget(self.my_call_edit, 0, 1)
        settings_grid.addWidget(QtWidgets.QLabel("prosign"), 0, 2)
        settings_grid.addWidget(self.prosign_edit, 0, 3)
        settings_grid.addWidget(QtWidgets.QLabel("cq_mode"), 0, 4)
        settings_grid.addLayout(cq_mode_row, 0, 5, 1, 2)

        settings_grid.addWidget(QtWidgets.QLabel("wpm_target"), 1, 0)
        settings_grid.addWidget(self.wpm_target_spin, 1, 1)
        settings_grid.addWidget(QtWidgets.QLabel("wpm_out"), 1, 2)
        settings_grid.addWidget(self.wpm_tx_spin, 1, 3)
        settings_grid.addWidget(QtWidgets.QLabel("incoming_%"), 1, 4)
        settings_grid.addWidget(self.incoming_prob_combo, 1, 5)

        settings_grid.addWidget(QtWidgets.QLabel("tone_hz_rx"), 2, 0)
        settings_grid.addWidget(self.tone_rx_spin, 2, 1)
        settings_grid.addWidget(QtWidgets.QLabel("tone_hz_out"), 2, 2)
        settings_grid.addWidget(self.tone_tx_spin, 2, 3)
        settings_grid.addWidget(QtWidgets.QLabel("message_gap_s"), 2, 4)
        settings_grid.addWidget(self.message_gap_sec_spin, 2, 5)

        settings_grid.addWidget(QtWidgets.QLabel("threshold_on"), 3, 0)
        settings_grid.addWidget(self.th_on_spin, 3, 1)
        settings_grid.addWidget(QtWidgets.QLabel("threshold_off"), 3, 2)
        settings_grid.addWidget(self.th_off_spin, 3, 3)
        settings_grid.addWidget(QtWidgets.QLabel("power_smooth"), 3, 4)
        settings_grid.addWidget(self.power_smooth_spin, 3, 5)

        settings_grid.addWidget(QtWidgets.QLabel("gap_char_dots"), 4, 0)
        settings_grid.addWidget(self.gap_char_spin, 4, 1)
        settings_grid.addWidget(QtWidgets.QLabel("min_up_ratio"), 4, 2)
        settings_grid.addWidget(self.min_up_ratio_spin, 4, 3)
        settings_grid.addLayout(options_row, 4, 4, 1, 2)

        settings_grid.addWidget(self.apply_button, 5, 0, 1, 7)
        right_col.addWidget(settings_box, 1)

        log_toggle_row = QtWidgets.QHBoxLayout()
        self.clear_decoded_button = QtWidgets.QPushButton("Clear Decoding")
        log_toggle_row.addWidget(self.clear_decoded_button)
        log_toggle_row.addStretch(1)
        self.logs_toggle_button = QtWidgets.QToolButton()
        self.logs_toggle_button.setCheckable(True)
        self.logs_toggle_button.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        log_toggle_row.addWidget(self.logs_toggle_button)
        root.addLayout(log_toggle_row)

        self.text_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.copied_view = QtWidgets.QPlainTextEdit()
        self.copied_view.setReadOnly(True)
        self.logs_view = QtWidgets.QPlainTextEdit()
        self.logs_view.setReadOnly(True)
        self.text_splitter.addWidget(self.copied_view)
        self.text_splitter.addWidget(self.logs_view)
        self.text_splitter.setSizes([240, 300])
        root.addWidget(self.text_splitter, 1)
        self._set_logs_expanded(False)

        self.reset_button.clicked.connect(self._on_reset)
        self.restart_qso_button.clicked.connect(self._on_restart_qso)
        self.cal_button.clicked.connect(self._on_calibrate)
        self.export_button.clicked.connect(self._on_export)
        self.load_calls_file_button.clicked.connect(self._on_load_calls_file)
        self.auto_wpm_cb.toggled.connect(self._on_auto_wpm_toggled)
        self.auto_tone_cb.toggled.connect(self._on_auto_tone_toggled)
        self.require_k1_cb.toggled.connect(self._on_require_k1_toggled)
        self.input_combo.currentIndexChanged.connect(self._on_input_changed)
        self.output_combo.currentIndexChanged.connect(self._on_output_changed)
        self.apply_button.clicked.connect(self._on_apply_settings)
        self.clear_decoded_button.clicked.connect(self._on_clear_decoding)
        self.logs_toggle_button.toggled.connect(self._on_logs_toggled)

    def _populate_devices(self) -> None:
        self.input_combo.blockSignals(True)
        self.output_combo.blockSignals(True)
        self.input_combo.clear()
        self.output_combo.clear()

        self.input_combo.addItem("System default", None)
        for idx, name in self.input_devices:
            self.input_combo.addItem(f"[{idx}] {name}", idx)
        self.output_combo.addItem("System default", None)
        for idx, name in self.output_devices:
            self.output_combo.addItem(f"[{idx}] {name}", idx)

        self.input_combo.blockSignals(False)
        self.output_combo.blockSignals(False)

    def _sync_widgets_from_config(self) -> None:
        self.my_call_edit.setText(self.cfg.qso.my_call)
        self._set_cq_mode_widget(self.cfg.qso.cq_mode)
        self.prosign_edit.setText(self.cfg.qso.prosign_literal)
        self.wpm_target_spin.setValue(self.cfg.decoder.wpm_target)
        self.tone_rx_spin.setValue(self.cfg.decoder.target_tone_hz)
        self.th_on_spin.setValue(self.cfg.decoder.threshold_on_mult)
        self.th_off_spin.setValue(self.cfg.decoder.threshold_off_mult)
        self.power_smooth_spin.setValue(self.cfg.decoder.power_smooth_alpha)
        self.gap_char_spin.setValue(self.cfg.decoder.gap_char_threshold_dots)
        self.min_up_ratio_spin.setValue(self.cfg.decoder.min_key_up_dot_ratio)
        if self.cfg.decoder.message_gap_seconds and self.cfg.decoder.message_gap_seconds > 0.0:
            self.message_gap_sec_spin.setValue(self.cfg.decoder.message_gap_seconds)
        else:
            self.message_gap_sec_spin.setValue(self.cfg.decoder.message_gap_dots * self.cfg.decoder.dot_seconds_fixed)
        self.wpm_tx_spin.setValue(self.cfg.encoder.wpm)
        self.tone_tx_spin.setValue(self.cfg.encoder.tone_hz)
        self.allow_599_cb.setChecked(self.cfg.qso.allow_599)
        self.allow_tu_cb.setChecked(self.cfg.qso.allow_tu)
        self.use_prosigns_cb.setChecked(self.cfg.qso.use_prosigns)
        incoming_pct = 0
        if self.cfg.qso.auto_incoming_after_qso:
            incoming_pct = int(
                round(max(0.0, min(1.0, float(self.cfg.qso.auto_incoming_probability))) * 100.0)
            )
        allowed = (0, 25, 50, 75, 100)
        incoming_pct = min(allowed, key=lambda v: abs(v - incoming_pct))
        self._set_combo_by_value(self.incoming_prob_combo, incoming_pct)
        self.auto_wpm_cb.setChecked(self.cfg.decoder.auto_wpm)
        self.auto_tone_cb.setChecked(self.cfg.decoder.auto_tone)
        self.require_k1_cb.setChecked(self.cfg.qso.require_k1)
        self._set_combo_by_device_id(self.input_combo, self.cfg.audio.input_device)
        self._set_combo_by_device_id(self.output_combo, self.cfg.audio.output_device)
        self._refresh_calls_file_status()
        self._refresh_status_labels()

    def _load_dynamic_calls_on_startup(self) -> None:
        _load_dynamic_calls_from_config(self.state_machine, self.cfg, self._log)

    def _refresh_calls_file_status(self) -> None:
        path = self.cfg.qso.other_calls_file or "(none)"
        self.calls_file_label.setText(path)
        self.calls_pool_label.setText(str(self.state_machine.other_call_pool_size))

    def _local_calls_file_path(self) -> Path:
        LOCAL_CALLS_DIR.mkdir(parents=True, exist_ok=True)
        return LOCAL_CALLS_DIR / LOCAL_CALLS_FILENAME

    def _on_load_calls_file(self) -> None:
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select Callsign File",
            str(Path.cwd()),
            "Text Files (*.txt *.csv);;All Files (*.*)",
        )
        if not file_path:
            return
        src = Path(file_path)
        dst = self._local_calls_file_path()
        try:
            shutil.copy2(src, dst)
            calls = load_callsigns_file(dst)
        except Exception as exc:
            self._log(f"Failed to load calls file: {exc}")
            return
        self.state_machine.set_other_call_pool(calls, str(dst))
        self.cfg.qso.other_calls_file = str(dst)
        save_config(self.cfg_path, self.cfg)
        self._refresh_calls_file_status()
        self._log(f"Calls file loaded: {dst} ({len(calls)} calls)")

    def _set_combo_by_device_id(self, combo: QtWidgets.QComboBox, device_id: Optional[int]) -> None:
        self._set_combo_by_value(combo, device_id)

    def _set_combo_by_value(self, combo: QtWidgets.QComboBox, value: object) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return
        combo.setCurrentIndex(0)

    def _set_cq_mode_widget(self, mode: str) -> None:
        mode_u = (mode or "POTA").strip().upper()
        if mode_u == "SIMPLE":
            self.cq_simple_cb.setChecked(True)
            return
        if mode_u == "SOTA":
            self.cq_sota_cb.setChecked(True)
            return
        self.cq_pota_cb.setChecked(True)

    def _get_cq_mode_widget(self) -> str:
        if self.cq_simple_cb.isChecked():
            return "SIMPLE"
        if self.cq_sota_cb.isChecked():
            return "SOTA"
        return "POTA"

    def _start_audio_pipeline(self) -> None:
        if sd is None:
            self._log("sounddevice not installed. Audio I/O disabled.")
            return

        if self.input_worker is None:
            self.input_worker = AudioInputWorker(
                sample_rate=self.cfg.audio.sample_rate,
                blocksize=self.cfg.audio.blocksize,
                channels=self.cfg.audio.channels,
            )
        if self.output_worker is None:
            self.output_worker = AudioOutputWorker(self.encoder, self.cfg.audio.output_device)
            self.output_worker.start()

        try:
            self.input_worker.start(self.cfg.audio.input_device)
        except Exception as exc:
            self._log(f"Input start failed: {exc}")
        if self.output_worker:
            self.output_worker.set_device(self.cfg.audio.output_device)

    def _restart_input(self) -> None:
        if self.input_worker is None:
            return
        try:
            self.input_worker.start(self.cfg.audio.input_device)
            self._log("Input device restarted.")
        except Exception as exc:
            self._log(f"Cannot switch input device: {exc}")

    def _on_timer(self) -> None:
        if self.input_worker:
            while True:
                try:
                    chunk = self.input_worker.queue.get_nowait()
                except queue.Empty:
                    break
                messages = self.decoder.process_samples(chunk)
                for message in messages:
                    self._handle_decoded_message(message)
            if self.input_worker.last_status:
                self._log(f"Input status: {self.input_worker.last_status}")
                self.input_worker.last_status = ""
        self._refresh_status_labels()

    def _refresh_status_labels(self) -> None:
        stats = self.decoder.stats
        self.state_label.setText(self.state_machine.state.value)
        self.level_text.setText(f"{stats.level_db:6.1f} dBFS")
        level = int(np.clip((stats.level_db + 100.0) * 1.0, 0.0, 100.0))
        self.level_bar.setValue(level)
        self.tone_label.setText(f"{stats.tone_hz:6.1f} Hz  power={stats.tone_power:.6f}")
        self.wpm_label.setText(f"{stats.wpm_est:5.1f} (dot {stats.dot_ms:5.1f} ms)")
        self.key_label.setText("DOWN" if stats.key_down else "UP")

    def _handle_decoded_message(self, msg: str) -> None:
        text = msg.strip()
        if not text:
            return
        self.last_decoded = text
        self.decoded_buffer.append(text)
        self._refresh_decoded_view()
        self._log(f"RX {text}")

        result = self.state_machine.process_text(text)
        for err in result.errors:
            self._log(f"ERR {err}")
        for info in result.info:
            self._log(f"INFO {info}")
        for reply in result.replies:
            self.last_tx = reply
            self._log(f"TX {reply}")
            if self.output_worker:
                self.output_worker.enqueue(reply)

    def _on_reset(self) -> None:
        self.decoder.reset()
        self.state_machine.reset()
        self.last_decoded = ""
        self.last_tx = ""
        self.decoded_buffer.clear()
        self._refresh_decoded_view()
        self._log("Reset decoder + QSO state.")
        self._refresh_status_labels()

    def _on_restart_qso(self) -> None:
        self.state_machine.reset()
        self.last_decoded = ""
        self.last_tx = ""
        self.decoded_buffer.clear()
        self._refresh_decoded_view()
        self._log("QSO restarted (state -> S0).")
        self._refresh_status_labels()

    def _on_calibrate(self) -> None:
        self.decoder.recalibrate()
        self._log("Decoder recalibrated.")

    def _on_export(self) -> None:
        path = self._export_log()
        self._log(f"Log exported: {path}")

    def _on_clear_decoding(self) -> None:
        self.decoded_buffer.clear()
        self.last_decoded = ""
        self._refresh_decoded_view()
        self._log("Decoded screen cleared.")

    def _on_auto_wpm_toggled(self, checked: bool) -> None:
        self.cfg.decoder.auto_wpm = bool(checked)
        self.decoder.config.auto_wpm = bool(checked)
        self._log(f"auto_wpm={checked}")

    def _on_auto_tone_toggled(self, checked: bool) -> None:
        self.cfg.decoder.auto_tone = bool(checked)
        self.decoder.config.auto_tone = bool(checked)
        self._log(f"auto_tone={checked}")

    def _on_require_k1_toggled(self, checked: bool) -> None:
        self.cfg.qso.require_k1 = bool(checked)
        self.state_machine.config.require_k1 = bool(checked)
        self._log(f"require_k1={checked}")

    def _on_input_changed(self, _index: int) -> None:
        device_id = self.input_combo.currentData()
        self.cfg.audio.input_device = device_id
        self._restart_input()

    def _on_output_changed(self, _index: int) -> None:
        device_id = self.output_combo.currentData()
        self.cfg.audio.output_device = device_id
        if self.output_worker:
            self.output_worker.set_device(device_id)
        self._log("Output device changed.")

    def _on_logs_toggled(self, checked: bool) -> None:
        self._set_logs_expanded(bool(checked))

    def _set_logs_expanded(self, expanded: bool) -> None:
        self.logs_expanded = bool(expanded)
        if self.logs_expanded:
            self.logs_view.show()
            self.logs_toggle_button.setArrowType(QtCore.Qt.ArrowType.DownArrow)
            self.logs_toggle_button.setText("Log")
            self.text_splitter.setSizes([200, 220])
            self.logs_view.verticalScrollBar().setValue(self.logs_view.verticalScrollBar().maximum())
            return

        self.logs_view.hide()
        self.logs_toggle_button.setArrowType(QtCore.Qt.ArrowType.RightArrow)
        self.logs_toggle_button.setText("Log")
        self.text_splitter.setSizes([1, 0])

    def _on_apply_settings(self) -> None:
        self.cfg.qso.my_call = self.my_call_edit.text().strip().upper() or self.cfg.qso.my_call
        self.cfg.qso.cq_mode = self._get_cq_mode_widget()
        self.cfg.qso.prosign_literal = self.prosign_edit.text().strip().upper() or "CAVE"
        self.cfg.qso.allow_599 = self.allow_599_cb.isChecked()
        self.cfg.qso.allow_tu = self.allow_tu_cb.isChecked()
        self.cfg.qso.use_prosigns = self.use_prosigns_cb.isChecked()
        incoming_pct = int(self.incoming_prob_combo.currentData() or 0)
        self.cfg.qso.auto_incoming_after_qso = incoming_pct > 0
        self.cfg.qso.auto_incoming_probability = float(incoming_pct) / 100.0

        self.cfg.decoder.wpm_target = float(self.wpm_target_spin.value())
        self.cfg.decoder.target_tone_hz = float(self.tone_rx_spin.value())
        self.cfg.decoder.threshold_on_mult = float(self.th_on_spin.value())
        self.cfg.decoder.threshold_off_mult = float(self.th_off_spin.value())
        self.cfg.decoder.power_smooth_alpha = float(self.power_smooth_spin.value())
        self.cfg.decoder.gap_char_threshold_dots = float(self.gap_char_spin.value())
        self.cfg.decoder.min_key_up_dot_ratio = float(self.min_up_ratio_spin.value())
        self.cfg.decoder.message_gap_seconds = float(self.message_gap_sec_spin.value())
        self.cfg.decoder.auto_wpm = self.auto_wpm_cb.isChecked()
        self.cfg.decoder.auto_tone = self.auto_tone_cb.isChecked()
        self.cfg.decoder.prosign_literal = self.cfg.qso.prosign_literal

        self.cfg.encoder.wpm = float(self.wpm_tx_spin.value())
        self.cfg.encoder.tone_hz = float(self.tone_tx_spin.value())

        self.decoder = CWDecoder(self.cfg.decoder)
        self.encoder.config.wpm = self.cfg.encoder.wpm
        self.encoder.config.tone_hz = self.cfg.encoder.tone_hz
        self._sync_encoder_prosign_tokens()

        sm_cfg = self.state_machine.config
        sm_cfg.my_call = self.cfg.qso.my_call
        sm_cfg.other_call = self.cfg.qso.other_call
        sm_cfg.cq_mode = self.cfg.qso.cq_mode
        sm_cfg.prosign_literal = self.cfg.qso.prosign_literal
        sm_cfg.allow_599 = self.cfg.qso.allow_599
        sm_cfg.allow_tu = self.cfg.qso.allow_tu
        sm_cfg.use_prosigns = self.cfg.qso.use_prosigns
        sm_cfg.require_k1 = self.cfg.qso.require_k1
        sm_cfg.auto_incoming_after_qso = self.cfg.qso.auto_incoming_after_qso
        sm_cfg.auto_incoming_probability = self.cfg.qso.auto_incoming_probability

        save_config(self.cfg_path, self.cfg)
        self._refresh_calls_file_status()
        self._log(
            f"Settings applied. incoming_call={incoming_pct}% "
            f"(enabled={self.cfg.qso.auto_incoming_after_qso})"
        )
        self._refresh_status_labels()

    def _sync_encoder_prosign_tokens(self) -> None:
        literal = "".join(ch for ch in self.cfg.qso.prosign_literal.strip().upper() if ch.isalnum())
        token = literal or "KN"
        self.cfg.encoder.prosign_tokens = (token,)
        self.encoder.config.prosign_tokens = (token,)

    def _log(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"{ts} {message}"
        self.app_logs.append(line)
        self.logs_view.setPlainText("\n".join(self.app_logs))
        self.logs_view.verticalScrollBar().setValue(self.logs_view.verticalScrollBar().maximum())

    def _refresh_decoded_view(self) -> None:
        self.copied_view.setPlainText("\n".join(self.decoded_buffer))
        self.copied_view.verticalScrollBar().setValue(self.copied_view.verticalScrollBar().maximum())

    def _export_log(self) -> Path:
        out_dir = Path("logs")
        out_dir.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_file = out_dir / f"qso_session_{stamp}.json"
        payload = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "config": {
                "audio": self.cfg.audio.__dict__,
                "decoder": self.cfg.decoder.__dict__,
                "encoder": self.cfg.encoder.__dict__,
                "qso": self.cfg.qso.__dict__,
            },
            "last_decoded": self.last_decoded,
            "last_tx": self.last_tx,
            "decoded_buffer": list(self.decoded_buffer),
            "app_logs": list(self.app_logs),
            "state_machine": self.state_machine.export_session(),
        }
        out_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return out_file

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self.timer.isActive():
            self.timer.stop()
        if self.input_worker:
            self.input_worker.stop()
        if self.output_worker:
            self.output_worker.stop()
        save_config(self.cfg_path, self.cfg)
        super().closeEvent(event)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="CW POTA activator simulator/trainer")
    p.add_argument("--config", default="config.yaml", help="YAML config path.")
    p.add_argument("--simulate", action="store_true", help="Run stdin simulation mode.")
    p.add_argument("--list-devices", action="store_true", help="List audio devices and exit.")
    p.add_argument("--input-device", type=int, default=None, help="Input device index.")
    p.add_argument("--output-device", type=int, default=None, help="Output device index.")
    p.add_argument("--my-call", default=None, help="My callsign.")
    p.add_argument("--other-call", default=None, help="Other station callsign.")
    p.add_argument("--cq-mode", choices=["SIMPLE", "POTA", "SOTA"], default=None, help="CQ mode keyword.")
    p.add_argument("--other-calls-file", default=None, help="Path to dynamic callsign file.")
    p.add_argument("--wpm-target", type=float, default=None, help="Decoder target WPM.")
    p.add_argument("--wpm-out", type=float, default=None, help="Encoder output WPM.")
    p.add_argument("--tone-hz", type=float, default=None, help="RX tone target.")
    p.add_argument("--tone-out-hz", type=float, default=None, help="TX tone.")
    p.add_argument("--message-gap-sec", type=float, default=None, help="Message-end silence in seconds.")
    p.add_argument("--auto-wpm", action="store_true", help="Force auto WPM on.")
    p.add_argument("--fixed-wpm", action="store_true", help="Force auto WPM off.")
    p.add_argument("--auto-tone", action="store_true", help="Force auto tone tracking on.")
    p.add_argument("--fixed-tone", action="store_true", help="Force fixed RX tone mode.")
    p.add_argument("--legacy-flow", action="store_true", help="Use legacy multi-step QSO flow.")
    p.add_argument("--direct-flow", action="store_true", help="Use direct report->final reply flow.")
    p.add_argument("--require-k1", action="store_true", help="Require K1 in S0 close.")
    p.add_argument("--allow-599", action="store_true", help="Accept 599 variants.")
    p.add_argument("--allow-tu", action="store_true", help="Accept optional TU.")
    p.add_argument("--disable-prosigns", action="store_true", help="Disable prosign requirement/replies.")
    p.add_argument("--prosign-literal", default=None, help="Special prosign literal (default CAVE).")
    p.add_argument("--s4-prefix", choices=["R", "RR"], default=None, help="S4 reply prefix.")
    return p


def _apply_cli_overrides(cfg: AppConfig, args: argparse.Namespace) -> None:
    if args.input_device is not None:
        cfg.audio.input_device = args.input_device
    if args.output_device is not None:
        cfg.audio.output_device = args.output_device
    if args.my_call:
        cfg.qso.my_call = args.my_call.upper()
    if args.other_call:
        cfg.qso.other_call = args.other_call.upper()
    if args.cq_mode:
        cfg.qso.cq_mode = args.cq_mode.upper()
    if args.other_calls_file:
        cfg.qso.other_calls_file = args.other_calls_file
    if args.wpm_target is not None:
        cfg.decoder.wpm_target = args.wpm_target
    if args.wpm_out is not None:
        cfg.encoder.wpm = args.wpm_out
    if args.message_gap_sec is not None:
        cfg.decoder.message_gap_seconds = args.message_gap_sec
    if args.tone_hz is not None:
        cfg.decoder.target_tone_hz = args.tone_hz
    if args.tone_out_hz is not None:
        cfg.encoder.tone_hz = args.tone_out_hz
    if args.auto_wpm:
        cfg.decoder.auto_wpm = True
    if args.fixed_wpm:
        cfg.decoder.auto_wpm = False
    if args.auto_tone:
        cfg.decoder.auto_tone = True
    if args.fixed_tone:
        cfg.decoder.auto_tone = False
    if args.legacy_flow:
        cfg.qso.direct_report_mode = False
    if args.direct_flow:
        cfg.qso.direct_report_mode = True
    if args.require_k1:
        cfg.qso.require_k1 = True
    if args.allow_599:
        cfg.qso.allow_599 = True
    if args.allow_tu:
        cfg.qso.allow_tu = True
    if args.disable_prosigns:
        cfg.qso.use_prosigns = False
    if args.prosign_literal:
        cfg.qso.prosign_literal = args.prosign_literal.upper()
    if args.s4_prefix:
        cfg.qso.s4_prefix = args.s4_prefix

    cfg.decoder.sample_rate = cfg.audio.sample_rate
    cfg.encoder.sample_rate = cfg.audio.sample_rate
    cfg.decoder.prosign_literal = cfg.qso.prosign_literal
    literal = "".join(ch for ch in cfg.qso.prosign_literal.strip().upper() if ch.isalnum())
    cfg.encoder.prosign_tokens = (literal or "KN",)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    cfg_path = Path(args.config)
    cfg = load_config(cfg_path)
    _apply_cli_overrides(cfg, args)

    if args.list_devices:
        return _print_devices_cli()
    if args.simulate:
        return _run_simulation_cli(cfg, cfg_path)

    if QtWidgets is None:
        print("PySide6 is not installed. Install with: python -m pip install PySide6")
        return 2

    qt_app = QtWidgets.QApplication([])
    window = PotaTrainerWindow(cfg, cfg_path)
    window.show()
    return qt_app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
