#!/usr/bin/env python3
"""Create center-cropped image variants without generative changes."""

from __future__ import annotations

import argparse
from pathlib import Path
from PIL import Image


def parse_size(value: str) -> tuple[int, int]:
    width, separator, height = value.lower().partition("x")
    if not separator or not width.isdigit() or not height.isdigit() or int(width) <= 0 or int(height) <= 0:
        raise argparse.ArgumentTypeError("size must be WIDTHxHEIGHT")
    return int(width), int(height)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--variant", action="append", required=True, help="NAME=WIDTHxHEIGHT")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(args.input) as source:
        image = source.convert("RGBA" if "A" in source.getbands() else "RGB")
        seen_names: set[str] = set()
        for raw in args.variant:
            name, separator, size_raw = raw.partition("=")
            if not separator or not name or Path(name).name != name or name in {".", ".."}:
                parser.error("variant must be a safe NAME=WIDTHxHEIGHT")
            if name in seen_names:
                parser.error(f"duplicate variant name: {name}")
            seen_names.add(name)
            width, height = parse_size(size_raw)
            target_ratio = width / height
            source_ratio = image.width / image.height
            if source_ratio > target_ratio:
                crop_width = round(image.height * target_ratio)
                left = (image.width - crop_width) // 2
                box = (left, 0, left + crop_width, image.height)
            else:
                crop_height = round(image.width / target_ratio)
                top = (image.height - crop_height) // 2
                box = (0, top, image.width, top + crop_height)
            output = image.crop(box).resize((width, height), Image.Resampling.LANCZOS)
            path = args.output_dir / f"{name}.png"
            if path.exists() or path.is_symlink():
                parser.error(f"refusing to overwrite variant: {path}")
            output.save(path, format="PNG", optimize=True)
            print(path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
