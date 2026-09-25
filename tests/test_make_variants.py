from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "make_variants.py"


class VariantTests(unittest.TestCase):
    def run_variants(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(SCRIPT), *args], text=True, capture_output=True, check=False)

    def test_preserves_alpha_and_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.png"
            output_dir = root / "out"
            Image.new("RGBA", (64, 32), (20, 30, 40, 100)).save(source)
            first = self.run_variants(str(source), "--variant", "square=32x32", "--output-dir", str(output_dir))
            self.assertEqual(first.returncode, 0, first.stderr)
            with Image.open(output_dir / "square.png") as image:
                self.assertEqual(image.mode, "RGBA")
            second = self.run_variants(str(source), "--variant", "square=32x32", "--output-dir", str(output_dir))
            self.assertNotEqual(second.returncode, 0)
            self.assertIn("refusing to overwrite variant", second.stderr)

    def test_rejects_unsafe_variant_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.png"
            Image.new("RGB", (64, 32)).save(source)
            result = self.run_variants(
                str(source),
                "--variant",
                "../escape=32x32",
                "--output-dir",
                str(root / "out"),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("safe NAME=WIDTHxHEIGHT", result.stderr)


if __name__ == "__main__":
    unittest.main()
