"""Illustrator Image Trace JSX generation helpers."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path

from PIL import Image, ImageFilter


@dataclass(slots=True)
class ImageTraceOptions:
    max_colors: int = 48
    max_dimension: int = 1200
    median_filter_size: int = 3
    path_fitting: float = 2.0
    corner_angle: int = 20
    noise_fidelity: int = 8
    ignore_white: bool = False


def prepare_image_trace_source(
    image_path: str | os.PathLike[str],
    prepared_path: str | os.PathLike[str],
    options: ImageTraceOptions | None = None,
) -> tuple[Path, tuple[int, int]]:
    """Create a stable, lightly de-noised trace source for Illustrator."""
    opts = options or ImageTraceOptions()
    source = Path(image_path)
    prepared = Path(prepared_path)
    prepared.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(source) as image:
        rgb = image.convert("RGB")
        if opts.max_dimension > 0:
            rgb.thumbnail((opts.max_dimension, opts.max_dimension), Image.Resampling.LANCZOS)
        if opts.median_filter_size >= 3:
            size = opts.median_filter_size if opts.median_filter_size % 2 == 1 else opts.median_filter_size + 1
            rgb = rgb.filter(ImageFilter.MedianFilter(size))
        rgb.save(prepared)
        return prepared, rgb.size


def generate_image_trace_jsx(
    prepared_image_path: str | os.PathLike[str],
    output_path: str | os.PathLike[str] | None,
    width: int,
    height: int,
    options: ImageTraceOptions | None = None,
) -> str:
    """Generate ExtendScript that runs Illustrator's native Image Trace."""
    opts = options or ImageTraceOptions()
    lines = [
        "#target illustrator",
        "(function () {",
        f"  var inFile = new File({_js_string(_jsx_path(prepared_image_path))});",
        "  if (!inFile.exists) throw new Error('Trace source not found: ' + inFile.fsName);",
        f"  var doc = app.documents.add(DocumentColorSpace.RGB, {_js_number(width)}, {_js_number(height)});",
        "  doc.rulerUnits = RulerUnits.Points;",
        "  var placed = doc.placedItems.add();",
        "  placed.file = inFile;",
        f"  placed.position = [0, {_js_number(height)}];",
        f"  placed.width = {_js_number(width)};",
        f"  placed.height = {_js_number(height)};",
        "  var traced = placed.trace();",
        "  var tracing = traced.tracing;",
        "  tracing.tracingOptions.tracingMode = TracingModeType.TRACINGMODECOLOR;",
        "  tracing.tracingOptions.palette = TracingColorType.TRACINGFULLCOLOR;",
        f"  tracing.tracingOptions.maxColors = {max(2, min(256, int(opts.max_colors)))};",
        f"  tracing.tracingOptions.pathFitting = {_js_number(opts.path_fitting)};",
        f"  tracing.tracingOptions.cornerAngle = {int(opts.corner_angle)};",
        f"  tracing.tracingOptions.noiseFidelity = {int(opts.noise_fidelity)};",
        f"  tracing.tracingOptions.ignoreWhite = {_js_bool(opts.ignore_white)};",
        "  app.redraw();",
        "  tracing.expandTracing();",
    ]
    if output_path:
        lines.extend(
            [
                f"  var outFile = new File({_js_string(_jsx_path(output_path))});",
                "  doc.saveAs(outFile);",
            ]
        )
    lines.extend(
        [
            "  return "
            + _js_string(
                "Image traced "
                f"{width}x{height}, maxColors={opts.max_colors}, "
                f"output={str(Path(output_path)) if output_path else ''}"
            )
            + ";",
            "}());",
        ]
    )
    return "\n".join(lines)


def _jsx_path(path: str | os.PathLike[str]) -> str:
    return str(Path(path)).replace("\\", "/")


def _js_bool(value: bool) -> str:
    return "true" if value else "false"


def _js_number(value: float | int) -> str:
    return str(round(float(value), 3))


def _js_string(value: str) -> str:
    return json.dumps(value)
