# Illustrator MCP Vectorizer

Automate Adobe Illustrator from AI agents and convert bitmap artwork into editable `.ai` files.

This project started from `krVatsal/illustrator-mcp` and adds a practical bitmap-to-vector pipeline:

- Run ExtendScript in Adobe Illustrator through an MCP server.
- Capture the Illustrator window for visual QA.
- Convert PNG/JPEG artwork into Illustrator paths.
- Choose between deterministic local vectorization, app-icon silhouette tracing, and native Illustrator Image Trace.
- Save repeatable `.jsx` scripts and final `.ai` files from the command line or MCP clients.

## Demo

### App icon mode

Use this mode for simple app icons where subtle gradients should not split one visual layer into many fragments.

![Vectorized travel icon](docs/assets/travel-icon-vectorized.png)

### Illustrator Image Trace mode

Use this mode for complex flat illustrations, JPEG inputs, and artwork where Illustrator's native smoothing gives better visual results.

![Image traced lighthouse island](docs/assets/lighthouse-island-image-trace.png)

## When to use each mode

| Mode | Best for | Tradeoff |
| --- | --- | --- |
| `color` | Flat logos, icons, posters, and controlled source art | Fully local and deterministic, but JPEG noise can create extra paths |
| `icon` | App-style icons with one rounded background and light foreground glyphs | Very clean layers for that specific icon shape family |
| `image-trace` / `image_trace` | Complex illustrations and noisy JPEGs | Requires Illustrator execution, but usually gives the cleanest result |

## Requirements

- Python 3.12+
- Adobe Illustrator installed
- Windows: `pywin32` is installed from dependencies
- macOS: grant Automation permissions when prompted

Optional:

- `OPENAI_API_KEY` for OpenAI vision-based layer naming
- A local llama.cpp multimodal model for offline layer naming

## Install

```bash
git clone https://github.com/yingy-buxing/illustrator-mcp-vectorizer.git
cd illustrator-mcp-vectorizer
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

On macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## CLI usage

Generate a reusable JSX file and an output path for Illustrator to save:

```bash
python -m illustrator.vectorize_cli input.png ^
  --mode color ^
  --jsx output.jsx ^
  --output-ai output.ai ^
  --colors 32 ^
  --max-dimension 1200 ^
  --min-area 40
```

For app icons with a gradient background and light foreground glyph:

```bash
python -m illustrator.vectorize_cli icon.png ^
  --mode icon ^
  --jsx icon.jsx ^
  --output-ai icon.ai ^
  --max-dimension 1024 ^
  --min-area 80
```

For complex JPEG illustrations, use native Illustrator Image Trace:

```bash
python -m illustrator.vectorize_cli illustration.jpg ^
  --mode image-trace ^
  --jsx illustration-trace.jsx ^
  --output-ai illustration-trace.ai ^
  --colors 48 ^
  --max-dimension 1200 ^
  --trace-median-filter 3
```

Run the generated JSX inside Illustrator with the MCP `run` tool, or use the MCP tool below with `execute: true`.

## MCP server

Start the server:

```bash
python -m illustrator
```

Example client configuration:

```json
{
  "mcpServers": {
    "illustrator": {
      "command": "C:\\path\\to\\repo\\.venv\\Scripts\\python.exe",
      "args": ["-m", "illustrator"]
    }
  }
}
```

The server exposes these core tools:

- `run`: execute ExtendScript in Illustrator
- `view`: capture the Illustrator window
- `vectorize_bitmap`: convert a bitmap into a `.jsx` script and optionally execute it/save `.ai`
- `get_prompt_suggestions`, `get_system_prompt`, `get_prompting_tips`, `get_advanced_template`, `help`: prompt helpers inherited from the original project

Example `vectorize_bitmap` arguments:

```json
{
  "image_path": "E:\\input.jpg",
  "output_path": "E:\\output.ai",
  "jsx_path": "E:\\output.jsx",
  "vector_mode": "image_trace",
  "colors": 48,
  "max_dimension": 1200,
  "trace_median_filter": 3,
  "execute": true
}
```

Use `vector_mode: "color"` for deterministic local tracing, `vector_mode: "icon"` for app-icon silhouettes, and `vector_mode: "image_trace"` for Illustrator Image Trace.

## Layer planning

Local vectorization can optionally rename layers with a visual planner:

- `layer_provider: "auto"` uses OpenAI vision when `OPENAI_API_KEY` is available, otherwise falls back to heuristic layers.
- `layer_provider: "openai"` requires an OpenAI API key.
- `layer_provider: "local"` uses a local llama.cpp multimodal model.
- `layer_provider: "none"` disables semantic layer planning.

Strict validation is available with `require_visual_model: true`; the tool stops before generating JSX if the visual planner does not complete.

## Codex skill

This repo includes a skill at:

```text
skills/illustrator-vectorizer
```

Use it when you want Codex to choose the best vectorization mode, run the pipeline, inspect previews, and hand back `.ai`/`.jsx` outputs. To install it locally, copy that folder into your Codex skills directory:

```powershell
Copy-Item -Recurse .\skills\illustrator-vectorizer C:\Users\Administrator\.codex\skills\illustrator-vectorizer
```

## Development

Run tests:

```bash
python -m unittest discover -s tests -v
```

Important files:

- `illustrator/server.py`: MCP tools and Illustrator execution
- `illustrator/vectorizer.py`: deterministic local color/icon vectorization
- `illustrator/image_trace.py`: native Illustrator Image Trace JSX generation
- `illustrator/vectorize_cli.py`: command line entry point
- `skills/illustrator-vectorizer/SKILL.md`: Codex skill workflow

## Notes

- `.env.local` is ignored and can hold local API keys.
- Generated `.ai` files are Adobe Illustrator documents; the `.jsx` files are reproducible scripts used to create them.
- JPEG sources often need `image-trace` mode or preprocessing because compression artifacts become tiny vector fragments.
