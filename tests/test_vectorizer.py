import os
import tempfile
import unittest

from PIL import Image, ImageDraw

from illustrator.vectorizer import (
    VectorizerOptions,
    generate_illustrator_jsx,
    vectorize_bitmap,
    vectorize_bitmap_to_jsx,
    vectorize_icon_silhouette,
)


class VectorizerTests(unittest.TestCase):
    def _make_test_image(self) -> str:
        handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        handle.close()
        image = Image.new("RGB", (48, 32), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((4, 4, 22, 26), fill=(220, 20, 20))
        draw.ellipse((25, 8, 43, 26), fill=(20, 80, 220))
        image.save(handle.name)
        return handle.name

    def test_vectorize_bitmap_extracts_shapes_and_layers(self):
        image_path = self._make_test_image()
        try:
            document = vectorize_bitmap(
                image_path,
                VectorizerOptions(colors=3, min_area=20, simplify_tolerance=1.0),
            )
        finally:
            os.unlink(image_path)

        self.assertEqual(document.width, 48)
        self.assertEqual(document.height, 32)
        self.assertGreaterEqual(len(document.palette), 3)
        self.assertGreaterEqual(len(document.shapes), 2)
        self.assertTrue(all(shape.beziers for shape in document.shapes))
        self.assertTrue(any(shape.layer_name for shape in document.shapes))

    def test_generate_illustrator_jsx_includes_save_path_and_paths(self):
        image_path = self._make_test_image()
        try:
            document = vectorize_bitmap(
                image_path,
                VectorizerOptions(colors=3, min_area=20, simplify_tolerance=1.0),
            )
            jsx = generate_illustrator_jsx(document, r"C:\tmp\vectorized.ai")
        finally:
            os.unlink(image_path)

        self.assertIn("#target illustrator", jsx)
        self.assertIn("doc.saveAs(outFile)", jsx)
        self.assertIn("pathPoints.add", jsx)
        self.assertIn("PointType.SMOOTH", jsx)

    def test_vectorize_bitmap_to_jsx_returns_summary(self):
        image_path = self._make_test_image()
        try:
            document, jsx = vectorize_bitmap_to_jsx(
                image_path,
                "output.ai",
                VectorizerOptions(colors=3, min_area=20),
            )
        finally:
            os.unlink(image_path)

        summary = document.summary()
        self.assertEqual(summary["shape_count"], len(document.shapes))
        self.assertIn("palette", summary)
        self.assertIn("output.ai", jsx)

    def test_vectorize_icon_silhouette_keeps_gradient_background_together(self):
        handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        handle.close()
        image = Image.new("RGB", (96, 96), "white")
        draw = ImageDraw.Draw(image)
        for y in range(8, 88):
            color = (36, 205 - y // 8, 205 - y // 10)
            draw.line((8, y, 88, y), fill=color)
        draw.rounded_rectangle((8, 8, 88, 88), radius=18, outline=(36, 198, 200), width=3)
        draw.line((28, 56, 70, 30), fill=(248, 255, 255), width=8)
        draw.polygon([(24, 50), (46, 50), (38, 60)], fill=(248, 255, 255))
        draw.polygon([(50, 40), (72, 22), (62, 46)], fill=(248, 255, 255))
        image.save(handle.name)

        try:
            document = vectorize_icon_silhouette(
                handle.name,
                VectorizerOptions(max_dimension=96, min_area=20, simplify_tolerance=1.6),
            )
        finally:
            os.unlink(handle.name)

        layers = document.summary()["layers"]
        self.assertEqual(layers.get("01 Background"), 1)
        self.assertGreaterEqual(layers.get("02 Main icon", 0), 1)
        self.assertLessEqual(document.summary()["shape_count"], 6)


if __name__ == "__main__":
    unittest.main()
