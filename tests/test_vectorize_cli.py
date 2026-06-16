import os
import subprocess
import sys
import tempfile
import unittest

from PIL import Image, ImageDraw


class VectorizeCliTests(unittest.TestCase):
    def _make_test_image(self) -> str:
        handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        handle.close()
        image = Image.new("RGB", (40, 30), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((4, 4, 20, 25), fill=(200, 30, 30))
        draw.ellipse((22, 6, 36, 24), fill=(20, 80, 200))
        image.save(handle.name)
        return handle.name

    def test_require_visual_model_returns_nonzero_without_vlm(self):
        image_path = self._make_test_image()
        jsx_path = tempfile.NamedTemporaryFile(suffix=".jsx", delete=False).name
        os.unlink(jsx_path)

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "illustrator.vectorize_cli",
                    image_path,
                    "--jsx",
                    jsx_path,
                    "--layer-provider",
                    "heuristic",
                    "--require-visual-model",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("Visual model layer planning is required", result.stdout)
            self.assertFalse(os.path.exists(jsx_path))
        finally:
            os.unlink(image_path)
            if os.path.exists(jsx_path):
                os.unlink(jsx_path)

    def test_image_trace_mode_writes_jsx_and_prepared_source(self):
        image_path = self._make_test_image()
        jsx_path = tempfile.NamedTemporaryFile(suffix=".jsx", delete=False).name
        os.unlink(jsx_path)
        prepared_path = os.path.splitext(jsx_path)[0] + "_source.png"

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "illustrator.vectorize_cli",
                    image_path,
                    "--mode",
                    "image-trace",
                    "--jsx",
                    jsx_path,
                    "--output-ai",
                    "output.ai",
                    "--colors",
                    "16",
                    "--max-dimension",
                    "32",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0)
            self.assertTrue(os.path.exists(jsx_path))
            self.assertTrue(os.path.exists(prepared_path))
            self.assertIn("image-trace", result.stdout)
            with open(jsx_path, encoding="utf-8") as f:
                self.assertIn("placed.trace()", f.read())
        finally:
            os.unlink(image_path)
            if os.path.exists(jsx_path):
                os.unlink(jsx_path)
            if os.path.exists(prepared_path):
                os.unlink(prepared_path)


if __name__ == "__main__":
    unittest.main()
