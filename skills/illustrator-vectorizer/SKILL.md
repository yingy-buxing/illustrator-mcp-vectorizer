---
name: illustrator-vectorizer
description: Convert bitmap artwork such as PNG/JPEG icons, logos, app icons, flat illustrations, and screenshots into editable Adobe Illustrator .ai files through the local illustrator-mcp project. Use when Codex needs to choose a vectorization mode, generate reproducible JSX, run Adobe Illustrator automation, inspect exported previews, tune tracing parameters, or hand back .ai/.jsx outputs.
---

# Illustrator Vectorizer

Use this skill to turn bitmap artwork into editable Illustrator files with the local `illustrator-mcp` project.

## Workflow

1. Confirm the source image path exists and inspect its size/mode with Pillow.
2. Choose a mode:
   - `image_trace` for complex illustrations, JPEGs, noisy artwork, or when visual smoothness matters most.
   - `icon` for app-style icons with one rounded colored background and a light foreground glyph.
   - `color` for clean flat artwork where deterministic local paths and layer summaries are preferred.
3. Generate a `.jsx` script and `.ai` output path.
4. Execute the JSX through `illustrator.server.run_illustrator_script` when Illustrator is available and the user wants an `.ai`.
5. Export a PNG preview from Illustrator and inspect it before finalizing.
6. If the preview has white cracks or noisy speckles:
   - Prefer `image_trace` for JPEGs and complex art.
   - Increase fidelity by lowering `min_area` for `color`.
   - Increase preprocessing with `trace_median_filter 3` for `image_trace`.
7. Return the `.ai`, `.jsx`, and preview paths, plus the mode and important parameter choices.

## Commands

Run deterministic color vectorization:

```powershell
python -m illustrator.vectorize_cli "E:\input.png" `
  --mode color `
  --jsx "E:\output.jsx" `
  --output-ai "E:\output.ai" `
  --colors 32 `
  --max-dimension 1200 `
  --min-area 40 `
  --layer-provider none
```

Run app icon vectorization:

```powershell
python -m illustrator.vectorize_cli "E:\icon.png" `
  --mode icon `
  --jsx "E:\icon.jsx" `
  --output-ai "E:\icon.ai" `
  --max-dimension 1024 `
  --min-area 80 `
  --layer-provider none
```

Run Illustrator native Image Trace:

```powershell
python -m illustrator.vectorize_cli "E:\illustration.jpg" `
  --mode image-trace `
  --jsx "E:\illustration_trace.jsx" `
  --output-ai "E:\illustration_trace.ai" `
  --colors 48 `
  --max-dimension 1200 `
  --trace-median-filter 3
```

Execute a generated JSX:

```powershell
@'
from pathlib import Path
from illustrator.server import run_illustrator_script
jsx = Path(r"E:\output.jsx").read_text(encoding="utf-8")
print(run_illustrator_script(jsx)[0].text)
'@ | python -
```

Export a preview from the active Illustrator document:

```powershell
@'
from illustrator.server import run_illustrator_script
code = r'''
#target illustrator
(function () {
  var outFile = new File("E:/output_preview.png");
  var opts = new ExportOptionsPNG24();
  opts.antiAliasing = true;
  opts.transparency = false;
  opts.artBoardClipping = true;
  app.activeDocument.exportFile(outFile, ExportType.PNG24, opts);
  return "exported " + outFile.fsName;
}());
'''
print(run_illustrator_script(code)[0].text)
'@ | python -
```

## Mode Notes

- `image_trace` is the best default for user-facing conversion results from JPEG/complex illustrations because Illustrator merges and smooths edges better than color-component tracing.
- `color` gives clearer shape counts and reproducible local geometry but can expose JPEG artifacts as many tiny paths.
- `icon` deliberately ignores subtle gradients and creates one background plus foreground silhouette layers; do not use it for general illustrations.
- Keep source paths ASCII when PowerShell quoting mangles non-ASCII paths; copy the source to a temporary ASCII path and copy outputs back to the user's preferred filename.

## References

Read `references/parameters.md` when tuning quality, path count, or mode selection.
