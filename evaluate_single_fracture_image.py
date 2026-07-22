from __future__ import annotations

import argparse
import base64
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from plugins.ai_assistant.ai_core.config import AIConfig
from plugins.ai_assistant.services.fracture_complete_workflow import _json_payload
from plugins.ai_assistant.services.fracture_vision_service import FractureVisionPipeline


SINGLE_IMAGE_SCHEMA = {
    "name": "single_borehole_image_fracture_candidates",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "reason": {"type": "string"},
            "candidates": {
                "type": "array",
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "properties": {
                        "candidate_id": {"type": "string"},
                        "fracture_type": {"type": "string", "enum": ["Conductive", "Resistive"]},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "x_start_norm": {"type": "number", "minimum": 0, "maximum": 1},
                        "x_end_norm": {"type": "number", "minimum": 0, "maximum": 1},
                        "y_top_norm": {"type": "number", "minimum": 0, "maximum": 1},
                        "y_bottom_norm": {"type": "number", "minimum": 0, "maximum": 1},
                        "anchor_points": {
                            "type": "array",
                            "minItems": 0,
                            "maxItems": 8,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "x_norm": {"type": "number", "minimum": 0, "maximum": 1},
                                    "y_norm": {"type": "number", "minimum": 0, "maximum": 1},
                                },
                                "required": ["x_norm", "y_norm"],
                                "additionalProperties": False,
                            },
                        },
                        "continuity_reason": {"type": "string"},
                        "needs_review": {"type": "boolean"},
                    },
                    "required": [
                        "candidate_id",
                        "fracture_type",
                        "confidence",
                        "x_start_norm",
                        "x_end_norm",
                        "y_top_norm",
                        "y_bottom_norm",
                        "anchor_points",
                        "continuity_reason",
                        "needs_review",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["reason", "candidates"],
        "additionalProperties": False,
    },
}


def data_url(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def image_to_data_url(image: Image.Image) -> str:
    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def build_preprocessed_variants(image_path: Path) -> dict[str, Image.Image]:
    source = Image.open(image_path).convert("RGB")
    gray = ImageOps.grayscale(source)
    contrast = ImageEnhance.Contrast(source).enhance(1.8)
    sharp = ImageEnhance.Sharpness(contrast).enhance(1.8)

    # Conductive fracture helper: emphasize dark, narrow anomalies.
    dark = ImageOps.invert(gray)
    dark = ImageEnhance.Contrast(dark).enhance(2.2)
    dark_binary = dark.point(lambda p: 255 if p > 145 else 0).convert("RGB")

    # Resistive fracture helper: emphasize bright, narrow anomalies.
    bright = ImageEnhance.Contrast(gray).enhance(2.2)
    bright_binary = bright.point(lambda p: 255 if p > 185 else 0).convert("RGB")

    # Edge view is useful for line placement, but noisy enough that it should be advisory.
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edges = ImageEnhance.Contrast(edges).enhance(2.5).convert("RGB")

    variants = {
        "original": source,
        "contrast_sharp": sharp,
        "dark_binary": dark_binary,
        "bright_binary": bright_binary,
        "edges": edges,
    }
    variants.update(build_advanced_variants(source))
    return variants


def _to_uint8(array):
    import numpy as np

    array = np.asarray(array, dtype=float)
    finite = array[np.isfinite(array)]
    if finite.size == 0:
        return np.zeros(array.shape, dtype=np.uint8)
    lo, hi = np.percentile(finite, [2, 98])
    if hi <= lo:
        hi = lo + 1.0
    scaled = (array - lo) / (hi - lo) * 255.0
    scaled = np.nan_to_num(scaled, nan=0.0, posinf=255.0, neginf=0.0)
    return np.clip(scaled, 0, 255).astype(np.uint8)


def _horizontal_box_blur(array, radius):
    import numpy as np

    padded = np.pad(array, ((0, 0), (radius, radius)), mode="edge")
    cumulative = np.cumsum(padded, axis=1, dtype=float)
    return (cumulative[:, 2 * radius:] - cumulative[:, :-2 * radius]) / float(2 * radius)


def _vertical_box_blur(array, radius):
    import numpy as np

    padded = np.pad(array, ((radius, radius), (0, 0)), mode="edge")
    cumulative = np.cumsum(padded, axis=0, dtype=float)
    return (cumulative[2 * radius:, :] - cumulative[:-2 * radius, :]) / float(2 * radius)


def _line_response(array, angle_deg, length=17):
    import numpy as np

    angle = math.radians(angle_deg)
    dx = math.cos(angle)
    dy = math.sin(angle)
    accum = np.zeros_like(array, dtype=float)
    count = 0
    half = length // 2
    h, w = array.shape
    for step in range(-half, half + 1):
        sx = int(round(step * dx))
        sy = int(round(step * dy))
        shifted = np.zeros_like(array, dtype=float)
        src_y0 = max(0, -sy)
        src_y1 = min(h, h - sy)
        src_x0 = max(0, -sx)
        src_x1 = min(w, w - sx)
        dst_y0 = max(0, sy)
        dst_y1 = min(h, h + sy)
        dst_x0 = max(0, sx)
        dst_x1 = min(w, w + sx)
        shifted[dst_y0:dst_y1, dst_x0:dst_x1] = array[src_y0:src_y1, src_x0:src_x1]
        accum += shifted
        count += 1
    return accum / max(1, count)


def _mask_pad_gaps(gray_array):
    import numpy as np

    # White pad gaps/tool gaps should not become high-confidence line evidence.
    return gray_array > 245


def _dilate_columns(mask, radius):
    import numpy as np

    if radius <= 0:
        return mask
    output = np.array(mask, dtype=bool, copy=True)
    for shift in range(1, radius + 1):
        output[:, shift:] |= mask[:, :-shift]
        output[:, :-shift] |= mask[:, shift:]
    return output


def build_advanced_variants(source: Image.Image) -> dict[str, Image.Image]:
    import numpy as np

    gray = np.asarray(ImageOps.grayscale(source), dtype=float)
    gap_mask = _dilate_columns(_mask_pad_gaps(gray), radius=5)

    horizontal_background = _horizontal_box_blur(gray, radius=23)
    vertical_background = _vertical_box_blur(gray, radius=7)

    # Remove laterally continuous bedding bands. Dark/bright residuals highlight
    # anomalies that differ from the dominant horizontal fabric.
    residual = gray - horizontal_background
    dark_residual = -residual
    bright_residual = residual
    dark_residual[gap_mask] = np.nan
    bright_residual[gap_mask] = np.nan

    # Directional filters: compare oblique line response against horizontal response.
    dark_source = 255.0 - gray
    bright_source = gray.copy()
    for arr in (dark_source, bright_source):
        arr[gap_mask] = 0
    horizontal_dark = _line_response(dark_source, 0, length=25)
    diagonal_dark = np.maximum(_line_response(dark_source, 35, length=19), _line_response(dark_source, -35, length=19))
    horizontal_bright = _line_response(bright_source, 0, length=25)
    diagonal_bright = np.maximum(
        _line_response(bright_source, 35, length=19),
        _line_response(bright_source, -35, length=19),
    )

    dark_diagonal = diagonal_dark - 0.85 * horizontal_dark
    bright_diagonal = diagonal_bright - 0.85 * horizontal_bright
    dark_diagonal[gap_mask] = 0
    bright_diagonal[gap_mask] = 0

    # Keep strongest non-horizontal conductive evidence as a sparse helper mask.
    dark_sparse = _to_uint8(dark_diagonal)
    dark_sparse = np.where(dark_sparse > 178, 255, 0).astype(np.uint8)

    return {
        "dark_residual": _apply_gap_display_mask(Image.fromarray(_to_uint8(dark_residual), "L"), gap_mask).convert("RGB"),
        "bright_residual": _apply_gap_display_mask(Image.fromarray(_to_uint8(bright_residual), "L"), gap_mask).convert("RGB"),
        "dark_diagonal": Image.fromarray(_to_uint8(dark_diagonal), "L").convert("RGB"),
        "bright_diagonal": Image.fromarray(_to_uint8(bright_diagonal), "L").convert("RGB"),
        "dark_diagonal_sparse": Image.fromarray(dark_sparse, "L").convert("RGB"),
    }


def _apply_gap_display_mask(image: Image.Image, gap_mask) -> Image.Image:
    import numpy as np

    arr = np.asarray(image.convert("L"), dtype=np.uint8).copy()
    arr[np.asarray(gap_mask, dtype=bool)] = 0
    return Image.fromarray(arr, "L")


def save_preprocessed_variants(image_path: Path, out_dir: Path) -> dict[str, Path]:
    paths = {}
    for name, image in build_preprocessed_variants(image_path).items():
        path = out_dir / f"{image_path.stem}_{name}.png"
        image.save(path)
        paths[name] = path
    return paths


def fit_normalized_sine(points: list[dict]) -> tuple[float, float, float] | None:
    try:
        import numpy as np
    except Exception:
        return None
    if len(points) < 3:
        return None
    x = np.asarray([float(p["x_norm"]) * 2.0 * math.pi for p in points], dtype=float)
    y = np.asarray([float(p["y_norm"]) for p in points], dtype=float)
    design = np.column_stack([np.ones_like(x), np.sin(x), np.cos(x)])
    coeffs, *_ = np.linalg.lstsq(design, y, rcond=None)
    offset, sin_coeff, cos_coeff = [float(v) for v in coeffs]
    return offset, sin_coeff, cos_coeff


def draw_overlay(image_path: Path, payload: dict, out_path: Path) -> None:
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    width, height = image.size
    colors = {"Conductive": (0, 220, 255), "Resistive": (255, 0, 128)}
    for index, candidate in enumerate(payload.get("candidates") or [], start=1):
        color = colors.get(candidate.get("fracture_type"), (255, 255, 0))
        x0 = float(candidate["x_start_norm"]) * width
        x1 = float(candidate["x_end_norm"]) * width
        y0 = float(candidate["y_top_norm"]) * height
        y1 = float(candidate["y_bottom_norm"]) * height
        draw.rectangle((x0, y0, x1, y1), outline=color, width=2)
        draw.text((x0 + 3, max(0, y0 - 13)), f"F{index}", fill=color)
        points = candidate.get("anchor_points") or []
        fit = fit_normalized_sine(points)
        if fit is not None:
            offset, sin_coeff, cos_coeff = fit
            samples = []
            for step in range(121):
                x_norm = step / 120.0
                theta = x_norm * 2.0 * math.pi
                y_norm = offset + sin_coeff * math.sin(theta) + cos_coeff * math.cos(theta)
                samples.append((x_norm * width, y_norm * height))
            draw.line(samples, fill=color, width=2)
        for point in points:
            x = float(point["x_norm"]) * width
            y = float(point["y_norm"]) * height
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=(255, 240, 0), outline=(0, 0, 0), width=1)
    image.save(out_path)


def call_model_for_image(pipeline, client, model: str, image_url: str, variant_name: str) -> dict:
    view_hint = (
        "This is the original color image."
        if variant_name == "original"
        else f"This is a preprocessed helper view named {variant_name}; use it to localize lineaments, "
             "but keep geology conservative and avoid reporting bedding/noise."
    )
    prompt = (
        "Detect fracture candidates in this cropped FMI/EMI-like unwrapped borehole image. "
        "There is no depth scale, so use normalized coordinates within the image. "
        "Conductive fractures are narrow dark curved/sinusoidal traces; resistive fractures are narrow bright traces. "
        "Do not report ordinary repeated horizontal bedding, pad gaps, or vertical tool artifacts. "
        "Return only visible candidate segments. Use anchor_points only on readable parts of the same trace; "
        "do not extrapolate through blank white pad gaps. Mark needs_review=true when evidence is partial, weak, "
        f"or could be bedding. {view_hint}"
    )
    messages = [
        {"role": "system", "content": "You are a cautious borehole image fracture picking assistant."},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url, "detail": "high"}},
            ],
        },
    ]
    response = pipeline._request(client, model, messages, response_schema=SINGLE_IMAGE_SCHEMA)
    return _json_payload(response)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("--out-dir", type=Path, default=Path("logs/fracture_detection/single_image_tests"))
    parser.add_argument(
        "--variants",
        nargs="+",
        default=["original"],
        choices=[
            "original",
            "contrast_sharp",
            "dark_binary",
            "bright_binary",
            "edges",
            "dark_residual",
            "bright_residual",
            "dark_diagonal",
            "bright_diagonal",
            "dark_diagonal_sparse",
            "all",
        ],
        help="Image variants to send to the vision model.",
    )
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    variant_paths = save_preprocessed_variants(args.image, args.out_dir)
    selected = list(args.variants)
    if "all" in selected:
        selected = list(variant_paths.keys())

    config = AIConfig().get_resolved_vision_config()
    if not config.get("api_key") or not config.get("model"):
        raise RuntimeError("Vision model is not configured in PyLog AI settings.")
    pipeline = FractureVisionPipeline()
    client = pipeline._create_client(config)
    stem = args.image.stem
    combined = {"image": str(args.image), "model": config["model"], "variants": {}}
    for variant_name in selected:
        variant_path = variant_paths[variant_name]
        payload = call_model_for_image(
            pipeline,
            client,
            config["model"],
            image_to_data_url(Image.open(variant_path).convert("RGB")),
            variant_name,
        )
        json_path = args.out_dir / f"{stem}_{variant_name}_ai_candidates.json"
        overlay_path = args.out_dir / f"{stem}_{variant_name}_ai_overlay.png"
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        draw_overlay(variant_path, payload, overlay_path)
        combined["variants"][variant_name] = {
            "preprocessed_image": str(variant_path),
            "json": str(json_path),
            "overlay": str(overlay_path),
            "candidate_count": len(payload.get("candidates") or []),
            "payload": payload,
        }
        print(f"{variant_name}: {json_path}")
        print(f"{variant_name}: {overlay_path}")
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    combined_path = args.out_dir / f"{stem}_multi_variant_ai_candidates.json"
    combined_path.write_text(json.dumps(combined, indent=2), encoding="utf-8")
    print(combined_path)


if __name__ == "__main__":
    main()
