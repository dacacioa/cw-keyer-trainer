from __future__ import annotations

import argparse
import re
from pathlib import Path


def _normalize_version(version: str) -> tuple[int, int, int, int]:
    parts = [int(part) for part in re.findall(r"\d+", version or "")]
    normalized = (parts + [0, 0, 0, 0])[:4]
    return tuple(normalized)  # type: ignore[return-value]


def build_version_info(
    version: str,
    *,
    company_name: str,
    file_description: str,
    internal_name: str,
    original_filename: str,
    product_name: str,
) -> str:
    v1, v2, v3, v4 = _normalize_version(version)
    display_version = f"{v1}.{v2}.{v3}.{v4}"
    return f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({v1}, {v2}, {v3}, {v4}),
    prodvers=({v1}, {v2}, {v3}, {v4}),
    mask=0x3F,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '040904B0',
          [
            StringStruct('CompanyName', '{company_name}'),
            StringStruct('FileDescription', '{file_description}'),
            StringStruct('FileVersion', '{display_version}'),
            StringStruct('InternalName', '{internal_name}'),
            StringStruct('OriginalFilename', '{original_filename}'),
            StringStruct('ProductName', '{product_name}'),
            StringStruct('ProductVersion', '{display_version}')
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Write a PyInstaller Windows version resource file.")
    parser.add_argument("--version", required=True, help="Semantic version or git tag (for example v1.2.3).")
    parser.add_argument("--output", required=True, help="Output path for the version resource text file.")
    parser.add_argument("--company-name", default="dacacioa", help="CompanyName string resource.")
    parser.add_argument("--file-description", default="CW Key trainer", help="FileDescription string resource.")
    parser.add_argument("--internal-name", default="CWKeyTrainer", help="InternalName string resource.")
    parser.add_argument("--original-filename", default="CWKeyTrainer.exe", help="OriginalFilename string resource.")
    parser.add_argument("--product-name", default="CWKeyTrainer", help="ProductName string resource.")
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        build_version_info(
            args.version,
            company_name=args.company_name,
            file_description=args.file_description,
            internal_name=args.internal_name,
            original_filename=args.original_filename,
            product_name=args.product_name,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
