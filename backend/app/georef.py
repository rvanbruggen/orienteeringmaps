"""Fitting a page image onto the world from matched control points.

Image pixels (x right, y down) are mapped to Web Mercator metres (EPSG:3857)
with a 3x3 matrix H, so that [X, Y, W] = H @ [x, y, 1] and X/W, Y/W are the
Mercator coordinates. Over the few kilometres an orienteering map covers,
Mercator is locally conformal, so a similarity or affine fit in Mercator is
as good as one in a local projection — distances just need the cos(lat)
scale factor.

Methods:
  similarity  2+ points: shift, rotation, uniform scale (true-to-scale prints)
  affine      3+ points: also absorbs shear and unequal x/y scale (scans, prints)
  projective  4+ points: perspective, for photos of a paper map taken at an angle
  auto        similarity for 2 points, affine for 3 or more
"""
import math
from dataclasses import dataclass

import numpy as np

R = 6378137.0
MIN_POINTS = {"similarity": 2, "affine": 3, "projective": 4}
METHODS = ("auto", "similarity", "affine", "projective")


class FitError(ValueError):
    pass


def to_merc(lat: float, lon: float) -> tuple[float, float]:
    lat = max(min(lat, 85.0511), -85.0511)
    return R * math.radians(lon), R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def from_merc(x: float, y: float) -> tuple[float, float]:
    return math.degrees(2 * math.atan(math.exp(y / R)) - math.pi / 2), math.degrees(x / R)


def _apply(h: np.ndarray, x: float, y: float) -> tuple[float, float]:
    v = h @ np.array([x, y, 1.0])
    return v[0] / v[2], v[1] / v[2]


def _fit_similarity(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    # Image y points down and Mercator Y up, so mirror y first; then
    # X = a*x' - b*y' + tx, Y = b*x' + a*y' + ty with y' = -y.
    rows, rhs = [], []
    for (x, y), (X, Y) in zip(src, dst):
        yp = -y
        rows.append([x, -yp, 1, 0]); rhs.append(X)
        rows.append([yp, x, 0, 1]); rhs.append(Y)
    a, b, tx, ty = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)[0]
    # Substitute y' = -y back into matrix form.
    return np.array([[a, b, tx], [b, -a, ty], [0, 0, 1.0]])


def _fit_affine(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    A = np.column_stack([src, np.ones(len(src))])
    sol = np.linalg.lstsq(A, dst, rcond=None)[0]  # 3x2
    return np.vstack([sol.T, [0, 0, 1.0]])


def _normalizer(pts: np.ndarray) -> np.ndarray:
    c = pts.mean(axis=0)
    d = np.sqrt(((pts - c) ** 2).sum(axis=1)).mean() or 1.0
    s = math.sqrt(2) / d
    return np.array([[s, 0, -s * c[0]], [0, s, -s * c[1]], [0, 0, 1.0]])


def _fit_projective(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    # Normalised direct linear transform (Hartley & Zisserman).
    ts, td = _normalizer(src), _normalizer(dst)
    s = (ts @ np.column_stack([src, np.ones(len(src))]).T).T
    d = (td @ np.column_stack([dst, np.ones(len(dst))]).T).T
    rows = []
    for (x, y, _), (X, Y, _) in zip(s, d):
        rows.append([-x, -y, -1, 0, 0, 0, X * x, X * y, X])
        rows.append([0, 0, 0, -x, -y, -1, Y * x, Y * y, Y])
    _, _, vt = np.linalg.svd(np.array(rows))
    h = vt[-1].reshape(3, 3)
    h = np.linalg.inv(td) @ h @ ts
    return h / h[2, 2]


@dataclass
class Fit:
    method: str
    matrix: list[list[float]]
    corners: list[list[float]]  # [lat, lon] of image TL, TR, BR, BL
    center: list[float]  # [lat, lon] of the image centre
    residuals_m: list[float]
    rms_m: float | None  # None when the fit is exactly determined
    metres_per_px: float
    scale: float | None  # implied print scale (needs DPI)
    rotation_deg: float  # how far image "up" is rotated clockwise from grid north

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def fit(points: list[dict], width: int, height: int, method: str = "auto", dpi: float | None = None) -> Fit:
    """points: [{x, y, lat, lon}] with x, y in image pixels."""
    if method not in METHODS:
        raise FitError(f"Unknown method {method!r}")
    n = len(points)
    if method == "auto":
        method = "similarity" if n < 3 else "affine"
    if n < MIN_POINTS[method]:
        raise FitError(f"{method} needs at least {MIN_POINTS[method]} points ({n} given)")

    src = np.array([[p["x"], p["y"]] for p in points], dtype=float)
    dst = np.array([to_merc(p["lat"], p["lon"]) for p in points], dtype=float)
    if np.ptp(src, axis=0).max() < 1 or np.ptp(dst, axis=0).max() < 0.01:
        raise FitError("Control points are all in the same place")

    h = {"similarity": _fit_similarity, "affine": _fit_affine, "projective": _fit_projective}[method](src, dst)
    if not np.all(np.isfinite(h)):
        raise FitError("Could not fit these points")

    mean_lat = float(np.mean([p["lat"] for p in points]))
    k = math.cos(math.radians(mean_lat))  # Mercator metres -> ground metres
    residuals = []
    for (x, y), (X, Y) in zip(src, dst):
        px, py = _apply(h, x, y)
        residuals.append(round(math.hypot(px - X, py - Y) * k, 2))
    dof = n - MIN_POINTS[method]
    rms = round(math.sqrt(sum(r * r for r in residuals) / n), 2) if dof > 0 else None

    # Local Jacobian at the image centre: ground metres per pixel and rotation.
    cx, cy = width / 2, height / 2
    p0, px1, py1 = _apply(h, cx, cy), _apply(h, cx + 1, cy), _apply(h, cx, cy + 1)
    jx = (px1[0] - p0[0], px1[1] - p0[1])
    jy = (py1[0] - p0[0], py1[1] - p0[1])
    det = abs(jx[0] * jy[1] - jx[1] * jy[0])
    if det < 1e-12:
        raise FitError("Degenerate fit (points on one line?)")
    m_per_px = math.sqrt(det) * k
    # Image "up" is -jy; angle clockwise from north.
    rotation = math.degrees(math.atan2(-jy[0], -jy[1]))
    scale = round(m_per_px / (0.0254 / dpi)) if dpi else None

    corners = [list(from_merc(*_apply(h, x, y))) for x, y in ((0, 0), (width, 0), (width, height), (0, height))]
    return Fit(
        method=method, matrix=h.tolist(), corners=corners, center=list(from_merc(*p0)),
        residuals_m=residuals, rms_m=rms, metres_per_px=round(m_per_px, 4), scale=scale,
        rotation_deg=round(rotation, 2),
    )
