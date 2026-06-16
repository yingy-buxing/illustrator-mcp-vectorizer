"""Command line entry point for bitmap vectorization."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .image_trace import ImageTraceOptions, generate_image_trace_jsx, prepare_image_trace_source
from .vectorizer import VectorizerOptions, generate_illustrator_jsx, vectorize_bitmap, vectorize_icon_silhouette
from .visual_layers import apply_visual_layer_plan


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert a bitmap to Illustrator JSX.")
    parser.add_argument("image_path", help="Source bitmap path.")
    parser.add_argument("--output-ai", help="Optional .ai path that the JSX will save in Illustrator.")
    parser.add_argument("--jsx", required=True, help="Path to write the generated JSX.")
    parser.add_argument("--colors", type=int, help="Fixed color count. Omit for automatic clustering.")
    parser.add_argument("--max-colors", type=int, default=12, help="Automatic color clustering upper bound.")
    parser.add_argument("--max-dimension", type=int, default=512, help="Trace at this maximum image dimension.")
    parser.add_argument("--min-area", type=int, default=16, help="Minimum connected region area in pixels.")
    parser.add_argument("--simplify", type=float, default=1.6, help="Contour simplification tolerance.")
    parser.add_argument("--smoothing", type=float, default=0.25, help="Bezier smoothing amount from 0 to 1.")
    parser.add_argument(
        "--mode",
        choices=["color", "icon", "image-trace"],
        default="color",
        help="Vectorization mode. image-trace uses Illustrator's native Image Trace after optional de-noising.",
    )
    parser.add_argument("--trace-path-fitting", type=float, default=2.0, help="Illustrator Image Trace path fitting.")
    parser.add_argument("--trace-corner-angle", type=int, default=20, help="Illustrator Image Trace corner angle.")
    parser.add_argument("--trace-noise", type=int, default=8, help="Illustrator Image Trace noise fidelity.")
    parser.add_argument("--trace-median-filter", type=int, default=3, help="Median filter size for image-trace preprocessing. Use 0 to disable.")
    parser.add_argument("--trace-ignore-white", action="store_true", help="Tell Illustrator Image Trace to ignore white areas.")
    parser.add_argument(
        "--layer-provider",
        choices=["auto", "openai", "local", "heuristic", "none"],
        default="auto",
        help="Layer planner. local uses llama.cpp VLM; auto uses OpenAI vision when OPENAI_API_KEY is set, otherwise heuristic.",
    )
    parser.add_argument("--vision-model", help="Optional OpenAI vision-capable model for layer planning.")
    parser.add_argument("--local-cli-path", help="Optional path to llama-mtmd-cli.exe.")
    parser.add_argument("--local-model-path", help="Optional path to local VLM .gguf model.")
    parser.add_argument("--local-mmproj-path", help="Optional path to local multimodal projector .gguf.")
    parser.add_argument("--local-timeout", type=int, default=300, help="Timeout in seconds for local VLM planning.")
    parser.add_argument(
        "--require-visual-model",
        action="store_true",
        help="Fail before writing JSX unless the visual model successfully assigns layers.",
    )
    args = parser.parse_args()

    if args.mode == "image-trace":
        trace_options = ImageTraceOptions(
            max_colors=args.colors or args.max_colors,
            max_dimension=args.max_dimension,
            median_filter_size=args.trace_median_filter,
            path_fitting=args.trace_path_fitting,
            corner_angle=args.trace_corner_angle,
            noise_fidelity=args.trace_noise,
            ignore_white=args.trace_ignore_white,
        )
        jsx_path = Path(args.jsx)
        prepared_path = jsx_path.with_name(f"{jsx_path.stem}_source.png")
        prepared_path, (width, height) = prepare_image_trace_source(args.image_path, prepared_path, trace_options)
        jsx = generate_image_trace_jsx(prepared_path, args.output_ai, width, height, trace_options)
        jsx_path.write_text(jsx, encoding="utf-8")
        print(
            json.dumps(
                {
                    "summary": {
                        "source_path": args.image_path,
                        "prepared_source_path": str(prepared_path),
                        "width": width,
                        "height": height,
                        "mode": "image-trace",
                        "max_colors": trace_options.max_colors,
                    },
                    "layer_plan": {
                        "provider": "illustrator-image-trace",
                        "model": None,
                        "applied": False,
                        "assigned_shapes": 0,
                        "reason": "native Illustrator tracing does not provide semantic layer assignments",
                    },
                    "jsx_path": str(jsx_path),
                },
                indent=2,
            )
        )
        return

    options = VectorizerOptions(
        colors=args.colors,
        max_colors=args.max_colors,
        max_dimension=args.max_dimension,
        min_area=args.min_area,
        simplify_tolerance=args.simplify,
        bezier_smoothing=args.smoothing,
    )
    if args.mode == "icon":
        document = vectorize_icon_silhouette(args.image_path, options)
    else:
        document = vectorize_bitmap(args.image_path, options)
    layer_provider = args.layer_provider
    if args.mode == "icon" and layer_provider == "auto":
        layer_provider = "none"
    layer_plan = apply_visual_layer_plan(
        document,
        args.image_path,
        provider=layer_provider,
        model=args.vision_model,
        local_cli_path=args.local_cli_path,
        local_model_path=args.local_model_path,
        local_mmproj_path=args.local_mmproj_path,
        local_timeout=args.local_timeout,
    )
    if args.require_visual_model and not layer_plan.applied:
        print(
            json.dumps(
                {
                    "summary": document.summary(),
                    "layer_plan": layer_plan.summary(),
                    "jsx_path": None,
                    "error": "Visual model layer planning is required but did not complete.",
                },
                indent=2,
            )
        )
        sys.exit(2)

    jsx = generate_illustrator_jsx(document, args.output_ai)
    jsx_path = Path(args.jsx)
    jsx_path.write_text(jsx, encoding="utf-8")
    print(json.dumps({"summary": document.summary(), "layer_plan": layer_plan.summary(), "jsx_path": str(jsx_path)}, indent=2))


if __name__ == "__main__":
    main()
