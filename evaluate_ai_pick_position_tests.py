from __future__ import annotations

import argparse
import base64
import json
import math
from pathlib import Path

from plugins.ai_assistant.ai_core.config import AIConfig
from plugins.ai_assistant.services.fracture_complete_workflow import _json_payload
from plugins.ai_assistant.services.fracture_vision_service import FractureVisionPipeline


DEFAULT_TEST_DIR = Path(
    r"C:\Users\72924\.codex\visualizations\2026\07\18\019f7502-70df-7860-bcb0-5d66b08154d1\ai_pick_position_tests"
)

AI_POSITION_SCHEMA = {
    "name": "synthetic_fracture_position_assessment",
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
                        "fracture_type": {
                            "type": "string",
                            "enum": ["Conductive", "Resistive"],
                        },
                        "depth_top": {"type": "number"},
                        "depth_bottom": {"type": "number"},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
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
                    },
                    "required": [
                        "candidate_id",
                        "fracture_type",
                        "depth_top",
                        "depth_bottom",
                        "confidence",
                        "anchor_points",
                        "continuity_reason",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["reason", "candidates"],
        "additionalProperties": False,
    },
}


def image_data_url(path: Path) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{data}"


def truth_depth(fracture: dict, azimuth_deg: float) -> float:
    center = float(fracture["center_depth_m"])
    amplitude = float(fracture["amplitude_m"])
    phase = float(fracture["phase_deg"])
    return center + amplitude * math.sin(math.radians(azimuth_deg + phase))


def visible_at(fracture: dict, azimuth_deg: float) -> bool:
    for start, end in fracture.get("visible_azimuth_ranges_deg") or []:
        if float(start) <= azimuth_deg <= float(end):
            return True
    return False


def depth_iou(a_top: float, a_bottom: float, b_top: float, b_bottom: float) -> float:
    left = max(min(a_top, a_bottom), min(b_top, b_bottom))
    right = min(max(a_top, a_bottom), max(b_top, b_bottom))
    overlap = max(0.0, right - left)
    union = max(max(a_top, a_bottom), max(b_top, b_bottom)) - min(min(a_top, a_bottom), min(b_top, b_bottom))
    return overlap / union if union > 0 else 0.0


def anchor_rmse(candidate: dict, fracture: dict, coordinates: dict) -> float | None:
    points = candidate.get("anchor_points") or []
    if not points:
        return None
    depth_top = float(coordinates["depth_top_m"])
    depth_bottom = float(coordinates["depth_bottom_m"])
    errors = []
    for point in points:
        azimuth = float(point["x_norm"]) * 360.0
        if not visible_at(fracture, azimuth):
            continue
        depth = depth_top + float(point["y_norm"]) * (depth_bottom - depth_top)
        errors.append(depth - truth_depth(fracture, azimuth))
    if not errors:
        return None
    return math.sqrt(sum(error * error for error in errors) / len(errors))


def match_candidates(ai_candidates: list[dict], truths: list[dict], coordinates: dict) -> list[dict]:
    rows = []
    used = set()
    for truth in truths:
        t_top = float(truth["center_depth_m"]) - abs(float(truth["amplitude_m"]))
        t_bottom = float(truth["center_depth_m"]) + abs(float(truth["amplitude_m"]))
        best = None
        best_score = -1.0
        for index, candidate in enumerate(ai_candidates):
            if index in used:
                continue
            type_bonus = 0.2 if candidate.get("fracture_type") == truth.get("fracture_type") else 0.0
            iou = depth_iou(float(candidate["depth_top"]), float(candidate["depth_bottom"]), t_top, t_bottom)
            score = iou + type_bonus
            if score > best_score:
                best_score = score
                best = (index, candidate, iou)
        if best is None:
            rows.append({"truth_id": truth["fracture_id"], "matched": False})
            continue
        index, candidate, iou = best
        used.add(index)
        rmse = anchor_rmse(candidate, truth, coordinates)
        rows.append({
            "truth_id": truth["fracture_id"],
            "matched": True,
            "candidate_id": candidate["candidate_id"],
            "type_ok": candidate.get("fracture_type") == truth.get("fracture_type"),
            "depth_iou": round(iou, 3),
            "anchor_rmse_m": None if rmse is None else round(rmse, 3),
            "confidence": candidate.get("confidence"),
        })
    for index, candidate in enumerate(ai_candidates):
        if index not in used:
            rows.append({
                "truth_id": None,
                "matched": False,
                "candidate_id": candidate.get("candidate_id"),
                "false_positive": True,
                "confidence": candidate.get("confidence"),
            })
    return rows


def build_messages(case: dict, coordinates: dict) -> list[dict]:
    prompt = (
        "You are evaluating synthetic FMI/EMI-like borehole image logs. "
        "Find only true fracture candidates, not bedding. Conductive fractures are dark traces; "
        "resistive fractures are bright traces. A valid fracture should be a narrow curved/sinusoidal "
        "or partial-sinusoidal anomaly that is distinct from repeated bedding. "
        "Return depth_top/depth_bottom in metres and anchor_points as x_norm/y_norm within the image track "
        "and plot area. x_norm=0 means 0 deg azimuth at the left edge of the image track; x_norm=1 means 360 deg. "
        f"The plot depth interval is {coordinates['depth_top_m']} to {coordinates['depth_bottom_m']} m. "
        "Use 3-8 anchors only where the trace is visible. Do not extrapolate anchors through blank pad gaps. "
        "If this is bedding only, return an empty candidates array."
    )
    return [
        {"role": "system", "content": "You locate fracture candidates on borehole image logs with structured output."},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_data_url(Path(case["raw_image"])), "detail": "high"}},
            ],
        },
    ]


def evaluate(test_dir: Path, *, call_api: bool) -> dict:
    manifest = json.loads((test_dir / "manifest.json").read_text(encoding="utf-8"))
    coordinates = manifest["coordinate_system"]
    config = AIConfig().get_resolved_vision_config()
    output = {
        "model": config.get("model") or "",
        "called_api": bool(call_api),
        "cases": [],
    }
    if call_api:
        if not config.get("api_key") or not config.get("model"):
            raise RuntimeError("Vision model is not configured in PyLog AI settings.")
        pipeline = FractureVisionPipeline()
        client = pipeline._create_client(config)
        model = config["model"]
    else:
        pipeline = client = model = None

    for case in manifest["cases"]:
        entry = {
            "case_id": case["case_id"],
            "title": case["title"],
            "truth_count": len(case.get("fractures") or []),
            "raw_image": case["raw_image"],
            "truth_overlay": case["truth_overlay"],
        }
        if call_api:
            response = pipeline._request(
                client,
                model,
                build_messages(case, coordinates),
                response_schema=AI_POSITION_SCHEMA,
            )
            payload = _json_payload(response)
            candidates = payload.get("candidates") or []
            entry["ai_reason"] = payload.get("reason", "")
            entry["ai_candidates"] = candidates
            entry["matches"] = match_candidates(candidates, case.get("fractures") or [], coordinates)
        else:
            entry["dry_run"] = "not called"
        output["cases"].append(entry)
    if call_api and pipeline is not None:
        output["request_metrics"] = pipeline.request_metrics_snapshot()
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate visual-model fracture candidate localization on synthetic images.")
    parser.add_argument("--test-dir", type=Path, default=DEFAULT_TEST_DIR)
    parser.add_argument("--call-api", action="store_true", help="Actually call the configured PyLog vision model.")
    args = parser.parse_args()

    result = evaluate(args.test_dir, call_api=args.call_api)
    suffix = "api" if args.call_api else "dry_run"
    out_path = args.test_dir / f"ai_position_eval_{suffix}.json"
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(out_path)
    for case in result["cases"]:
        print(f"{case['case_id']}: truth={case['truth_count']} candidates={len(case.get('ai_candidates') or [])}")
        for match in case.get("matches") or []:
            print(f"  {match}")


if __name__ == "__main__":
    main()
