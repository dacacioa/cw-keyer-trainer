from __future__ import annotations

from pathlib import Path

from core.qso_state_machine import QSOConfig
from ui.app import _resolve_config_path, _resolve_runtime_path, _runtime_qso_config


def test_resolve_config_path_defaults_to_app_base_dir():
    base_dir = Path.cwd() / "__bundle__"

    assert _resolve_config_path(None, base_dir) == base_dir / "config.yaml"
    assert _resolve_config_path("config.yaml", base_dir) == base_dir / "config.yaml"


def test_resolve_runtime_path_prefers_existing_cwd_candidate():
    base_dir = Path.cwd() / "__bundle__"

    resolved = _resolve_runtime_path("README.md", base_dir)

    assert resolved == Path.cwd() / "README.md"


def test_resolve_runtime_path_falls_back_to_base_dir_for_missing_relative_file():
    base_dir = Path.cwd() / "__bundle__"

    resolved = _resolve_runtime_path("missing-resource.csv", base_dir)

    assert resolved == base_dir / "missing-resource.csv"


def test_runtime_qso_config_resolves_relative_resource_files():
    base_dir = Path.cwd() / "__bundle__"
    cfg = QSOConfig(
        other_calls_file="calls.csv",
        parks_file="parks.csv",
        exchange_patterns_file="patterns.yaml",
    )

    runtime_cfg = _runtime_qso_config(cfg, base_dir)

    assert runtime_cfg.other_calls_file == str(base_dir / "calls.csv")
    assert runtime_cfg.parks_file == str(base_dir / "parks.csv")
    assert runtime_cfg.exchange_patterns_file == str(base_dir / "patterns.yaml")
