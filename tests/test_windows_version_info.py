from __future__ import annotations

from scripts.write_windows_version_info import _normalize_version, build_version_info


def test_normalize_version_pads_to_four_parts() -> None:
    assert _normalize_version("v1.2.3") == (1, 2, 3, 0)


def test_normalize_version_keeps_first_four_numeric_groups() -> None:
    assert _normalize_version("2026.03.07.5-beta.9") == (2026, 3, 7, 5)


def test_build_version_info_contains_expected_strings() -> None:
    text = build_version_info(
        "v1.2.3",
        company_name="dacacioa",
        file_description="CW Key trainer",
        internal_name="CWKeyTrainer",
        original_filename="CWKeyTrainer.exe",
        product_name="CWKeyTrainer",
    )

    assert "filevers=(1, 2, 3, 0)" in text
    assert "prodvers=(1, 2, 3, 0)" in text
    assert "StringStruct('OriginalFilename', 'CWKeyTrainer.exe')" in text
