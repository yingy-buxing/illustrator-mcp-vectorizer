"""Bitmap to Illustrator vectorization helpers.

The pipeline in this module is intentionally local and deterministic:

1. load an input bitmap
2. choose a color count when one is not supplied
3. quantize the image into a small palette
4. split each palette color into connected color regions
5. trace region contours on the pixel grid
6. simplify contours
7. fit lightweight Bezier handles
8. infer a layer structure
9. emit Illustrator ExtendScript
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageFilter


Point = tuple[float, float]
Color = tuple[int, int, int]


@dataclass(slots=True)
class VectorizerOptions:
    colors: int | None = None
    max_colors: int = 12
    min_colors: int = 3
    max_dimension: int = 512
    min_area: int = 16
    simplify_tolerance: float = 1.6
    bezier_smoothing: float = 0.25
    background_color: Color = (255, 255, 255)
    layer_strategy: str = "visual_heuristic"


@dataclass(slots=True)
class BezierPoint:
    anchor: Point
    left: Point
    right: Point
    smooth: bool


@dataclass(slots=True)
class VectorShape:
    color: Color
    area: int
    bbox: tuple[int, int, int, int]
    contour: list[Point]
    beziers: list[BezierPoint]
    layer_name: str


@dataclass(slots=True)
class VectorDocument:
    width: int
    height: int
    source_path: str
    options: VectorizerOptions
    palette: list[Color]
    shapes: list[VectorShape] = field(default_factory=list)

    def summary(self) -> dict:
        layers: dict[str, int] = {}
        for shape in self.shapes:
            layers[shape.layer_name] = layers.get(shape.layer_name, 0) + 1
        return {
            "source_path": self.source_path,
            "width": self.width,
            "height": self.height,
            "palette": [rgb_to_hex(color) for color in self.palette],
            "shape_count": len(self.shapes),
            "layers": layers,
        }


def vectorize_bitmap(image_path: str | os.PathLike[str], options: VectorizerOptions | None = None) -> VectorDocument:
    """Run the bitmap vectorization pipeline and return an in-memory document."""
    opts = options or VectorizerOptions()
    image = _load_image(image_path, opts.background_color)
    image = _resize_to_limit(image, opts.max_dimension)

    color_count = opts.colors or _choose_color_count(image, opts.min_colors, opts.max_colors)
    indexed, palette = _quantize_image(image, color_count)
    labels = list(indexed.getdata())
    width, height = indexed.size

    shapes: list[VectorShape] = []
    for component in _connected_components(labels, width, height, opts.min_area):
        color = palette[component.label]
        loops = _trace_component_loops(component.pixels)
        if not loops:
            continue

        contour = max(loops, key=lambda loop: abs(_polygon_area(loop)))
        if len(contour) < 3:
            continue

        simplified = _simplify_closed(contour, opts.simplify_tolerance)
        if len(simplified) < 3:
            continue

        beziers = _fit_bezier_points(simplified, opts.bezier_smoothing)
        layer_name = _infer_layer_name(color, component.area, width * height, component.bbox, opts.layer_strategy)
        shapes.append(
            VectorShape(
                color=color,
                area=component.area,
                bbox=component.bbox,
                contour=simplified,
                beziers=beziers,
                layer_name=layer_name,
            )
        )

    shapes.sort(key=lambda shape: shape.area, reverse=True)
    return VectorDocument(
        width=width,
        height=height,
        source_path=str(Path(image_path)),
        options=opts,
        palette=palette,
        shapes=shapes,
    )


def vectorize_icon_silhouette(
    image_path: str | os.PathLike[str],
    options: VectorizerOptions | None = None,
) -> VectorDocument:
    """Vectorize app-style icons without letting subtle gradients split layers."""
    opts = options or VectorizerOptions()
    image = _resize_to_limit(_load_image(image_path, opts.background_color), opts.max_dimension)
    width, height = image.size
    pixels = list(image.getdata())

    background_mask = [_is_icon_background_color(color) for color in pixels]
    background_mask = _filter_mask(background_mask, width, height, close=True)
    background_components = list(_mask_components(background_mask, width, height, max(opts.min_area, 64)))
    if not background_components:
        return vectorize_bitmap(image_path, options)

    background_component = max(background_components, key=lambda component: component.area)
    background_shape = _shape_from_component(
        component=background_component,
        color=_average_color(pixels, width, background_component.pixels, fallback=(31, 198, 199)),
        layer_name="01 Background",
        simplify_tolerance=max(opts.simplify_tolerance, 3.0),
        smoothing=max(opts.bezier_smoothing, 0.25),
    )

    foreground_mask = [_is_icon_foreground_color(color) for color in pixels]
    foreground_mask = _remove_border_connected_mask(foreground_mask, width, height)
    foreground_mask = _filter_mask(foreground_mask, width, height, close=True)
    foreground_components = [
        component
        for component in _mask_components(foreground_mask, width, height, max(opts.min_area, 24))
        if _is_useful_icon_foreground_component(component, width, height)
    ]
    foreground_components.sort(key=lambda component: component.area, reverse=True)
    largest_foreground_area = foreground_components[0].area if foreground_components else 0
    background_color = background_shape.color if background_shape else (31, 198, 199)

    shapes: list[VectorShape] = []
    if background_shape:
        shapes.append(background_shape)

    for component in foreground_components:
        layer_name = "02 Main icon" if component.area >= largest_foreground_area * 0.35 else "03 Decorative marks"
        component_shapes = _shapes_from_component_with_cutouts(
            component=component,
            color=_average_color(pixels, width, component.pixels, fallback=(248, 255, 255)),
            cutout_color=background_color,
            layer_name=layer_name,
            simplify_tolerance=max(opts.simplify_tolerance, 2.2),
            smoothing=opts.bezier_smoothing,
        )
        shapes.extend(component_shapes)

    return VectorDocument(
        width=width,
        height=height,
        source_path=str(Path(image_path)),
        options=opts,
        palette=[shape.color for shape in shapes],
        shapes=shapes,
    )


def generate_illustrator_jsx(document: VectorDocument, output_path: str | os.PathLike[str] | None = None) -> str:
    """Generate ExtendScript that builds the vector document and optionally saves it."""
    lines: list[str] = [
        "#target illustrator",
        "(function () {",
        "  var doc = app.documents.add(DocumentColorSpace.RGB, "
        f"{_js_number(document.width)}, {_js_number(document.height)});",
        "  doc.rulerUnits = RulerUnits.Points;",
        "",
        "  function rgb(r, g, b) {",
        "    var c = new RGBColor();",
        "    c.red = r; c.green = g; c.blue = b;",
        "    return c;",
        "  }",
        "",
        "  function ensureLayer(name) {",
        "    for (var i = 0; i < doc.layers.length; i++) {",
        "      if (doc.layers[i].name === name) return doc.layers[i];",
        "    }",
        "    var layer = doc.layers.add();",
        "    layer.name = name;",
        "    return layer;",
        "  }",
        "",
        "  function addShape(layerName, fillColor, points) {",
        "    var layer = ensureLayer(layerName);",
        "    var item = layer.pathItems.add();",
        "    item.closed = true;",
        "    item.filled = true;",
        "    item.stroked = false;",
        "    item.fillColor = fillColor;",
        "    for (var i = 0; i < points.length; i++) {",
        "      var p = item.pathPoints.add();",
        "      p.anchor = points[i].anchor;",
        "      p.leftDirection = points[i].left;",
        "      p.rightDirection = points[i].right;",
        "      p.pointType = points[i].smooth ? PointType.SMOOTH : PointType.CORNER;",
        "    }",
        "    return item;",
        "  }",
        "",
    ]

    for shape in document.shapes:
        points_js = _shape_points_js(shape.beziers, document.height)
        lines.extend(
            [
                "  addShape(",
                f"    {_js_string(shape.layer_name)},",
                f"    rgb({shape.color[0]}, {shape.color[1]}, {shape.color[2]}),",
                f"    {points_js}",
                "  );",
            ]
        )

    if output_path:
        lines.extend(
            [
                "",
                f"  var outFile = new File({_js_string(str(Path(output_path))) });",
                "  doc.saveAs(outFile);",
            ]
        )

    lines.extend(
        [
            "",
            "  return "
            + _js_string(
                "Vectorized "
                f"{document.width}x{document.height}, "
                f"shapes={len(document.shapes)}, "
                f"output={str(Path(output_path)) if output_path else ''}"
            )
            + ";",
            "}());",
        ]
    )
    return "\n".join(lines)


def vectorize_bitmap_to_jsx(
    image_path: str | os.PathLike[str],
    output_path: str | os.PathLike[str] | None = None,
    options: VectorizerOptions | None = None,
) -> tuple[VectorDocument, str]:
    document = vectorize_bitmap(image_path, options)
    return document, generate_illustrator_jsx(document, output_path)


def vectorize_icon_silhouette_to_jsx(
    image_path: str | os.PathLike[str],
    output_path: str | os.PathLike[str] | None = None,
    options: VectorizerOptions | None = None,
) -> tuple[VectorDocument, str]:
    document = vectorize_icon_silhouette(image_path, options)
    return document, generate_illustrator_jsx(document, output_path)


@dataclass(slots=True)
class _Component:
    label: int
    pixels: set[tuple[int, int]]
    area: int
    bbox: tuple[int, int, int, int]


def _shape_from_component(
    component: _Component,
    color: Color,
    layer_name: str,
    simplify_tolerance: float,
    smoothing: float,
) -> VectorShape | None:
    loops = _trace_component_loops(component.pixels)
    if not loops:
        return None

    contour = max(loops, key=lambda loop: abs(_polygon_area(loop)))
    if len(contour) < 3:
        return None

    simplified = _simplify_closed(contour, simplify_tolerance)
    if len(simplified) < 3:
        return None

    return VectorShape(
        color=color,
        area=component.area,
        bbox=component.bbox,
        contour=simplified,
        beziers=_fit_bezier_points(simplified, smoothing),
        layer_name=layer_name,
    )


def _shapes_from_component_with_cutouts(
    component: _Component,
    color: Color,
    cutout_color: Color,
    layer_name: str,
    simplify_tolerance: float,
    smoothing: float,
) -> list[VectorShape]:
    loops = _trace_component_loops(component.pixels)
    if not loops:
        return []

    loops.sort(key=lambda loop: abs(_polygon_area(loop)), reverse=True)
    shapes: list[VectorShape] = []
    for index, loop in enumerate(loops):
        if len(loop) < 3:
            continue
        simplified = _simplify_closed(loop, simplify_tolerance)
        if len(simplified) < 3:
            continue
        loop_area = max(1, round(abs(_polygon_area(loop))))
        fill = color if index == 0 else cutout_color
        shapes.append(
            VectorShape(
                color=fill,
                area=component.area if index == 0 else loop_area,
                bbox=_loop_bbox(loop),
                contour=simplified,
                beziers=_fit_bezier_points(simplified, smoothing),
                layer_name=layer_name,
            )
        )
    return shapes


def _loop_bbox(loop: list[Point]) -> tuple[int, int, int, int]:
    xs = [point[0] for point in loop]
    ys = [point[1] for point in loop]
    return (math.floor(min(xs)), math.floor(min(ys)), math.ceil(max(xs)), math.ceil(max(ys)))


def _load_image(image_path: str | os.PathLike[str], background: Color) -> Image.Image:
    with Image.open(image_path) as image:
        rgba = image.convert("RGBA")
        canvas = Image.new("RGBA", rgba.size, (*background, 255))
        canvas.alpha_composite(rgba)
        return canvas.convert("RGB")


def _is_icon_background_color(color: Color) -> bool:
    r, g, b = color
    saturation = _saturation(color)
    luminance = _relative_luminance(color)
    return saturation > 0.16 and 0.22 < luminance < 0.94 and g > r + 18 and b > r + 18


def _is_icon_foreground_color(color: Color) -> bool:
    saturation = _saturation(color)
    luminance = _relative_luminance(color)
    return luminance > 0.72 and saturation < 0.32


def _filter_mask(mask: list[bool], width: int, height: int, close: bool = False) -> list[bool]:
    mask_image = Image.new("L", (width, height))
    mask_image.putdata([255 if value else 0 for value in mask])
    mask_image = mask_image.filter(ImageFilter.MedianFilter(3))
    if close:
        mask_image = mask_image.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    return [value >= 128 for value in mask_image.getdata()]


def _remove_border_connected_mask(mask: list[bool], width: int, height: int) -> list[bool]:
    cleaned = list(mask)
    visited = bytearray(width * height)
    queue: deque[int] = deque()

    for x in range(width):
        for index in (x, (height - 1) * width + x):
            if cleaned[index] and not visited[index]:
                visited[index] = 1
                queue.append(index)
    for y in range(height):
        for index in (y * width, y * width + width - 1):
            if cleaned[index] and not visited[index]:
                visited[index] = 1
                queue.append(index)

    while queue:
        index = queue.popleft()
        cleaned[index] = False
        x = index % width
        y = index // width
        for neighbor in _neighbor_indices(index, x, y, width, height):
            if cleaned[neighbor] and not visited[neighbor]:
                visited[neighbor] = 1
                queue.append(neighbor)

    return cleaned


def _mask_components(mask: list[bool], width: int, height: int, min_area: int) -> Iterable[_Component]:
    labels = [1 if value else 0 for value in mask]
    for component in _connected_components(labels, width, height, min_area):
        if component.label == 1:
            yield component


def _is_useful_icon_foreground_component(component: _Component, width: int, height: int) -> bool:
    min_x, min_y, max_x, max_y = component.bbox
    bbox_area = _bbox_area(component.bbox)
    if bbox_area <= 0:
        return False
    if component.area / bbox_area < 0.08:
        return False
    if min_x > width * 0.82 and min_y > height * 0.82:
        return False
    if max_x < width * 0.04 or max_y < height * 0.04:
        return False
    if min_x > width * 0.96 or min_y > height * 0.96:
        return False
    return True


def _average_color(pixels: list[Color], width: int, component_pixels: set[tuple[int, int]], fallback: Color) -> Color:
    if not component_pixels:
        return fallback
    total_r = total_g = total_b = 0
    count = 0
    for x, y in component_pixels:
        try:
            r, g, b = pixels[y * width + x]
        except IndexError:
            return fallback
        total_r += r
        total_g += g
        total_b += b
        count += 1
    if not count:
        return fallback
    return (round(total_r / count), round(total_g / count), round(total_b / count))


def _resize_to_limit(image: Image.Image, max_dimension: int) -> Image.Image:
    if max_dimension <= 0:
        return image
    width, height = image.size
    longest = max(width, height)
    if longest <= max_dimension:
        return image
    scale = max_dimension / longest
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


def _choose_color_count(image: Image.Image, min_colors: int, max_colors: int) -> int:
    probe = image.copy()
    probe.thumbnail((128, 128))
    quantized = probe.quantize(colors=max_colors, method=Image.Quantize.MEDIANCUT)
    histogram = quantized.histogram()
    total = max(1, probe.size[0] * probe.size[1])
    meaningful = sum(1 for count in histogram[:max_colors] if count / total >= 0.01)
    return max(min_colors, min(max_colors, meaningful or min_colors))


def _quantize_image(image: Image.Image, colors: int) -> tuple[Image.Image, list[Color]]:
    colors = max(2, min(256, colors))
    indexed = image.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    raw_palette = indexed.getpalette() or []
    used_labels = sorted(set(indexed.getdata()))
    palette: list[Color] = [(0, 0, 0)] * (max(used_labels) + 1 if used_labels else 0)
    for label in used_labels:
        idx = label * 3
        palette[label] = tuple(raw_palette[idx:idx + 3])  # type: ignore[assignment]
    return indexed, palette


def _connected_components(labels: list[int], width: int, height: int, min_area: int) -> Iterable[_Component]:
    visited = bytearray(width * height)
    for start_index, label in enumerate(labels):
        if visited[start_index]:
            continue

        queue: deque[int] = deque([start_index])
        visited[start_index] = 1
        pixels: set[tuple[int, int]] = set()
        min_x = width
        min_y = height
        max_x = 0
        max_y = 0

        while queue:
            index = queue.popleft()
            x = index % width
            y = index // width
            pixels.add((x, y))
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x + 1)
            max_y = max(max_y, y + 1)

            for neighbor in _neighbor_indices(index, x, y, width, height):
                if not visited[neighbor] and labels[neighbor] == label:
                    visited[neighbor] = 1
                    queue.append(neighbor)

        area = len(pixels)
        if area >= min_area:
            yield _Component(label=label, pixels=pixels, area=area, bbox=(min_x, min_y, max_x, max_y))


def _neighbor_indices(index: int, x: int, y: int, width: int, height: int) -> Iterable[int]:
    if x > 0:
        yield index - 1
    if x + 1 < width:
        yield index + 1
    if y > 0:
        yield index - width
    if y + 1 < height:
        yield index + width


def _trace_component_loops(pixels: set[tuple[int, int]]) -> list[list[Point]]:
    edges: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for x, y in pixels:
        if (x, y - 1) not in pixels:
            edges.append(((x, y), (x + 1, y)))
        if (x + 1, y) not in pixels:
            edges.append(((x + 1, y), (x + 1, y + 1)))
        if (x, y + 1) not in pixels:
            edges.append(((x + 1, y + 1), (x, y + 1)))
        if (x - 1, y) not in pixels:
            edges.append(((x, y + 1), (x, y)))

    by_start: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    for start, end in edges:
        by_start[start].append(end)

    unused = set(edges)
    loops: list[list[Point]] = []
    while unused:
        start, end = next(iter(unused))
        unused.remove((start, end))
        loop: list[tuple[int, int]] = [start, end]
        current = end

        while current != start:
            candidates = by_start.get(current, [])
            next_end = None
            for candidate in candidates:
                edge = (current, candidate)
                if edge in unused:
                    next_end = candidate
                    break
            if next_end is None:
                break
            unused.remove((current, next_end))
            current = next_end
            loop.append(current)

        if len(loop) >= 4 and loop[-1] == start:
            loops.append([(float(x), float(y)) for x, y in loop[:-1]])

    return loops


def _simplify_closed(points: list[Point], tolerance: float) -> list[Point]:
    if len(points) <= 3 or tolerance <= 0:
        return points
    simplified = _rdp(points + [points[0]], tolerance)
    if simplified and simplified[-1] == simplified[0]:
        simplified.pop()
    return simplified if len(simplified) >= 3 else points


def _rdp(points: list[Point], epsilon: float) -> list[Point]:
    if len(points) < 3:
        return points

    start = points[0]
    end = points[-1]
    max_distance = -1.0
    index = 0
    for i in range(1, len(points) - 1):
        distance = _point_line_distance(points[i], start, end)
        if distance > max_distance:
            max_distance = distance
            index = i

    if max_distance > epsilon:
        left = _rdp(points[: index + 1], epsilon)
        right = _rdp(points[index:], epsilon)
        return left[:-1] + right
    return [start, end]


def _point_line_distance(point: Point, start: Point, end: Point) -> float:
    px, py = point
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    if dx == 0 and dy == 0:
        return math.hypot(px - sx, py - sy)
    numerator = abs(dy * px - dx * py + ex * sy - ey * sx)
    denominator = math.hypot(dx, dy)
    return numerator / denominator


def _fit_bezier_points(points: list[Point], smoothing: float) -> list[BezierPoint]:
    smoothing = max(0.0, min(1.0, smoothing))
    if len(points) < 3 or smoothing == 0:
        return [BezierPoint(anchor=p, left=p, right=p, smooth=False) for p in points]

    fitted: list[BezierPoint] = []
    count = len(points)
    for i, anchor in enumerate(points):
        prev_point = points[(i - 1) % count]
        next_point = points[(i + 1) % count]
        vx = (next_point[0] - prev_point[0]) * smoothing / 6.0
        vy = (next_point[1] - prev_point[1]) * smoothing / 6.0
        left = (anchor[0] - vx, anchor[1] - vy)
        right = (anchor[0] + vx, anchor[1] + vy)
        fitted.append(BezierPoint(anchor=anchor, left=left, right=right, smooth=True))
    return fitted


def _infer_layer_name(
    color: Color,
    area: int,
    total_area: int,
    bbox: tuple[int, int, int, int],
    strategy: str,
) -> str:
    if strategy != "visual_heuristic":
        return "Vector shapes"

    luminance = _relative_luminance(color)
    saturation = _saturation(color)
    area_ratio = area / max(1, total_area)
    if area_ratio > 0.35:
        return "01 Background"
    if luminance < 0.22:
        return "02 Shadows"
    if luminance > 0.82 and saturation < 0.2:
        return "05 Highlights"
    if saturation > 0.45:
        return "04 Accent color blocks"
    if _bbox_area(bbox) / max(1, total_area) < 0.02:
        return "06 Details"
    return "03 Main color blocks"


def _relative_luminance(color: Color) -> float:
    r, g, b = (channel / 255 for channel in color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _saturation(color: Color) -> float:
    r, g, b = (channel / 255 for channel in color)
    return max(r, g, b) - min(r, g, b)


def _bbox_area(bbox: tuple[int, int, int, int]) -> int:
    min_x, min_y, max_x, max_y = bbox
    return max(0, max_x - min_x) * max(0, max_y - min_y)


def _polygon_area(points: list[Point]) -> float:
    area = 0.0
    for i, (x1, y1) in enumerate(points):
        x2, y2 = points[(i + 1) % len(points)]
        area += x1 * y2 - x2 * y1
    return area / 2.0


def _shape_points_js(points: list[BezierPoint], document_height: int) -> str:
    data = []
    for point in points:
        data.append(
            {
                "anchor": _to_illustrator_point(point.anchor, document_height),
                "left": _to_illustrator_point(point.left, document_height),
                "right": _to_illustrator_point(point.right, document_height),
                "smooth": point.smooth,
            }
        )
    return json.dumps(data, separators=(",", ":"))


def _to_illustrator_point(point: Point, document_height: int) -> list[float]:
    x, y = point
    return [_round_float(x), _round_float(document_height - y)]


def _round_float(value: float) -> float:
    return round(float(value), 3)


def _js_number(value: float | int) -> str:
    return str(_round_float(value))


def _js_string(value: str) -> str:
    return json.dumps(value)


def rgb_to_hex(color: Color) -> str:
    return "#{:02x}{:02x}{:02x}".format(*color)
