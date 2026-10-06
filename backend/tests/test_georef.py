import math

import numpy as np
import pytest

from app.georef import FitError, fit, from_merc, to_merc

DPI = 250
SCALE = 5000
M_PER_PX = SCALE * 0.0254 / DPI  # ground metres per pixel at 1:5000, 250 dpi


def synth(points_px, rotation_deg=8.0, origin=(50.8759, 4.7037), shear=0.0, persp=0.0):
    """Ground truth: image rotated clockwise by rotation_deg relative to grid north."""
    lat0, lon0 = origin
    X0, Y0 = to_merc(lat0, lon0)
    k = 1 / math.cos(math.radians(lat0))
    th = math.radians(rotation_deg)
    out = []
    for x, y in points_px:
        x2 = x + shear * y
        w = 1 + persp * y
        e = (x2 * math.cos(th) + y * math.sin(th)) * M_PER_PX / w  # east
        n = (x2 * math.sin(th) - y * math.cos(th)) * M_PER_PX / w  # north (image y is down)
        lat, lon = from_merc(X0 + e * k, Y0 + n * k)
        out.append({"x": x, "y": y, "lat": lat, "lon": lon})
    return out


PX = [(100, 120), (1800, 200), (1700, 2500), (150, 2600), (900, 1300), (1200, 700)]


def test_similarity_two_points_recovers_scale_and_rotation():
    pts = synth(PX[:2])
    f = fit(pts, 2000, 2800, dpi=DPI)
    assert f.method == "similarity"
    assert f.rms_m is None  # exactly determined
    assert abs(f.scale - SCALE) <= 5
    assert f.rotation_deg == pytest.approx(-8.0, abs=0.05)


def test_rotation_sign_is_clockwise_positive():
    f = fit(synth(PX[:3], rotation_deg=10), 2000, 2800, dpi=DPI)
    # Image x axis rotated counter-clockwise by 10 deg -> image "up" points 10 deg west of north.
    assert f.rotation_deg == pytest.approx(-10, abs=0.05)


def test_affine_residuals_and_noise():
    pts = synth(PX, shear=0.01)
    f = fit(pts, 2000, 2800, dpi=DPI)
    assert f.method == "affine"
    assert f.rms_m < 0.05
    pts[4]["lat"] += 20 / 111_320  # move one point 20 m north
    f2 = fit(pts, 2000, 2800, dpi=DPI)
    assert max(f2.residuals_m) == f2.residuals_m[4]
    assert f2.rms_m > 3


def test_projective_handles_perspective():
    pts = synth(PX, persp=0.0002)
    assert fit(pts, 2000, 2800, method="affine").rms_m > 5
    f = fit(pts, 2000, 2800, method="projective")
    assert f.rms_m < 0.05
    assert len(f.corners) == 4


def test_errors():
    with pytest.raises(FitError):
        fit(synth(PX[:1]), 2000, 2800)
    with pytest.raises(FitError):
        fit(synth(PX[:3]), 2000, 2800, method="projective")
    same = synth([(10, 10), (10, 10)])
    with pytest.raises(FitError):
        fit(same, 2000, 2800)
