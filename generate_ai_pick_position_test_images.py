from __future__ import annotations

import json
import math
import random
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


OUT_DIR = Path(r"C:\Users\72924\.codex\visualizations\2026\07\18\019f7502-70df-7860-bcb0-5d66b08154d1\ai_pick_position_tests")
WIDTH = 720
HEIGHT = 1280
HEADER_H = 90
DEPTH_LEFT_W = 96
TRACK_LEFT = DEPTH_LEFT_W
TRACK_RIGHT = WIDTH - 10
PLOT_TOP = HEADER_H
PLOT_BOTTOM = HEIGHT - 10
DEPTH_TOP = 8074.0
DEPTH_BOTTOM = 8077.0
PAD_GAPS = [(214, 236), (348, 370), (498, 520)]


@dataclass(frozen=True)
class FractureTruth:
    fracture_id: str
    fracture_type: str
    center_depth_m: float
    amplitude_m: float
    phase_deg: float
    visible_azimuth_ranges_deg: list[list[float]]
    confidence: str


@dataclass(frozen=True)
class CaseSpec:
    case_id: str
    title: str
    bedding_style: str
    fractures: list[FractureTruth]
    noise: float = 0.18
    low_contrast: bool = False


def depth_to_y(depth: float) -> float:
    return PLOT_TOP + (depth - DEPTH_TOP) / (DEPTH_BOTTOM - DEPTH_TOP) * (PLOT_BOTTOM - PLOT_TOP)


def y_to_depth(y: float) -> float:
    return DEPTH_TOP + (y - PLOT_TOP) / (PLOT_BOTTOM - PLOT_TOP) * (DEPTH_BOTTOM - DEPTH_TOP)


def x_to_azimuth(x: float) -> float:
    return (x - TRACK_LEFT) / (TRACK_RIGHT - TRACK_LEFT) * 360.0


def azimuth_to_x(azimuth: float) -> float:
    return TRACK_LEFT + (azimuth / 360.0) * (TRACK_RIGHT - TRACK_LEFT)


def fracture_depth(frac: FractureTruth, azimuth_deg: float) -> float:
    return frac.center_depth_m + frac.amplitude_m * math.sin(math.radians(azimuth_deg + frac.phase_deg))


def in_visible_range(frac: FractureTruth, azimuth_deg: float) -> bool:
    return any(start <= azimuth_deg <= end for start, end in frac.visible_azimuth_ranges_deg)


def plasma_color(value: float) -> tuple[int, int, int]:
    value = max(0.0, min(1.0, value))
    stops = [
        (0.00, (15, 0, 36)),
        (0.25, (88, 0, 88)),
        (0.50, (205, 30, 0)),
        (0.75, (255, 158, 0)),
        (1.00, (255, 255, 188)),
    ]
    for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
        if p0 <= value <= p1:
            t = (value - p0) / (p1 - p0)
            return tuple(int(c0[i] + t * (c1[i] - c0[i])) for i in range(3))
    return stops[-1][1]


def draw_base_image(spec: CaseSpec) -> Image.Image:
    rng = random.Random(spec.case_id)
    image = Image.new("RGB", (WIDTH, HEIGHT), (250, 248, 239))
    draw = ImageDraw.Draw(image)

    draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), outline=(0, 0, 0), width=3)
    draw.line((DEPTH_LEFT_W, 0, DEPTH_LEFT_W, HEIGHT), fill=(0, 0, 0), width=3)
    draw.line((0, HEADER_H, WIDTH, HEADER_H), fill=(0, 0, 0), width=3)
    draw.text((DEPTH_LEFT_W + 140, 20), "SYN_RES_DYN", fill=(0, 0, 0))
    draw.text((14, 24), "Depth", fill=(0, 0, 0))

    for depth in range(int(DEPTH_TOP), int(DEPTH_BOTTOM) + 1):
        y = depth_to_y(depth)
        draw.line((0, y, 28, y), fill=(0, 0, 0), width=4)
        draw.text((38, y - 16), str(depth), fill=(0, 0, 0))
    for i in range(31):
        depth = DEPTH_TOP + i * 0.1
        y = depth_to_y(depth)
        draw.line((DEPTH_LEFT_W - 18, y, DEPTH_LEFT_W, y), fill=(0, 0, 0), width=2)

    px = Image.new("RGB", (TRACK_RIGHT - TRACK_LEFT, PLOT_BOTTOM - PLOT_TOP))
    pix = px.load()
    for y in range(px.height):
        depth = y_to_depth(PLOT_TOP + y)
        for x in range(px.width):
            az = x / max(1, px.width - 1) * 360.0
            band = 0.0
            if spec.bedding_style == "horizontal":
                band = math.sin((depth - DEPTH_TOP) * 28.0)
            elif spec.bedding_style == "wavy":
                band = math.sin((depth - DEPTH_TOP) * 27.0 + 0.55 * math.sin(math.radians(az * 2)))
            elif spec.bedding_style == "dense":
                band = 0.6 * math.sin((depth - DEPTH_TOP) * 42.0) + 0.4 * math.sin((depth - DEPTH_TOP) * 72.0)
            noise = spec.noise * (rng.random() - 0.5)
            value = 0.55 + 0.32 * band + noise
            pix[x, y] = plasma_color(value)

    px = px.filter(ImageFilter.GaussianBlur(radius=0.55))
    image.paste(px, (TRACK_LEFT, PLOT_TOP))
    draw = ImageDraw.Draw(image)

    for gap_left, gap_right in PAD_GAPS:
        draw.rectangle((gap_left, PLOT_TOP, gap_right, PLOT_BOTTOM), fill=(255, 255, 255))
    for x in range(TRACK_LEFT, TRACK_RIGHT, 120):
        draw.line((x, PLOT_TOP, x, PLOT_BOTTOM), fill=(245, 245, 245), width=2)

    for frac in spec.fractures:
        color = (255, 248, 155) if frac.fracture_type == "Resistive" else (35, 0, 45)
        half_width = 5 if not spec.low_contrast else 3
        for x in range(TRACK_LEFT, TRACK_RIGHT):
            az = x_to_azimuth(x)
            if not in_visible_range(frac, az):
                continue
            y = depth_to_y(fracture_depth(frac, az))
            if y < PLOT_TOP or y >= PLOT_BOTTOM:
                continue
            if any(left <= x <= right for left, right in PAD_GAPS):
                continue
            alpha = 0.75 if not spec.low_contrast else 0.45
            for dy in range(-half_width, half_width + 1):
                yy = int(round(y + dy))
                if PLOT_TOP <= yy < PLOT_BOTTOM:
                    old = image.getpixel((x, yy))
                    mixed = tuple(int(old[i] * (1 - alpha) + color[i] * alpha) for i in range(3))
                    image.putpixel((x, yy), mixed)

    return image


def draw_truth_overlay(base: Image.Image, spec: CaseSpec) -> Image.Image:
    image = base.copy()
    draw = ImageDraw.Draw(image)
    for frac in spec.fractures:
        color = (255, 0, 128) if frac.fracture_type == "Resistive" else (0, 220, 255)
        for start, end in frac.visible_azimuth_ranges_deg:
            pts = []
            for az in [start + i * (end - start) / 120.0 for i in range(121)]:
                pts.append((azimuth_to_x(az), depth_to_y(fracture_depth(frac, az))))
            draw.line(pts, fill=color, width=4)
        draw.text(
            (azimuth_to_x(frac.visible_azimuth_ranges_deg[0][0]) + 6, depth_to_y(frac.center_depth_m) - 18),
            frac.fracture_id,
            fill=color,
        )
    return image


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cases = [
        CaseSpec(
            "case_01_obvious_resistive",
            "obvious single resistive sinusoid",
            "horizontal",
            [FractureTruth("F1", "Resistive", 8075.30, 0.42, 35.0, [[0, 360]], "high")],
        ),
        CaseSpec(
            "case_02_partial_conductive",
            "partial conductive fracture with pad gaps",
            "horizontal",
            [FractureTruth("F1", "Conductive", 8075.05, 0.33, 120.0, [[20, 155], [245, 330]], "medium")],
        ),
        CaseSpec(
            "case_03_bedding_only_negative",
            "wavy bedding only, no fracture",
            "wavy",
            [],
        ),
        CaseSpec(
            "case_04_two_crossing_candidates",
            "two fractures with different confidence",
            "dense",
            [
                FractureTruth("F1", "Resistive", 8074.95, 0.28, 260.0, [[10, 190]], "medium"),
                FractureTruth("F2", "Conductive", 8076.05, 0.36, 70.0, [[135, 355]], "high"),
            ],
        ),
        CaseSpec(
            "case_05_low_contrast_resistive",
            "low contrast resistive fracture",
            "dense",
            [FractureTruth("F1", "Resistive", 8075.72, 0.22, 185.0, [[40, 295]], "low")],
            noise=0.26,
            low_contrast=True,
        ),
    ]

    manifest = {
        "coordinate_system": {
            "depth_top_m": DEPTH_TOP,
            "depth_bottom_m": DEPTH_BOTTOM,
            "track_left_px": TRACK_LEFT,
            "track_right_px": TRACK_RIGHT,
            "plot_top_px": PLOT_TOP,
            "plot_bottom_px": PLOT_BOTTOM,
            "azimuth_formula": "azimuth_deg=(x-track_left)/(track_right-track_left)*360",
            "depth_formula": "depth_m=depth_top+(y-plot_top)/(plot_bottom-plot_top)*(depth_bottom-depth_top)",
        },
        "cases": [],
    }

    contact = Image.new("RGB", (WIDTH * 2, HEIGHT * len(cases)), (240, 240, 240))
    for i, spec in enumerate(cases):
        raw = draw_base_image(spec)
        truth = draw_truth_overlay(raw, spec)
        raw_path = OUT_DIR / f"{spec.case_id}.png"
        truth_path = OUT_DIR / f"{spec.case_id}_truth.png"
        raw.save(raw_path)
        truth.save(truth_path)
        contact.paste(raw, (0, i * HEIGHT))
        contact.paste(truth, (WIDTH, i * HEIGHT))
        manifest["cases"].append({
            "case_id": spec.case_id,
            "title": spec.title,
            "raw_image": str(raw_path),
            "truth_overlay": str(truth_path),
            "fractures": [asdict(frac) for frac in spec.fractures],
        })

    contact_path = OUT_DIR / "contact_sheet_raw_vs_truth.png"
    manifest_path = OUT_DIR / "manifest.json"
    contact.save(contact_path)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(contact_path)
    print(manifest_path)


if __name__ == "__main__":
    main()
