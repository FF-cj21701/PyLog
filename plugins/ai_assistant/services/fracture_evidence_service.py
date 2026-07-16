from __future__ import annotations

import base64

import numpy as np
from PySide6.QtGui import QImage
from scipy.ndimage import gaussian_filter


MIN_SCORE = 2.30
MIN_COVERAGE = 0.58
MIN_QUADRANT_COVERAGE = 0.50


class FractureEvidenceScorer:
    """Score a fitted full-period fracture against the rendered image evidence."""

    def evaluate(self, rendered, target_image_track, annotation):
        try:
            gray = self._target_gray_image(rendered, target_image_track)
            evidence, valid_cols = self.build_evidence(gray)
            result = self.score_annotation(evidence, valid_cols, annotation, rendered["metadata"])
            result["available"] = True
            return result
        except Exception as exc:
            return {
                "available": False,
                "complete": None,
                "reason": str(exc),
            }

    @staticmethod
    def build_evidence(gray):
        image = np.asarray(gray, dtype=np.float64)
        if image.ndim != 2 or min(image.shape) < 8:
            raise ValueError("Target image data area is too small for completeness scoring")

        white_ratio = (image > 245.0).mean(axis=0)
        col_std = image.std(axis=0)
        valid_cols = (white_ratio < 0.25) & (col_std > 15.0)
        valid_cols[:3] = False
        valid_cols[-3:] = False
        if int(valid_cols.sum()) < 20:
            raise ValueError("Target image has fewer than 20 valid evidence columns")

        masked = np.where(valid_cols[None, :], image, np.nan)
        row_median = np.nanmedian(masked, axis=1)
        residual = image - row_median[:, None]
        row_mad = np.nanmedian(
            np.where(valid_cols[None, :], np.abs(residual), np.nan),
            axis=1,
        ) + 5.0
        normalized = residual / row_mad[:, None]
        evidence = np.abs(gaussian_filter(normalized, sigma=(1.0, 0.7)))
        evidence[:, ~valid_cols] = 0.0
        return evidence, valid_cols

    @staticmethod
    def score_annotation(evidence, valid_cols, annotation, metadata):
        height, width = evidence.shape
        x = np.flatnonzero(valid_cols)
        depth_start = float(metadata["depth_start"])
        depth_end = float(metadata["depth_end"])
        depth_span = depth_end - depth_start
        if depth_span <= 0:
            raise ValueError("Rendered depth range is invalid")

        azimuth = x.astype(float) * 360.0 / max(width - 1, 1)
        radians = np.deg2rad(azimuth)
        depth = (
            float(annotation.get("offset", 0.0))
            + float(annotation.get("sin_coeff", 0.0)) * np.sin(radians)
            + float(annotation.get("cos_coeff", 0.0)) * np.cos(radians)
        )
        y = (depth - depth_start) / depth_span * max(height - 1, 1)
        yi = np.rint(y).astype(int)
        inside = (yi >= 1) & (yi < height - 1)
        x = x[inside]
        yi = yi[inside]
        if x.size < 20:
            return {
                "score": 0.0,
                "coverage": 0.0,
                "min_quadrant_coverage": 0.0,
                "quadrant_coverage": [0.0, 0.0, 0.0, 0.0],
                "valid_column_count": int(x.size),
                "complete": False,
                "reason": "insufficient_curve_columns_inside_image",
            }

        values = np.maximum.reduce([
            evidence[yi - 1, x],
            evidence[yi, x],
            evidence[yi + 1, x],
        ])
        values = np.clip(values, 0.0, 4.0)
        coverage = float((values > 1.0).mean())
        quadrants = np.minimum((4 * x / max(width - 1, 1)).astype(int), 3)
        quadrant_coverage = []
        quadrant_valid_counts = []
        for quadrant in range(4):
            quadrant_values = values[quadrants == quadrant]
            quadrant_valid_counts.append(int(quadrant_values.size))
            quadrant_coverage.append(
                float((quadrant_values > 0.8).mean()) if quadrant_values.size else 0.0
            )
        minimum_supported_columns = max(3, int(round(width * 0.02)))
        supported_quadrants = [
            value for value, count in zip(quadrant_coverage, quadrant_valid_counts)
            if count >= minimum_supported_columns
        ]
        min_quadrant = min(supported_quadrants) if supported_quadrants else 0.0
        score = float(values.mean() + 0.7 * coverage + 0.7 * min_quadrant)
        complete = bool(
            score >= MIN_SCORE
            and coverage >= MIN_COVERAGE
            and min_quadrant >= MIN_QUADRANT_COVERAGE
        )
        failed = []
        if score < MIN_SCORE:
            failed.append("score")
        if coverage < MIN_COVERAGE:
            failed.append("coverage")
        if min_quadrant < MIN_QUADRANT_COVERAGE:
            failed.append("quadrant_coverage")
        return {
            "score": score,
            "coverage": coverage,
            "min_quadrant_coverage": min_quadrant,
            "quadrant_coverage": quadrant_coverage,
            "quadrant_valid_column_count": quadrant_valid_counts,
            "supported_quadrant_count": len(supported_quadrants),
            "valid_column_count": int(x.size),
            "thresholds": {
                "score": MIN_SCORE,
                "coverage": MIN_COVERAGE,
                "min_quadrant_coverage": MIN_QUADRANT_COVERAGE,
            },
            "complete": complete,
            "reason": None if complete else "below_" + "_and_".join(failed),
        }

    @staticmethod
    def _target_gray_image(rendered, target_image_track):
        data_url = str(rendered.get("data_url") or "")
        if "," not in data_url:
            raise ValueError("Rendered analysis image is unavailable")
        image = QImage.fromData(base64.b64decode(data_url.split(",", 1)[1]), "PNG")
        if image.isNull():
            raise ValueError("Rendered analysis image cannot be decoded")

        metadata = rendered.get("metadata") or {}
        target = next(
            (
                track for track in metadata.get("tracks", [])
                if target_image_track in (track.get("name"), track.get("label"))
            ),
            None,
        )
        if target is None:
            raise ValueError("Target image track bounds are unavailable")
        left = max(0, int(round(float(target["pixel_left"]))))
        right = min(image.width(), int(round(float(target["pixel_right"]))))
        top = max(0, int(round(float(metadata.get("plot_top", 0)))))
        bottom = min(image.height(), int(round(float(metadata.get("plot_bottom", image.height())))))
        if right <= left or bottom <= top:
            raise ValueError("Target image data bounds are invalid")

        gray = image.copy(left, top, right - left, bottom - top).convertToFormat(QImage.Format_Grayscale8)
        raw = bytes(gray.constBits())
        rows = np.frombuffer(raw, dtype=np.uint8).reshape(gray.height(), gray.bytesPerLine())
        return rows[:, : gray.width()].copy()
