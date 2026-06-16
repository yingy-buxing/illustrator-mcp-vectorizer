import asyncio
import json
import os
import tempfile
import unittest

from PIL import Image, ImageDraw

from illustrator.server import _default_ai_output_path, handle_call_tool, handle_list_tools


class ServerVectorizeTests(unittest.TestCase):
    def _make_test_image(self) -> str:
        handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        handle.close()
        image = Image.new("RGB", (40, 30), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((4, 4, 20, 25), fill=(200, 30, 30))
        draw.ellipse((22, 6, 36, 24), fill=(20, 80, 200))
        image.save(handle.name)
        return handle.name

    def test_vectorize_bitmap_tool_is_registered(self):
        async def run():
            tools = await handle_list_tools()
            return [tool.name for tool in tools]

        names = asyncio.run(run())
        self.assertIn("vectorize_bitmap", names)

    def test_default_ai_output_path_uses_input_stem(self):
        self.assertEqual(
            _default_ai_output_path(r"C:\tmp\source.png"),
            r"C:\tmp\source_vectorized.ai",
        )

    def test_vectorize_bitmap_tool_writes_jsx_without_execution(self):
        image_path = self._make_test_image()
        jsx_handle = tempfile.NamedTemporaryFile(suffix=".jsx", delete=False)
        jsx_handle.close()
        os.unlink(jsx_handle.name)

        async def run():
            return await handle_call_tool(
                "vectorize_bitmap",
                {
                    "image_path": image_path,
                    "output_path": "sample.ai",
                    "jsx_path": jsx_handle.name,
                    "colors": 3,
                    "min_area": 10,
                    "layer_provider": "heuristic",
                    "execute": False,
                },
            )

        try:
            result = asyncio.run(run())
            payload = json.loads(result[0].text)
            self.assertFalse(payload["executed"])
            self.assertTrue(os.path.exists(jsx_handle.name))
            self.assertGreater(os.path.getsize(jsx_handle.name), 0)
            self.assertGreaterEqual(payload["summary"]["shape_count"], 2)
        finally:
            os.unlink(image_path)
            if os.path.exists(jsx_handle.name):
                os.unlink(jsx_handle.name)

    def test_vectorize_bitmap_tool_writes_image_trace_jsx_without_execution(self):
        image_path = self._make_test_image()
        jsx_handle = tempfile.NamedTemporaryFile(suffix=".jsx", delete=False)
        jsx_handle.close()
        os.unlink(jsx_handle.name)
        prepared_path = os.path.splitext(jsx_handle.name)[0] + "_source.png"

        async def run():
            return await handle_call_tool(
                "vectorize_bitmap",
                {
                    "image_path": image_path,
                    "output_path": "sample.ai",
                    "jsx_path": jsx_handle.name,
                    "vector_mode": "image_trace",
                    "colors": 16,
                    "max_dimension": 32,
                    "execute": False,
                },
            )

        try:
            result = asyncio.run(run())
            payload = json.loads(result[0].text)
            self.assertFalse(payload["executed"])
            self.assertEqual(payload["summary"]["mode"], "image_trace")
            self.assertTrue(os.path.exists(jsx_handle.name))
            self.assertTrue(os.path.exists(prepared_path))
            with open(jsx_handle.name, encoding="utf-8") as f:
                self.assertIn("placed.trace()", f.read())
        finally:
            os.unlink(image_path)
            if os.path.exists(jsx_handle.name):
                os.unlink(jsx_handle.name)
            if os.path.exists(prepared_path):
                os.unlink(prepared_path)

    def test_require_visual_model_stops_before_jsx(self):
        image_path = self._make_test_image()
        jsx_handle = tempfile.NamedTemporaryFile(suffix=".jsx", delete=False)
        jsx_handle.close()
        os.unlink(jsx_handle.name)

        async def run():
            return await handle_call_tool(
                "vectorize_bitmap",
                {
                    "image_path": image_path,
                    "jsx_path": jsx_handle.name,
                    "colors": 3,
                    "min_area": 10,
                    "layer_provider": "heuristic",
                    "require_visual_model": True,
                    "execute": False,
                },
            )

        try:
            result = asyncio.run(run())
            payload = json.loads(result[0].text)
            self.assertIn("error", payload)
            self.assertFalse(payload["executed"])
            self.assertFalse(os.path.exists(jsx_handle.name))
        finally:
            os.unlink(image_path)
            if os.path.exists(jsx_handle.name):
                os.unlink(jsx_handle.name)


if __name__ == "__main__":
    unittest.main()
