import os
from pathlib import Path
import tempfile
import unittest

import httpx
from PIL import Image, ImageDraw

from illustrator.vectorizer import VectorizerOptions, vectorize_bitmap
from illustrator.visual_layers import (
    _extract_json_object,
    _format_http_status_error,
    _resolve_api_key,
    apply_visual_layer_plan,
)


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.last_request = None

    def post(self, url, *, headers, json, timeout):
        self.last_request = {
            "url": url,
            "headers": headers,
            "json": json,
            "timeout": timeout,
        }
        return FakeResponse(self.payload)


class VisualLayerTests(unittest.TestCase):
    def _make_test_image(self) -> str:
        handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        handle.close()
        image = Image.new("RGB", (48, 32), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((4, 4, 22, 26), fill=(220, 20, 20))
        draw.ellipse((25, 8, 43, 26), fill=(20, 80, 220))
        image.save(handle.name)
        return handle.name

    def test_auto_without_key_falls_back_to_heuristic(self):
        image_path = self._make_test_image()
        old_cwd = os.getcwd()
        old_key = os.environ.pop("OPENAI_API_KEY", None)
        work = tempfile.TemporaryDirectory()
        try:
            os.chdir(work.name)
            document = vectorize_bitmap(image_path, VectorizerOptions(colors=3, min_area=20))
            result = apply_visual_layer_plan(document, image_path, provider="auto")
        finally:
            os.chdir(old_cwd)
            if old_key:
                os.environ["OPENAI_API_KEY"] = old_key
            work.cleanup()
            os.unlink(image_path)

        self.assertFalse(result.applied)
        self.assertEqual(result.provider, "heuristic")
        self.assertIn("OPENAI_API_KEY", result.reason)

    def test_openai_response_assigns_layer_names(self):
        image_path = self._make_test_image()
        payload = {
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": (
                                '{"layers":['
                                '{"name":"01 Background","shape_indices":[0]},'
                                '{"name":"02 Main objects","shape_indices":[1,2]}'
                                '],"notes":"grouped by visual role"}'
                            ),
                        }
                    ]
                }
            ]
        }
        client = FakeClient(payload)

        try:
            document = vectorize_bitmap(image_path, VectorizerOptions(colors=3, min_area=20))
            result = apply_visual_layer_plan(
                document,
                image_path,
                provider="openai",
                model="test-vision-model",
                api_key="test-key",
                client=client,
            )
        finally:
            os.unlink(image_path)

        self.assertTrue(result.applied)
        self.assertEqual(result.model, "test-vision-model")
        self.assertIn("input_image", str(client.last_request["json"]))
        self.assertEqual(document.shapes[0].layer_name, "01 Background")
        self.assertEqual(document.shapes[1].layer_name, "02 Main objects")

    def test_env_local_takes_priority_over_process_env(self):
        old_cwd = os.getcwd()
        old_key = os.environ.get("OPENAI_API_KEY")
        work = tempfile.TemporaryDirectory()
        try:
            os.chdir(work.name)
            Path(".env.local").write_text("OPENAI_API_KEY=local-test-key\n", encoding="utf-8")
            os.environ["OPENAI_API_KEY"] = "process-test-key"
            self.assertEqual(_resolve_api_key(None), "local-test-key")
        finally:
            os.chdir(old_cwd)
            if old_key is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = old_key
            work.cleanup()

    def test_http_status_error_format_includes_safe_details(self):
        request = httpx.Request("POST", "https://api.openai.com/v1/responses")
        response = httpx.Response(
            429,
            json={
                "error": {
                    "message": "quota reached",
                    "code": "insufficient_quota",
                    "type": "rate_limit_error",
                }
            },
            request=request,
        )
        reason = _format_http_status_error(httpx.HTTPStatusError("boom", request=request, response=response))
        self.assertIn("HTTP 429", reason)
        self.assertIn("insufficient_quota", reason)
        self.assertIn("rate_limit_error", reason)

    def test_extract_json_object_from_local_cli_output(self):
        raw = 'log line\n{"layers":[{"name":"01 Background","shape_indices":[0]}],"notes":"ok"}\n'
        extracted = _extract_json_object(raw)
        self.assertTrue(extracted.startswith("{"))
        self.assertTrue(extracted.endswith("}"))

    def test_local_response_assigns_layer_names(self):
        image_path = self._make_test_image()
        try:
            document = vectorize_bitmap(image_path, VectorizerOptions(colors=3, min_area=20))
            from illustrator import visual_layers

            original = visual_layers._call_local_llama_layer_planner
            visual_layers._call_local_llama_layer_planner = lambda *args, **kwargs: (
                '{"layers":['
                '{"name":"01 Background","shape_indices":[0]},'
                '{"name":"02 Local objects","shape_indices":[1,2]}'
                '],"notes":"local"}'
            )
            try:
                result = apply_visual_layer_plan(
                    document,
                    image_path,
                    provider="local",
                    local_cli_path=image_path,
                    local_model_path=image_path,
                    local_mmproj_path=image_path,
                )
            finally:
                visual_layers._call_local_llama_layer_planner = original
        finally:
            os.unlink(image_path)

        self.assertTrue(result.applied)
        self.assertEqual(result.provider, "local")
        self.assertEqual(document.shapes[1].layer_name, "02 Local objects")


if __name__ == "__main__":
    unittest.main()
