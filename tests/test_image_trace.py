import os
import tempfile
import unittest

from PIL import Image

from illustrator.image_trace import ImageTraceOptions, generate_image_trace_jsx, prepare_image_trace_source


class ImageTraceTests(unittest.TestCase):
    def test_prepare_image_trace_source_resizes_and_writes_png(self):
        source = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        source.close()
        prepared = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        prepared.close()
        os.unlink(prepared.name)

        image = Image.new("RGB", (80, 40), (120, 200, 190))
        image.save(source.name)

        try:
            prepared_path, size = prepare_image_trace_source(
                source.name,
                prepared.name,
                ImageTraceOptions(max_dimension=40, median_filter_size=0),
            )
            self.assertTrue(os.path.exists(prepared_path))
            self.assertEqual(size, (40, 20))
        finally:
            os.unlink(source.name)
            if os.path.exists(prepared.name):
                os.unlink(prepared.name)

    def test_generate_image_trace_jsx_contains_native_trace_options(self):
        jsx = generate_image_trace_jsx(
            r"C:\tmp\trace-source.png",
            r"C:\tmp\out.ai",
            100,
            80,
            ImageTraceOptions(max_colors=24, ignore_white=True),
        )
        self.assertIn("placed.trace()", jsx)
        self.assertIn("TRACINGMODECOLOR", jsx)
        self.assertIn("maxColors = 24", jsx)
        self.assertIn("ignoreWhite = true", jsx)
        self.assertIn("doc.saveAs(outFile)", jsx)


if __name__ == "__main__":
    unittest.main()
