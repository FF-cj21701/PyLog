import math

import numpy as np

from scripts.rendering.fracture_annotations import (
    FRACTURE_TYPE_STYLES,
    MIN_FRACTURE_PREVIEW_POINTS,
    MIN_FRACTURE_PICK_POINTS,
    build_fracture_annotation,
    sinusoidal_fracture_xy,
)


def test_sinusoidal_fracture_fit_recovers_fixed_period_trace():
    points = []
    for azimuth in (0, 45, 90, 180, 270, 360):
        depth = 7567.0 + 0.18 * math.sin(math.radians(azimuth)) - 0.07 * math.cos(math.radians(azimuth))
        points.append([azimuth, depth])

    annotation = build_fracture_annotation(points)

    assert annotation["type"] == "sinusoidal_fracture"
    assert annotation["offset"] == pytest_approx(7567.0)
    assert annotation["sin_coeff"] == pytest_approx(0.18)
    assert annotation["cos_coeff"] == pytest_approx(-0.07)

    x, y = sinusoidal_fracture_xy(annotation, samples=37)
    assert np.nanmin(x) == pytest_approx(0.0)
    assert np.nanmax(x) == pytest_approx(360.0)
    assert np.nanmax(y) - np.nanmin(y) > 0.3


def test_fracture_annotation_keeps_type_and_color():
    annotation = build_fracture_annotation(
        [[0, 1000.0], [90, 1000.1], [180, 1000.2]],
        fracture_type="Resistive",
        color=FRACTURE_TYPE_STYLES["Resistive"]["color"],
    )

    assert annotation["fracture_type"] == "Resistive"
    assert annotation["color"] == "#FF2D2D"


def test_fracture_fit_rejects_incomplete_two_point_pick():
    import pytest

    with pytest.raises(ValueError, match="At least 3"):
        build_fracture_annotation([[0, 1000.0], [180, 1000.2]])

    assert MIN_FRACTURE_PICK_POINTS == 3


def test_fracture_preview_can_fit_two_points():
    annotation = build_fracture_annotation(
        [[0, 1000.0], [180, 1000.2]],
        name="Preview",
        min_points=MIN_FRACTURE_PREVIEW_POINTS,
    )

    x, y = sinusoidal_fracture_xy(annotation, samples=19)

    assert annotation["name"] == "Preview"
    assert len(x) == 19
    assert len(y) == 19


def pytest_approx(value):
    import pytest

    return pytest.approx(value, abs=1e-9)
