#!/usr/bin/env python3
"""Report deterministic image metadata and SHA-256."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from PIL import Image


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", type=Path)
    args = parser.parse_args()
    records = []
    for path in args.images:
        content = path.read_bytes()
        with Image.open(path) as image:
            records.append({
                "path": str(path.resolve()),
                "format": image.format,
                "width": image.width,
                "height": image.height,
                "mode": image.mode,
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
            })
    print(json.dumps({"images": records}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
