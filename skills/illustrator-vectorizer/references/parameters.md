# Vectorization Parameters

## Mode Selection

- Use `image_trace` / CLI `image-trace` for complex flat illustrations, JPEGs, and deliverables where visual cleanliness beats semantic layer control.
- Use `icon` for app icons with a single colored rounded-square background and a white/light glyph. It keeps the background together and extracts foreground silhouettes.
- Use `color` for clean PNG/SVG-like raster art where deterministic local tracing is useful.

## Good Starting Points

Complex JPEG illustration:

```text
mode=image-trace
colors=48
max_dimension=1200
trace_median_filter=3
trace_path_fitting=2
trace_corner_angle=20
trace_noise=8
```

Clean flat PNG:

```text
mode=color
colors=24-48
max_dimension=1000-1400
min_area=20-80
simplify=1.2-1.8
smoothing=0.12-0.2
```

App icon:

```text
mode=icon
max_dimension=1024
min_area=80
simplify=2.2-2.8
smoothing=0.18-0.25
layer_provider=none
```

## Troubleshooting

- White cracks between regions: lower `min_area`, or switch to `image_trace`.
- Too many tiny paths: increase `min_area`, reduce `colors`, or use `trace_median_filter 3`.
- Important small details disappear: lower `min_area` or increase `colors`.
- Gradient backgrounds split into fragments: use `icon` for app icons or `image_trace` for illustrations.
- Illustrator is slow: reduce `max_dimension`, increase `min_area`, or use `image_trace` with fewer colors.
- Need reproducibility without Illustrator: use `color` or `icon` to generate `.jsx`; final `.ai` still requires Illustrator execution.

## QA Checklist

Before final response:

1. Confirm `.ai` exists and has nonzero size.
2. Confirm `.jsx` exists when requested or useful for reproducibility.
3. Export a PNG preview from Illustrator.
4. Visually inspect the preview for missing objects, white cracks, excessive speckles, and wrong mode choice.
5. Mention the chosen mode and why.
