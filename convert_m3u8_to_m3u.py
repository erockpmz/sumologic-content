#!/usr/bin/env python3
"""Convert .m3u8 playlist files to .m3u for Walkman compatibility.

- Keeps playlist content lines intact by default.
- Normalizes slashes to forward `/`.
- Strips UTF-8 BOM on read.
- Writes UTF-8 text with LF line endings.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def convert_file(src: Path, out_dir: Path | None, overwrite: bool, keep_original: bool) -> Path:
    text = src.read_text(encoding="utf-8-sig", errors="replace")

    lines = []
    for raw in text.splitlines():
        line = raw.rstrip("\r\n")
        if line and not line.startswith("#"):
            line = line.replace("\\", "/")
        lines.append(line)

    target_dir = out_dir if out_dir is not None else src.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    dst = target_dir / f"{src.stem}.m3u"

    if dst.exists() and not overwrite:
        raise FileExistsError(f"Target already exists: {dst} (use --overwrite)")

    dst.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    if not keep_original:
        src.unlink()

    return dst


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert .m3u8 files to .m3u")
    parser.add_argument("--input", required=True, help="File or directory containing .m3u8 files")
    parser.add_argument("--out-dir", default=None, help="Optional output directory (default: same as source)")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing .m3u targets")
    parser.add_argument(
        "--keep-original",
        action="store_true",
        help="Keep original .m3u8 files (default: remove originals after successful conversion)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    src = Path(args.input).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else None

    if not src.exists():
        raise SystemExit(f"Input path does not exist: {src}")

    files = [src] if src.is_file() else sorted(src.rglob("*.m3u8"))
    files = [f for f in files if f.suffix.lower() == ".m3u8"]
    if not files:
        raise SystemExit("No .m3u8 files found.")

    converted: list[Path] = []
    for file in files:
        dst = convert_file(file, out_dir, args.overwrite, args.keep_original)
        converted.append(dst)
        print(f"Converted: {file} -> {dst}")

    print(f"Done. Converted {len(converted)} playlist(s).")


if __name__ == "__main__":
    main()
