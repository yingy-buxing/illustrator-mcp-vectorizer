"""Visual-model layer planning for vectorized bitmap shapes."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import mimetypes
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Protocol

import httpx
from PIL import Image

try:
    from .vectorizer import VectorDocument, VectorShape, rgb_to_hex
except ImportError:
    from vectorizer import VectorDocument, VectorShape, rgb_to_hex


DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_LLAMA_DIR = Path(r"D:\llama-b9395-bin-win-cuda-13.3-x64")
DEFAULT_LOCAL_CLI = DEFAULT_LLAMA_DIR / "llama-mtmd-cli.exe"
DEFAULT_LOCAL_MODEL = DEFAULT_LLAMA_DIR / "models" / "Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-IQ2_M.gguf"
DEFAULT_LOCAL_MMPROJ = DEFAULT_LLAMA_DIR / "models" / "mmproj-Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-f16.gguf"
DEFAULT_LOCAL_IMAGE_MAX_DIMENSION = 512


@dataclass(slots=True)
class LayerPlanResult:
    provider: str
    model: str | None
    applied: bool
    layers: dict[int, str]
    reason: str | None = None
    raw_response: str | None = None

    def summary(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "applied": self.applied,
            "assigned_shapes": len(self.layers),
            "reason": self.reason,
        }


class ResponsesClient(Protocol):
    def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: int) -> httpx.Response:
        ...


def apply_visual_layer_plan(
    document: VectorDocument,
    image_path: str | os.PathLike[str] | None = None,
    provider: str = "auto",
    model: str | None = None,
    api_key: str | None = None,
    client: ResponsesClient | None = None,
    local_cli_path: str | os.PathLike[str] | None = None,
    local_model_path: str | os.PathLike[str] | None = None,
    local_mmproj_path: str | os.PathLike[str] | None = None,
    local_timeout: int = 300,
) -> LayerPlanResult:
    """Use a visual model to assign layer names, falling back to existing names."""
    provider = (provider or "auto").lower()
    if provider in {"heuristic", "none", "off"}:
        return LayerPlanResult(provider="heuristic", model=None, applied=False, layers={}, reason="visual model disabled")
    if provider in {"local", "llama", "llama.cpp"}:
        return _apply_local_llama_layer_plan(
            document=document,
            image_path=image_path,
            cli_path=local_cli_path,
            model_path=local_model_path,
            mmproj_path=local_mmproj_path,
            timeout=local_timeout,
        )

    api_key = _resolve_api_key(api_key)
    if provider in {"auto", "openai"} and not api_key:
        return LayerPlanResult(provider="heuristic", model=None, applied=False, layers={}, reason="OPENAI_API_KEY is not set")
    if provider not in {"auto", "openai"}:
        return LayerPlanResult(provider=provider, model=model, applied=False, layers={}, reason=f"unsupported provider: {provider}")

    source_path = Path(image_path or document.source_path)
    if not source_path.exists():
        return LayerPlanResult(provider="openai", model=model or DEFAULT_OPENAI_MODEL, applied=False, layers={}, reason="source image not found")

    try:
        result = _call_openai_layer_planner(
            document=document,
            image_path=source_path,
            model=model or os.environ.get("OPENAI_VISION_MODEL") or DEFAULT_OPENAI_MODEL,
            api_key=api_key,
            client=client,
        )
    except httpx.HTTPStatusError as exc:
        return LayerPlanResult(
            provider="openai",
            model=model or os.environ.get("OPENAI_VISION_MODEL") or DEFAULT_OPENAI_MODEL,
            applied=False,
            layers={},
            reason=_format_http_status_error(exc),
        )
    except Exception as exc:
        return LayerPlanResult(
            provider="openai",
            model=model or os.environ.get("OPENAI_VISION_MODEL") or DEFAULT_OPENAI_MODEL,
            applied=False,
            layers={},
            reason=str(exc),
        )

    applied_layers = _parse_layer_plan(result.raw_response or "", len(document.shapes))
    if not applied_layers:
        return LayerPlanResult(
            provider="openai",
            model=result.model,
            applied=False,
            layers={},
            reason="model did not return usable layer assignments",
            raw_response=result.raw_response,
        )

    for index, layer_name in applied_layers.items():
        document.shapes[index].layer_name = _clean_layer_name(layer_name)

    return LayerPlanResult(
        provider="openai",
        model=result.model,
        applied=True,
        layers=applied_layers,
        raw_response=result.raw_response,
    )


def _apply_local_llama_layer_plan(
    document: VectorDocument,
    image_path: str | os.PathLike[str] | None,
    cli_path: str | os.PathLike[str] | None,
    model_path: str | os.PathLike[str] | None,
    mmproj_path: str | os.PathLike[str] | None,
    timeout: int,
) -> LayerPlanResult:
    source_path = Path(image_path or document.source_path)
    cli = Path(cli_path or os.environ.get("LLAMA_MTMD_CLI") or DEFAULT_LOCAL_CLI)
    model_file = Path(model_path or os.environ.get("LLAMA_MODEL_PATH") or DEFAULT_LOCAL_MODEL)
    mmproj_file = Path(mmproj_path or os.environ.get("LLAMA_MMPROJ_PATH") or DEFAULT_LOCAL_MMPROJ)

    missing = [str(path) for path in (source_path, cli, model_file, mmproj_file) if not path.exists()]
    if missing:
        return LayerPlanResult(
            provider="local",
            model=str(model_file),
            applied=False,
            layers={},
            reason="missing local VLM file(s): " + ", ".join(missing),
        )

    try:
        raw_text = _call_local_llama_layer_planner(document, source_path, cli, model_file, mmproj_file, timeout)
    except Exception as exc:
        return LayerPlanResult(provider="local", model=str(model_file), applied=False, layers={}, reason=str(exc))

    applied_layers = _parse_layer_plan(_extract_json_object(raw_text), len(document.shapes))
    if not applied_layers:
        return LayerPlanResult(
            provider="local",
            model=str(model_file),
            applied=False,
            layers={},
            reason="local model did not return usable layer assignments",
            raw_response=raw_text,
        )

    for index, layer_name in applied_layers.items():
        document.shapes[index].layer_name = _clean_layer_name(layer_name)

    return LayerPlanResult(
        provider="local",
        model=str(model_file),
        applied=True,
        layers=applied_layers,
        raw_response=raw_text,
    )


def _call_local_llama_layer_planner(
    document: VectorDocument,
    image_path: Path,
    cli_path: Path,
    model_path: Path,
    mmproj_path: Path,
    timeout: int,
) -> str:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "layers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string"},
                        "shape_indices": {"type": "array", "items": {"type": "integer"}},
                    },
                    "required": ["name", "shape_indices"],
                },
            },
            "notes": {"type": "string"},
        },
        "required": ["layers", "notes"],
    }
    prompt = _local_layer_prompt(document)

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as prompt_file:
        prompt_file.write(prompt)
        prompt_path = Path(prompt_file.name)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as schema_file:
        json.dump(schema, schema_file)
        schema_path = Path(schema_file.name)
    prepared_image_path: Path | None = None

    try:
        prepared_image_path = _prepare_local_vlm_image(image_path, DEFAULT_LOCAL_IMAGE_MAX_DIMENSION)
        result = subprocess.run(
            [
                str(cli_path),
                "-m",
                str(model_path),
                "--mmproj",
                str(mmproj_path),
                "--image",
                str(prepared_image_path),
                "-f",
                str(prompt_path),
                "--json-schema-file",
                str(schema_path),
                "-n",
                "256",
                "--temp",
                "0",
                "--ctx-size",
                "8192",
                "--image-max-tokens",
                "512",
                "--verbosity",
                "1",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cli_path.parent),
        )
    finally:
        prompt_path.unlink(missing_ok=True)
        schema_path.unlink(missing_ok=True)
        if prepared_image_path and prepared_image_path != image_path:
            prepared_image_path.unlink(missing_ok=True)

    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    if result.returncode != 0:
        raise RuntimeError(f"local VLM exited with {result.returncode}: {output}")
    return output


def _local_layer_prompt(document: VectorDocument) -> str:
    descriptors = [_shape_descriptor(index, shape, document.width, document.height) for index, shape in enumerate(document.shapes)]
    compact_descriptors = json.dumps(descriptors, separators=(",", ":"))
    return (
        "Return only JSON. Plan Illustrator layers for this vectorized travel app icon. "
        "Use shape indices from descriptors. Schema: "
        '{"layers":[{"name":"01 Background","shape_indices":[0]},'
        '{"name":"02 Main icon","shape_indices":[1]}],"notes":"short"}. '
        "Use layer names like 01 Background, 02 Main icon, 03 Decorative marks, 04 Highlights. "
        f"Canvas={document.width}x{document.height}. Shapes={compact_descriptors}"
    )


def _prepare_local_vlm_image(image_path: Path, max_dimension: int) -> Path:
    with Image.open(image_path) as image:
        image = image.convert("RGB")
        if max(image.size) <= max_dimension:
            return image_path
        image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_image:
            temp_path = Path(temp_image.name)
        image.save(temp_path)
        return temp_path


def _call_openai_layer_planner(
    document: VectorDocument,
    image_path: Path,
    model: str,
    api_key: str,
    client: ResponsesClient | None = None,
) -> LayerPlanResult:
    payload = _openai_payload(document, image_path, model)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if client is None:
        with httpx.Client() as http_client:
            response = http_client.post(OPENAI_RESPONSES_URL, headers=headers, json=payload, timeout=60)
    else:
        response = client.post(OPENAI_RESPONSES_URL, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    text = _extract_response_text(response.json())
    return LayerPlanResult(provider="openai", model=model, applied=False, layers={}, raw_response=text)


def _format_http_status_error(exc: httpx.HTTPStatusError) -> str:
    status = exc.response.status_code
    try:
        payload = exc.response.json()
    except ValueError:
        return f"OpenAI API returned HTTP {status}"

    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    message = str(error.get("message") or f"OpenAI API returned HTTP {status}")
    code = error.get("code")
    kind = error.get("type")
    parts = [f"OpenAI API returned HTTP {status}: {message}"]
    if code:
        parts.append(f"code={code}")
    if kind:
        parts.append(f"type={kind}")
    return " | ".join(parts)


def _resolve_api_key(api_key: str | None) -> str | None:
    if api_key:
        return api_key
    local_key = _read_env_local_key(Path.cwd())
    if local_key:
        return local_key
    return os.environ.get("OPENAI_API_KEY")


def _read_env_local_key(start: Path) -> str | None:
    for directory in [start, *start.parents]:
        env_path = directory / ".env.local"
        if not env_path.exists() or not env_path.is_file():
            continue
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            name, value = stripped.split("=", 1)
            if name.strip() == "OPENAI_API_KEY":
                return value.strip().strip('"').strip("'") or None
    return None


def _openai_payload(document: VectorDocument, image_path: Path, model: str) -> dict[str, Any]:
    return {
        "model": model,
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": _layer_prompt(document),
                    },
                    {
                        "type": "input_image",
                        "image_url": _image_data_url(image_path),
                    },
                ],
            }
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "illustrator_layer_plan",
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "layers": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "name": {"type": "string"},
                                    "shape_indices": {
                                        "type": "array",
                                        "items": {"type": "integer"},
                                    },
                                },
                                "required": ["name", "shape_indices"],
                            },
                        },
                        "notes": {"type": "string"},
                    },
                    "required": ["layers", "notes"],
                },
            }
        },
    }


def _layer_prompt(document: VectorDocument) -> str:
    descriptors = [_shape_descriptor(index, shape, document.width, document.height) for index, shape in enumerate(document.shapes)]
    return (
        "You are planning Adobe Illustrator layers for an automatic bitmap-to-vector conversion. "
        "Use the source image and the extracted shape descriptors to group shapes into a clean Illustrator layer structure. "
        "Prefer concise layer names with numeric prefixes for stacking order, such as '01 Background', '02 Main subject', "
        "'03 Details', '04 Highlights'. Assign every useful shape index exactly once. "
        "Return only JSON matching the provided schema.\n\n"
        f"Canvas: {document.width} x {document.height}\n"
        f"Shape descriptors:\n{json.dumps(descriptors, indent=2)}"
    )


def _shape_descriptor(index: int, shape: VectorShape, width: int, height: int) -> dict[str, Any]:
    min_x, min_y, max_x, max_y = shape.bbox
    return {
        "index": index,
        "color": rgb_to_hex(shape.color),
        "area_ratio": round(shape.area / max(1, width * height), 4),
        "bbox": {
            "x": min_x,
            "y": min_y,
            "width": max_x - min_x,
            "height": max_y - min_y,
        },
        "heuristic_layer": shape.layer_name,
    }


def _image_data_url(image_path: Path) -> str:
    mime_type = mimetypes.guess_type(str(image_path))[0] or "image/png"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _extract_response_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]

    chunks: list[str] = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    return "\n".join(chunks).strip()


def _parse_layer_plan(raw_text: str, shape_count: int) -> dict[int, str]:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return {}

    assignments: dict[int, str] = {}
    for layer in payload.get("layers", []):
        name = _clean_layer_name(str(layer.get("name", "")))
        if not name:
            continue
        shape_indices = layer.get("shape_indices", layer.get("shapes", []))
        for index in shape_indices:
            if isinstance(index, int) and 0 <= index < shape_count and index not in assignments:
                assignments[index] = name
    return assignments


def _extract_json_object(raw_text: str) -> str:
    stripped = raw_text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return stripped
    return stripped[start:end + 1]


def _clean_layer_name(name: str) -> str:
    cleaned = " ".join(name.replace("/", " ").replace("\\", " ").split())
    return cleaned[:80]
