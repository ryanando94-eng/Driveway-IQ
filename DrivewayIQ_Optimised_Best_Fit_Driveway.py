"""
Driveway Platform Level Calculator
Drafting-style schematic graph (similar to sample image)

UPDATE (per request)
- RL values are ALWAYS placed above the dashed vertical guide line (same X as guide),
  NOT above the point on the red profile line.
- Graph auto-fits inside the viewport (no text/linework can disappear off the sides).

Other retained behaviours:
- White graph background
- Garage slab = solid blue fill box
- Last RL point touches slab top-left corner
- Platform line = thin dashed grey (extends under slab)
- No tolerance line drawn
- RL text has no white boxes and no leader arrows

Run: paste into Python IDLE and press F5
"""

from __future__ import annotations

# ------------------------------------------------------------
# Bootstrap: capture "instant crash on open" errors to a log file
# ------------------------------------------------------------
import os
import sys
import traceback

def _write_startup_error(err_text: str) -> None:
    try:
        base = os.path.dirname(os.path.abspath(__file__))
    except Exception:
        base = os.getcwd()
    path = os.path.join(base, "driveway_platform_startup_error.log")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(err_text)
    except Exception:
        pass

try:
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import ttk, messagebox, filedialog, filedialog
except Exception:
    _write_startup_error(traceback.format_exc())
    raise


# =============================
# EARLY CRASH LOGGING (module-level exceptions)
# =============================
def _write_early_crash_log() -> None:
    try:
        base = os.path.dirname(os.path.abspath(__file__))
    except Exception:
        base = os.getcwd()
    path = os.path.join(base, "driveway_platform_runtime_crash.log")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n\n--- Unhandled exception ---\n")
            f.write(traceback.format_exc())
    except Exception:
        pass

def _excepthook(exctype, value, tb):
    try:
        # write same runtime crash log for early failures
        base = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
        path = os.path.join(base, "driveway_platform_runtime_crash.log")
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n\n--- Unhandled exception (sys.excepthook) ---\n")
            f.write(''.join(traceback.format_exception(exctype, value, tb)))
    except Exception:
        pass
    # also print to stderr as normal
    sys.__excepthook__(exctype, value, tb)

sys.excepthook = _excepthook

from dataclasses import dataclass
import math
import random
import json

# Optional: DXF export (install with: py -m pip install ezdxf)
try:
    import ezdxf  # type: ignore
except Exception:
    ezdxf = None

# =============================
# STARTUP CRASH LOGGING
# =============================
import traceback as _traceback
import os as _os

def _write_crash_log():
    try:
        log_path = _os.path.join(_os.path.dirname(__file__), "startup_crash.log")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("Driveway Platform UI crash log\n\n")
            f.write(_traceback.format_exc())
    except Exception:
        pass
def _write_runtime_crash_log(err_text: str) -> str:
    """Write a runtime crash log (uncaught exceptions from UI callbacks etc.)."""
    try:
        base = _os.path.dirname(_os.path.abspath(__file__))
    except Exception:
        base = _os.getcwd()
    log_path = _os.path.join(base, "driveway_platform_runtime_crash.log")
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n" + "=" * 72 + "\n")
            f.write(f"Timestamp: {__import__('datetime').datetime.now().isoformat()}\n")
            f.write(err_text.strip() + "\n")
    except Exception:
        pass
    return log_path


def _install_global_crash_hooks() -> None:
    """Install sys.excepthook so any uncaught exceptions are logged."""
    def _hook(exc_type, exc, tb):
        err_text = "".join(_traceback.format_exception(exc_type, exc, tb))
        _write_runtime_crash_log(err_text)
        # fall back to default printing as well
        try:
            sys.__excepthook__(exc_type, exc, tb)
        except Exception:
            pass

    try:
        sys.excepthook = _hook
    except Exception:
        pass

# =============================
# RULES / CONSTANTS
# =============================
# UPSLOPE zones
UP_A_LEN, UP_A_RATIO = 1.0, 6.0
UP_TOP_LEN, UP_TOP_RATIO = 1.5, 8.0
UP_MID_RATIO_MAX = 4.0

# DOWNSLOPE zones
DN_A_LEN, DN_A_RATIO = 1.0, 20.0
DN_B_LEN, DN_B_RATIO = 1.0, 6.0
DN_MID_RATIO_MAX = 4.0
DN_D_LEN, DN_D_RATIO = 1.5, 8.0
DN_E_LEN, DN_E_RATIO = 1.0, 20.0  # UP

TOLERANCE_M = 0.000  # 100mm (still calculated; not drawn)

# Downslope strip drain (fixed length, flat)
DRAIN_LEN_M = 0.100  # 100mm
STEP_TO_SLAB_M = 0.035  # default rebate (m): garage slab is higher than the last RL point

SLAB_OPTIONS = {
    "310 mm — S / M Class slab": 310,
    "385 mm — H1 / H2 Class slab": 385,
    "460 mm — E Class slab": 460,
    "610 mm — E Class slab (thickened)": 610,
}

WHITE = "#111821"
# Technical/drafting palette (dark CAD workstation style)
INK = "#e7edf6"
LIGHT_INK = "#aab4c0"
GUIDE = "#687789"
ACCENT = "#39bdf2"  # technical cyan/blue for key labels
GRID_MINOR = "#1e2a36"
GRID_MAJOR = "#2b3948"


# =============================
# DATA MODEL
# =============================
@dataclass
class Segment:
    name: str
    length_m: float
    ratio: float      # 1:ratio
    sign: int         # +1 UP, -1 DOWN

    @property
    def grade_pct(self) -> float:
        if self.sign == 0 or self.ratio <= 0:
            return 0.0
        return (1.0 / self.ratio) * 100.0

    def delta_rl(self) -> float:
        if self.sign == 0 or self.ratio <= 0:
            return 0.0
        return (self.length_m / self.ratio) * self.sign


def fmt(v: float, nd: int = 3) -> str:
    return f"{v:.{nd}f}"


def fmt_mm(length_m: float) -> str:
    mm = int(round(length_m * 1000))
    return f"{mm:,}"


# =============================
# SEGMENT BUILDERS
# =============================
def build_segments_upslope(total_len: float) -> list[Segment]:
    if total_len <= 0:
        raise ValueError("Driveway length must be > 0.")

    segs: list[Segment] = []
    a_len = min(UP_A_LEN, total_len)
    segs.append(Segment("Zone A (UP)", a_len, UP_A_RATIO, +1))
    remaining = total_len - a_len
    if remaining <= 0:
        return segs

    if total_len >= (UP_A_LEN + UP_TOP_LEN):
        mid_len = total_len - UP_A_LEN - UP_TOP_LEN
        if mid_len > 0:
            segs.append(Segment("Zone B (UP)", mid_len, UP_MID_RATIO_MAX, +1))
        segs.append(Segment("Zone C (UP)", UP_TOP_LEN, UP_TOP_RATIO, +1))
    else:
        segs.append(Segment("Zone C (UP, shortened)", remaining, UP_TOP_RATIO, +1))

    return segs


def build_segments_downslope(total_len: float) -> list[Segment]:
    if total_len <= 0:
        raise ValueError("Driveway length must be > 0.")

    # Fixed drain immediately after Zone D (1:8) for downslope
    DRAIN_LEN_M = 0.100  # 100mm
    DRAIN_RATIO = 1.0    # displayed as FLAT elsewhere; no RL change because sign=0

    segs: list[Segment] = []
    remaining = total_len

    # Zone A (DOWN) up to 1.0m
    a_len = min(DN_A_LEN, remaining)
    segs.append(Segment("Zone A (DOWN)", a_len, DN_A_RATIO, -1))
    remaining -= a_len
    if remaining <= 0:
        return segs

    # Zone B (DOWN) up to 1.0m
    b_len = min(DN_B_LEN, remaining)
    segs.append(Segment("Zone B (DOWN)", b_len, DN_B_RATIO, -1))
    remaining -= b_len
    if remaining <= 0:
        return segs

    # From here, we always want:
    #   Zone D (DOWN) = up to 1.5m (may shorten if overall is short)
    #   DRAIN (FLAT)  = 0.1m fixed
    #   Zone E (UP)   = 1.0m fixed (per request: must remain 1000mm)
    tail_min = DRAIN_LEN_M + DN_E_LEN

    if remaining < tail_min - 1e-9:
        # Not enough length to even place the fixed drain + fixed Zone E
        raise ValueError("Driveway length is too short to fit the required 100mm drain + 1000mm Zone E.")

    # Prefer the standard layout:
    #   Zone C (DOWN, varies) + Zone D (DOWN, 1.5m) + DRAIN (FLAT, 0.1m) + Zone E (UP, 1.0m)
    # If we don't have enough for full Zone D, shorten Zone D (NOT Zone E, NOT drain).
    full_tail = DN_D_LEN + DRAIN_LEN_M + DN_E_LEN

    if remaining >= full_tail - 1e-9:
        # We can fit full Zone D and full Zone E and drain
        mid_len = remaining - full_tail
        if mid_len > 1e-9:
            segs.append(Segment("Zone C (DOWN)", mid_len, DN_MID_RATIO_MAX, -1))
        segs.append(Segment("Zone D (DOWN)", DN_D_LEN, DN_D_RATIO, -1))
        segs.append(Segment("DRAIN", DRAIN_LEN_M, DRAIN_RATIO, 0))
        segs.append(Segment("Zone E (UP)", DN_E_LEN, DN_E_RATIO, +1))
        return segs

    # Otherwise, no Zone C; shorten Zone D to make room for fixed drain + fixed Zone E
    d_len = max(0.0, remaining - (DRAIN_LEN_M + DN_E_LEN))
    if d_len > 1e-9:
        segs.append(Segment("Zone D (DOWN, shortened)", d_len, DN_D_RATIO, -1))
    else:
        # If d_len is 0, we still proceed with drain + Zone E
        pass
    segs.append(Segment("DRAIN", DRAIN_LEN_M, DRAIN_RATIO, 0))
    segs.append(Segment("Zone E (UP)", DN_E_LEN, DN_E_RATIO, +1))
    return segs


def build_segments(total_len: float, direction: str) -> list[Segment]:
    if direction == "Up from boundary":
        return build_segments_upslope(total_len)
    if direction == "Down from boundary":
        return build_segments_downslope(total_len)
    raise ValueError("Direction must be 'Up from boundary' or 'Down from boundary'.")


# =============================
# CALCULATION ENGINE (PROFILE POINTS)
# =============================
def compute(boundary_rl: float, total_len: float, direction: str, slab_mm: int, tolerance_m: float = TOLERANCE_M, rebate_m: float = STEP_TO_SLAB_M):
    segments = build_segments(total_len, direction)

    station = 0.0
    rl = boundary_rl
    points = [(station, rl)]  # (station_m, rl_m)

    total_delta = 0.0
    for seg in segments:
        d = seg.delta_rl()
        total_delta += d
        station += seg.length_m
        rl += d
        points.append((station, rl))

    tos_rl = rl
    slab_m = slab_mm / 1000.0

    # Apply 35mm step down from the final RL point to the garage slab top
    slab_step_rl = tos_rl + rebate_m

    # Platform is measured from the *slab top* down by the chosen slab thickness
    platform_rl = round(slab_step_rl - slab_m, 2)  # rounded to nearest 0.01m

    # Directional 100mm tolerance applied to GRAPHED levels:
    # - Up from boundary: end RL shifts DOWN by 0.100m
    # - Down from boundary: end RL shifts UP by 0.100m
    if "Up" in direction:
        tol_delta = -tolerance_m
        maxmin = "MAX"
    elif "Down" in direction:
        tol_delta = tolerance_m
        maxmin = "MIN"
    else:
        tol_delta = 0.0
        maxmin = "MAX"

    # Ratio-scale intermediate RLs so boundary stays fixed and end RL reflects tolerance
    total_delta = tos_rl - boundary_rl
    if abs(total_delta) < 1e-9:
        ratio = 1.0
    else:
        ratio = (total_delta + tol_delta) / total_delta

    points_graph = [(st, boundary_rl + (r - boundary_rl) * ratio) for (st, r) in points]

    # Update end RLs based on graphed profile
    tos_rl = points_graph[-1][1]

    # Apply 35mm step down from the final RL point to the garage slab top
    slab_step_rl = tos_rl + rebate_m

    # Platform is measured from the *slab top* down by the chosen slab thickness
    platform_rl = round(slab_step_rl - slab_m, 2)  # rounded to nearest 0.01m
    return {
        "tos_rl": tos_rl,
        "slab_step_rl": slab_step_rl,
        "platform_rl": platform_rl,
                "maxmin": maxmin,
        "total_delta": total_delta,
        "segments": segments,
        "points": points_graph,
        "slab_mm": slab_mm,
        "slab_m": slab_m,
        "direction": direction,
    }



def compute_custom(boundary_rl: float, direction: str, slab_mm: int, segments, tolerance_m: float = TOLERANCE_M, rebate_m: float = STEP_TO_SLAB_M):
    """
    Compute using user-specified segments (length + gradient), matching compute() return shape.
    segments: list[Segment]
    """
    station = 0.0
    rl = boundary_rl
    points = [(station, rl)]

    total_delta = 0.0
    for seg in segments:
        d = seg.delta_rl()
        total_delta += d
        station += seg.length_m
        rl += d
        points.append((station, rl))

    tos_rl = rl
    slab_m = slab_mm / 1000.0

    # Apply step down from final RL point to slab top, then slab thickness to platform
    slab_step_rl = tos_rl + rebate_m
    platform_rl = round(slab_step_rl - slab_m, 2)

    # Optional tolerance scaling (used by tolerance tab; custom tab is "true" by default)
    if "Up" in direction:
        tol_delta = -tolerance_m
        maxmin = "MAX"
    elif "Down" in direction:
        tol_delta = tolerance_m
        maxmin = "MIN"
    else:
        tol_delta = 0.0
        maxmin = "MAX"

    total_delta = tos_rl - boundary_rl
    if abs(total_delta) < 1e-9:
        ratio = 1.0
    else:
        ratio = (total_delta + tol_delta) / total_delta

    points_graph = [(st, boundary_rl + (r - boundary_rl) * ratio) for (st, r) in points]

    # Update end RLs based on graphed profile
    tos_rl = points_graph[-1][1]
    slab_step_rl = tos_rl + rebate_m
    platform_rl = round(slab_step_rl - slab_m, 2)

    return {
        "tos_rl": tos_rl,
        "slab_step_rl": slab_step_rl,
        "platform_rl": platform_rl,
        "maxmin": maxmin,
        "total_delta": total_delta,
        "segments": segments,
        "points": points_graph,
        "slab_mm": slab_mm,
        "slab_m": slab_m,
        "direction": direction,
    }


# =============================
# AUTO BEST-FIT PROFILE ENGINE
# =============================
def compute_best_fit(
    boundary_rl: float,
    total_len: float,
    target_rl: float,
    target_rl_type: str,
    slab_mm: int,
    rebate_m: float,
    boundary_grade_len: float,
    garage_grade_len: float,
    transition_count: int,
    direction: str,
):
    """Generate a vehicle-friendly driveway using constrained optimisation.

    The solver does not copy a fixed template. It finds the smoothest grade
    sequence that exactly connects the entered boundary RL to the selected
    target RL while enforcing:
      * boundary-end grade <= 1:8;
      * garage-end grade <= 1:8 and always rising toward the garage
        (therefore falling away from the garage);
      * intermediate grades <= 1:4; and
      * adjacent grade change <= 1:8.

    Smoothness is assessed from both adjacent grade changes and changes in the
    rate of grade change. This avoids the artificial sine-profile behaviour and
    reduces unnecessary crests, sags and alternating grades.
    """
    if total_len <= 0:
        raise ValueError("Driveway length must be greater than 0 m.")
    if boundary_grade_len <= 0:
        raise ValueError("Boundary end-profile length must be greater than 0 m.")
    if garage_grade_len <= 0:
        raise ValueError("Garage end-profile length must be greater than 0 m.")
    if boundary_grade_len + garage_grade_len >= total_len:
        raise ValueError("Boundary and garage end-profile lengths must leave room for the transition profiles.")

    transition_count = int(transition_count)
    if transition_count < 1 or transition_count > 20:
        raise ValueError("Transition changes must be between 1 and 20.")

    slab_m = slab_mm / 1000.0
    if target_rl_type == "Garage Slab RL":
        slab_step_rl = target_rl
        platform_rl = slab_step_rl - slab_m
        target_tos = slab_step_rl - rebate_m
    else:
        platform_rl = target_rl
        target_tos = platform_rl + slab_m - rebate_m
        slab_step_rl = target_tos + rebate_m

    middle_len = total_len - boundary_grade_len - garage_grade_len
    middle_zone_len = middle_len / transition_count
    lengths = [boundary_grade_len] + [middle_zone_len] * transition_count + [garage_grade_len]
    names = ["Boundary end profile"] + [f"Transition {i + 1}" for i in range(transition_count)] + ["Garage end profile"]
    n = len(lengths)
    target_delta = target_tos - boundary_rl

    end_limit = 1.0 / 8.0
    middle_limit = 1.0 / 4.0
    adjacent_limit = 1.0 / 8.0
    min_garage_grade = 1.0e-6

    def make_result(grades, failed=False, reason=""):
        points = [(0.0, boundary_rl)]
        segments: list[Segment] = []
        rl = boundary_rl
        station = 0.0
        for name, seg_len, grade in zip(names, lengths, grades):
            station += seg_len
            rl += seg_len * grade
            points.append((station, rl))
            sign = 0 if abs(grade) < 1e-10 else (1 if grade > 0 else -1)
            ratio = 1.0 if sign == 0 else 1.0 / abs(grade)
            segments.append(Segment(name, seg_len, ratio, sign))
        points[-1] = (total_len, target_tos)
        changes = [abs(grades[i + 1] - grades[i]) for i in range(len(grades) - 1)]
        return {
            "tos_rl": target_tos, "slab_step_rl": slab_step_rl, "platform_rl": platform_rl,
            "maxmin": "FAIL" if failed else "OPTIMISED", "total_delta": target_delta,
            "segments": segments, "points": points, "slab_mm": slab_mm, "slab_m": slab_m,
            "direction": direction, "auto_best_fit": True,
            "best_fit_failed": failed, "best_fit_fail_reason": reason,
            "best_fit_start_grade": grades[0], "best_fit_end_grade": grades[-1],
            "best_fit_peak_grade": max(abs(g) for g in grades),
            "best_fit_max_grade_change": max(changes) if changes else 0.0,
            "best_fit_transition_count": transition_count,
            "best_fit_boundary_len": boundary_grade_len,
            "best_fit_garage_len": garage_grade_len,
            "best_fit_solver": "constrained optimisation",
        }

    avg_grade = target_delta / total_len

    try:
        import numpy as np
        from scipy.optimize import minimize

        L = np.asarray(lengths, dtype=float)
        bounds = [(-end_limit, end_limit)] + [(-middle_limit, middle_limit)] * transition_count + [(min_garage_grade, end_limit)]

        # Start from the average grade, then force a valid positive garage-end
        # grade. The equality constraint will redistribute the remaining level.
        x0 = np.full(n, max(-middle_limit, min(middle_limit, avg_grade)), dtype=float)
        x0[0] = max(-end_limit, min(end_limit, avg_grade))
        x0[-1] = max(min_garage_grade, min(end_limit, max(avg_grade, end_limit * 0.20)))

        # Correct the initial elevation error across the middle zones first.
        err = target_delta - float(np.dot(L, x0))
        middle_total = float(sum(lengths[1:-1]))
        if middle_total > 1e-9:
            x0[1:-1] += err / middle_total
        x0 = np.asarray([max(lo, min(hi, v)) for v, (lo, hi) in zip(x0, bounds)], dtype=float)

        def objective(g):
            dg = np.diff(g)
            ddg = np.diff(g, n=2) if len(g) >= 3 else np.asarray([], dtype=float)

            # Primary objective: small adjacent grade changes.
            smooth_1 = 1200.0 * float(np.dot(dg, dg))
            # Secondary objective: grade changes should themselves vary smoothly.
            smooth_2 = 600.0 * float(np.dot(ddg, ddg)) if len(ddg) else 0.0
            # Avoid unnecessarily steep profiles and soften both ends on flat sites.
            grade_energy = 5.0 * float(np.dot(g, g))
            end_softness = 18.0 * float(g[0] ** 2 + g[-1] ** 2)

            # Penalise repeated reversals that create unnecessary humps/sags.
            reversal = 0.0
            for a, b in zip(g[:-1], g[1:]):
                if a * b < 0.0:
                    reversal += min(abs(a), abs(b)) ** 2
            return smooth_1 + smooth_2 + grade_energy + end_softness + 150.0 * reversal

        constraints = [
            {"type": "eq", "fun": lambda g: float(np.dot(L, g) - target_delta)},
        ]
        for i in range(n - 1):
            constraints.append({"type": "ineq", "fun": lambda g, i=i: adjacent_limit - (g[i + 1] - g[i])})
            constraints.append({"type": "ineq", "fun": lambda g, i=i: adjacent_limit + (g[i + 1] - g[i])})

        best = None
        # Several deterministic starting shapes improve reliability for difficult
        # upslope/down-slope combinations without changing the final objective.
        starts = [x0]
        linear = np.linspace(max(-end_limit, min(end_limit, avg_grade)), max(min_garage_grade, min(end_limit, max(avg_grade, 0.01))), n)
        starts.append(np.asarray([max(lo, min(hi, v)) for v, (lo, hi) in zip(linear, bounds)]))
        starts.append(np.asarray([0.0] + [max(-middle_limit, min(middle_limit, avg_grade))] * transition_count + [max(min_garage_grade, min(end_limit, 0.02))]))

        for guess in starts:
            result = minimize(
                objective,
                guess,
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={"maxiter": 2000, "ftol": 1e-12, "disp": False},
            )
            if result.success:
                grades = np.asarray(result.x, dtype=float)
                elevation_error = abs(float(np.dot(L, grades) - target_delta))
                max_change = max((abs(float(grades[i + 1] - grades[i])) for i in range(n - 1)), default=0.0)
                if elevation_error <= 1e-7 and max_change <= adjacent_limit + 1e-7:
                    score = objective(grades)
                    if best is None or score < best[0]:
                        best = (score, grades)

        if best is not None:
            return make_result([float(v) for v in best[1]])

    except Exception:
        # The application remains usable if SciPy is unavailable; the failed
        # profile is drawn in red with an explanatory status instead of crashing.
        pass

    fallback_grade = max(-middle_limit, min(middle_limit, avg_grade))
    fallback = [max(-end_limit, min(end_limit, fallback_grade))]
    fallback += [fallback_grade] * transition_count
    fallback += [max(min_garage_grade, min(end_limit, max(fallback_grade, 0.01)))]
    reason = (
        "No profile satisfies all entered constraints. The optimiser must exactly reach the target RL while "
        "keeping the boundary and garage ends at 1:8 maximum, the middle at 1:4 maximum, the garage end "
        "falling away from the garage, and every adjacent grade change at 1:8 maximum. "
        f"Required average grade: {avg_grade * 100.0:+.2f}%. Try increasing driveway length, increasing the number "
        "of transitions, or reducing one or both fixed end-profile lengths."
    )
    return make_result(fallback, failed=True, reason=reason)


# =============================
# CANVAS / SCHEMATIC
# =============================
def _dim_line(canvas: tk.Canvas, x1, y1, x2, y2, color="#111", width=1, ah=8):
    """Drafting-style dimension line with filled triangular arrowheads."""
    canvas.create_line(x1, y1, x2, y2, fill=color, width=width)

    dx, dy = x2 - x1, y2 - y1
    L = math.hypot(dx, dy) or 1.0
    ux, uy = dx / L, dy / L
    px, py = -uy, ux

    def head_at(x, y, dir_sign):
        bx = x + (-dir_sign) * ux * ah
        by = y + (-dir_sign) * uy * ah
        w = ah * 0.55
        p1 = (x, y)
        p2 = (bx + px * w, by + py * w)
        p3 = (bx - px * w, by - py * w)
        canvas.create_polygon(p1, p2, p3, fill=color, outline=color)

    head_at(x1, y1, +1)
    head_at(x2, y2, -1)


def _clip_line_to_rect(x1, y1, x2, y2, rx0, ry0, rx1, ry1):
    """Liang-Barsky line clipping. Returns (x1,y1,x2,y2) or None."""
    p = [-(x2 - x1), (x2 - x1), -(y2 - y1), (y2 - y1)]
    q = [x1 - rx0, rx1 - x1, y1 - ry0, ry1 - y1]
    u1, u2 = 0.0, 1.0
    for pi, qi in zip(p, q):
        if pi == 0:
            if qi < 0:
                return None
        else:
            t = qi / pi
            if pi < 0:
                if t > u2:
                    return None
                if t > u1:
                    u1 = t
            else:
                if t < u1:
                    return None
                if t < u2:
                    u2 = t
    nx1 = x1 + u1 * (x2 - x1)
    ny1 = y1 + u1 * (y2 - y1)
    nx2 = x1 + u2 * (x2 - x1)
    ny2 = y1 + u2 * (y2 - y1)
    return nx1, ny1, nx2, ny2


def _concrete_hatch(canvas: tk.Canvas, x0, y0, x1, y1, density=0.015, color="#666"):
    """Concrete-style stipple hatch (random dots) inside rectangle."""
    rx0, rx1 = min(x0, x1), max(x0, x1)
    ry0, ry1 = min(y0, y1), max(y0, y1)

    area = (rx1 - rx0) * (ry1 - ry0)
    dots = int(area * density)

    for _ in range(dots):
        x = random.uniform(rx0, rx1)
        y = random.uniform(ry0, ry1)
        r = random.choice((0.6, 0.8, 1.0))
        canvas.create_oval(x - r, y - r, x + r, y + r, fill=color, outline=color)



def draw_schematic(canvas: tk.Canvas, res: dict):
    overlays = res.get("overlays") or {
        "rl": True, "lengths": True, "grades": True, "labels": True,
        "ref": True, "spline": True, "straight_spline": False,
        "slope_pct": False,
    }
    # Dash pattern constants (ensure availability before use)
    PLATFORM_DASH = (6, 4)  # (dash_length, gap_length)
    canvas.delete("all")
    w = canvas.winfo_width()
    h = canvas.winfo_height()
    if w < 200 or h < 150:
        return

    canvas.configure(bg=WHITE, highlightthickness=0)
    canvas.create_rectangle(0, 0, w, h, fill=WHITE, outline="")

    # Subtle CAD-style paper grid. This is visual only; geometry remains unchanged.
    minor = 20
    major = 100
    for gx in range(0, w + minor, minor):
        canvas.create_line(gx, 0, gx, h, fill=(GRID_MAJOR if gx % major == 0 else GRID_MINOR), width=1)
    for gy in range(0, h + minor, minor):
        canvas.create_line(0, gy, w, gy, fill=(GRID_MAJOR if gy % major == 0 else GRID_MINOR), width=1)

    segments = res["segments"]
    points = res["points"]

    ov = res.get("overlays", {})
    show_rl = bool(ov.get("rl", True))
    show_lengths = bool(ov.get("lengths", True))
    show_grades = bool(ov.get("grades", True))
    show_labels = bool(ov.get("labels", True))
    show_ref = bool(ov.get("ref", True))
    show_spline = bool(ov.get("spline", True))
    straight_spline = bool(ov.get("straight_spline", False))
    show_slope_pct = bool(ov.get("slope_pct", False))
    platform_rl = res["platform_rl"]
    tos_rl = res["tos_rl"]
    slab_step_rl = res.get("slab_step_rl", tos_rl)

    total_len = points[-1][0]

    # Layout
    # The graph must stay fully within the viewport (no disappearing linework/text).
    # We therefore *fit* the entire required width/height and keep X/Y scale equal.
    margin_l = 70
    margin_t = 48
    margin_b = 30

    ys = [p[1] for p in points] + [platform_rl]
    y_min, y_max = min(ys), max(ys)
    y_rng = max(y_max - y_min, 0.20)
    y_min -= 0.25 * y_rng
    y_max += 0.25 * y_rng
    y_rng = max(y_max - y_min, 0.20)

    # Consistent scale (X and Y use the SAME pixels-per-metre so the profile angle is true).
    # We *fit-to-viewport* so nothing can disappear off-screen.
    BASE_PX_PER_M = 40.0

    # Reserve room on the right for the slab box + platform labels so they never clip.
    slab_width = 110
    right_label_pad = 190  # room for PLATFORM + RL text
    margin_r = max(40, slab_width + right_label_pad)

    avail_w = max(50.0, (w - margin_l - margin_r))
    avail_h = max(50.0, (h - margin_t - margin_b))

    # Zoom to fit extents without distortion.
    zoom_x = avail_w / max(total_len * BASE_PX_PER_M, 1.0)
    zoom_y = avail_h / max(y_rng * BASE_PX_PER_M, 1.0)
    zoom = max(0.12, min(zoom_x, zoom_y))

    px_per_m = BASE_PX_PER_M * zoom

    # Font scaling is gentler than geometry scaling so labels stay readable.
    font_scale = max(0.85, min(1.6, zoom))
    def FS(n: int) -> int:
        return max(8, int(n * font_scale))
    def X(station_m):
        return margin_l + (station_m * px_per_m)

    def Y(rl):
        return margin_t + (y_max - rl) * px_per_m

    # Key datum Y-values (computed after Y() exists)
    origin_y = Y(points[0][1])  # starting boundary RL
    platform_y = Y(platform_rl)  # platform RL (already tolerance-adjusted in compute)

    # No scrollregion: we always fit into the viewport.

    # ✅ REMOVED: extra horizontal dashed datum/reference line
    # (previously: datum_y = ... and canvas.create_line(...))

    # Boundary line + label
    bx = margin_l
    # Boundary line (stop at lowest dashed horizontal line)
    boundary_bottom_y = max(origin_y, platform_y)
    if show_ref:
        canvas.create_line(bx, margin_t - 10, bx, boundary_bottom_y,
                           fill=INK, width=2)
    # Calculate vertical midpoint of the actual boundary line so the label stays centred
    boundary_mid_y = (margin_t - 10 + boundary_bottom_y) / 2

    if show_labels:
        canvas.create_text(
                bx - 20, boundary_mid_y,
                text="BOUNDARY", angle=90, fill=INK,
                font=("Arial", FS(12), "bold"), anchor="center"
            )

    # Driveway design polyline
    poly = []
    for st, rl in points:
        poly.extend([X(st), Y(rl)])
    canvas.create_line(*poly, fill=GUIDE, width=1, dash=(5, 4), capstyle="round", joinstyle="round")

    # Average spline line through graph points.
    # Optional overlay: enters horizontally at the boundary, passes through the
    # strip drain as a true horizontal 100mm section, and exits horizontally at
    # the garage rebate level / final driveway RL point (not the garage slab top).
    if show_spline:
        # Use the actual graph/profile points. The final point is the rebate level;
        # do not lift the spline end to slab_step_rl/top-of-slab.
        spline_profile_points = list(points)
        exact_smooth_points = res.get("smooth_profile_points")

        # Identify intentional flat drain spans so the spline does not V-shape through
        # the 100mm drain and the rate check does not falsely fail on that detail.
        flat_spans: list[tuple[float, float]] = []
        cur_st = 0.0
        for s in segments:
            st0 = cur_st
            st1 = cur_st + s.length_m
            if getattr(s, "sign", 1) == 0 or "DRAIN" in s.name.upper():
                flat_spans.append((st0, st1))
            cur_st = st1

        spline_fail, spline_messages = _profile_rate_change_flags(spline_profile_points, flat_spans=flat_spans)
        if straight_spline:
            # Draw straight lines through each calculated transition point.
            spline_station_rl = spline_profile_points
        elif exact_smooth_points:
            # Auto best-fit profiles already contain the exact mathematically smooth curve.
            spline_station_rl = exact_smooth_points
            spline_fail = bool(res.get("best_fit_max_grade_change", 0.0) > (1.0 / 8.0) + 1e-9)
        else:
            spline_station_rl = _catmull_style_spline_points(
                spline_profile_points,
                samples_per_segment=22,
                flat_spans=flat_spans,
            )
        spline_xy = []
        for st, rl in spline_station_rl:
            spline_xy.extend([X(st), Y(rl)])
        best_fit_failed = bool(res.get("best_fit_failed", False))
        spline_fail = spline_fail or best_fit_failed
        spline_colour = "#ff4b5c" if spline_fail else ACCENT
        if len(spline_xy) >= 4:
            canvas.create_line(*spline_xy, fill=spline_colour, width=3, capstyle="round", joinstyle="round")
        if show_labels:
            if res.get("auto_best_fit"):
                if best_fit_failed:
                    status_txt = "FAIL — " + str(res.get("best_fit_fail_reason", "Driveway profile is non-compliant."))
                else:
                    status_txt = "AUTO BEST FIT — ENDS ≤ 1:8 · MID ≤ 1:4 · ΔGRADE ≤ 1:8" if not spline_fail else "FAIL — ADJACENT GRADE CHANGE > 1:8"
            else:
                status_txt = "FAIL — RATE CHANGE > 1:8" if spline_fail else "AVG SPLINE OK ≤ 1:8"
            # Place spline compliance status at the bottom-left of the schematic viewport
            # so it stays clear of the top dimension/RL labels.
            canvas.create_text(
                16, h - 16,
                text=status_txt, fill=spline_colour,
                font=("Arial", FS(10), "bold"), anchor="sw",
                width=max(240, w - 32), justify="left"
            )

    # Dashed guides at breakpoints (stop at datum depending on slope direction)
    origin_rl = points[0][1]
    y_stop = origin_y if (platform_rl >= origin_rl) else platform_y  # upslope -> origin line, downslope -> platform line

    for st, _rl in points:
        x = X(st)
        if overlays.get("ref", True):
            canvas.create_line(x, margin_t - 8, x, y_stop, dash=(2, 4), fill=GUIDE)
    # Top segment dimensions
    dim_y = max(12, margin_t - 16)

    # --- Auto-space RL text above the zone/dimension text (font-metric driven) ---
    dim_font = tkfont.Font(family="Arial", size=FS(10), weight="bold")
    rl_font = tkfont.Font(family="Arial", size=FS(9), weight="bold")
    dim_h = dim_font.metrics("linespace")
    rl_h = rl_font.metrics("linespace")
    dim_text_y = dim_y - 10  # matches the y used for the segment length text
    dim_top = dim_text_y - (dim_h / 2)
    gap = max(6, int(0.35 * dim_h))  # breathing room between the two bands
    rl_band_y = max(rl_h + 6, int(dim_top - gap))  # RL text uses anchor=\"s\" (bottom)
    # Ensure RL band stays visible (anchor south draws upward).

    seg_starts = []
    cur = 0.0
    for s in segments:
        seg_starts.append(cur)
        cur += s.length_m
    seg_ends = seg_starts[1:] + [total_len]

    def _fit_label_to_px(text: str, font_obj: tkfont.Font, max_px: float) -> str:
        """Trim a segment label so it stays inside its zone bay."""
        text = (text or "").strip()
        if not text:
            return ""
        max_px = max(8.0, float(max_px))
        if font_obj.measure(text) <= max_px:
            return text
        ell = "…"
        if font_obj.measure(ell) > max_px:
            return ""
        trimmed = text
        while trimmed and font_obj.measure(trimmed + ell) > max_px:
            trimmed = trimmed[:-1].rstrip()
        return (trimmed + ell) if trimmed else ell

    zone_font = tkfont.Font(family="Arial", size=FS(9), weight="normal")

    for s, st0, st1 in zip(segments, seg_starts, seg_ends):
        x0, x1 = X(st0), X(st1)
        if show_ref:
            _dim_line(canvas, x0, dim_y, x1, dim_y, color=INK, width=1, ah=8)

        length_txt = ""
        if getattr(s, "sign", 1) != 0:
            length_txt = fmt_mm(s.length_m) if res.get("custom_mode") else (fmt_mm(s.length_m) if (abs(s.length_m - 1.0) < 1e-6 or abs(s.length_m - 1.5) < 1e-6) else "VARIES")
        cx = (x0 + x1) / 2
        if show_lengths:
            canvas.create_text(cx, dim_y - 10, text=length_txt, fill=INK,
                               font=("Arial", FS(10), "bold"), anchor="center")

        if getattr(s, "sign", 1) != 0:
            slope_txt = (f"1:{int(s.ratio)}" if float(s.ratio).is_integer() else f"1:{s.ratio:g}")
            if show_grades:
                canvas.create_text(cx, dim_y + 14, text=slope_txt, fill=ACCENT,
                                   font=("Arial", FS(11), "bold"), anchor="center")
        elif show_grades:
            canvas.create_text(cx, dim_y + 14, text="FLAT", fill=ACCENT,
                               font=("Arial", FS(10), "bold"), anchor="center")

        if show_slope_pct:
            if getattr(s, "sign", 1) == 0:
                pct_txt = "0.00%"
            else:
                signed_pct = s.grade_pct * (1 if s.sign > 0 else -1)
                pct_txt = f"{signed_pct:+.2f}%"
            canvas.create_text(cx, dim_y + 36, text=pct_txt, fill=ACCENT,
                               font=("Arial", FS(9), "bold"), anchor="center")

        # Zone name label: uses the custom zone matrix text and centres it in
        # the matching schematic bay so each custom row can be identified on the graph.
        if show_labels:
            zone_txt = _fit_label_to_px(getattr(s, "name", ""), zone_font, abs(x1 - x0) - 8)
            if zone_txt:
                canvas.create_text(
                    cx, dim_y + (58 if show_slope_pct else 32),
                    text=zone_txt,
                    fill=LIGHT_INK,
                    font=zone_font,
                    anchor="center"
                )
    # Slab (solid blue fill). Driveway ends at TOS, then steps down 35mm to slab top
    end_x = X(total_len)
    end_tos_y = Y(tos_rl)
    slab_top_y = Y(slab_step_rl)

    # 35mm vertical step from final RL point to garage slab
    if abs(slab_top_y - end_tos_y) > 0.5:
        canvas.create_line(end_x, end_tos_y, end_x, slab_top_y, fill=INK, width=2)
    # Rise/Fall label at PLATFORM level (horizontal text, left side of graph, right of boundary line)
    # Shows the delta from boundary RL to platform RL.
    d_pf = platform_rl - points[0][1]
    rf_txt = ("RISE TO PLATFORM - " if d_pf >= 0 else "FALL TO PLATFORM - ") + f"{abs(d_pf):.3f} m"
    rf_x = margin_l + max(4, int(6 * zoom))  # same inset from boundary as platform line start
    # Keep inside viewport and clear of left border
    rf_x = min(w - margin_r - 10, max(margin_l + max(4, int(6 * zoom)), rf_x))
    # Place on the platform dashed line with a small offset for readability
    rf_y = platform_y - (PLATFORM_DASH[1] if 'PLATFORM_DASH' in locals() else max(2, int(3 * zoom)))  # baseline exactly one dash-gap above dashed line
    if show_labels:
        canvas.create_text(rf_x, rf_y, text=rf_txt,
                           fill=INK, font=("Arial", FS(10), "bold"),
                           anchor="sw")


    slab_left = end_x
    slab_top = slab_top_y
    slab_bottom = platform_y
    slab_right = slab_left + slab_width

    canvas.create_rectangle(
        slab_left, slab_top, slab_right, slab_bottom,
        fill="#dbe5ef", outline=INK, width=2
    )

    if show_labels:
        canvas.create_text(slab_left + 4, slab_top - 10,
                           text="GARAGE SLAB", fill=INK,
                           font=("Arial", FS(11), "bold"), anchor="sw")
    # Origin RL dashed line (same style as platform level line)
    if show_ref:
        canvas.create_line(margin_l, origin_y, slab_right, origin_y,
                               fill=LIGHT_INK, width=1, dash=PLATFORM_DASH)

    # Platform line: thin dashed grey (extends under slab)
    if show_ref:
        canvas.create_line(margin_l, platform_y, slab_right, platform_y,
                               fill=LIGHT_INK, width=1, dash=PLATFORM_DASH)

    if show_labels:
        canvas.create_text(slab_left + 4, platform_y + 6,
                           text="PLATFORM", fill=INK,
                           font=("Arial", FS(11), "bold"), anchor="nw")

    if show_rl:
        canvas.create_text(slab_left + 4, platform_y + 26, text=f"RL {platform_rl:.3f}",
                       fill=INK, font=("Arial", FS(10), "bold"), anchor="nw")

    # RL labels above dashed guides
    # Suppress the RL label at the RIGHT-HAND SIDE of the drain (drain end station) for downslope only.
    drain_end_station = None
    if res.get("direction") == "Down from boundary":
        cur_st = 0.0
        for s in segments:
            st0 = cur_st
            st1 = cur_st + s.length_m
            if s.name == "DRAIN":
                drain_end_station = st1  # RHS of drain
                break
            cur_st = st1

    for st, rl in points:
        if drain_end_station is not None and abs(st - drain_end_station) < 1e-9:
            continue

        x = X(st)
        py = Y(rl)

        canvas.create_oval(x - 3, py - 3, x + 3, py + 3, fill=INK, outline="")
        if show_rl:
            canvas.create_text(
                x, rl_band_y,
                text=f"RL {rl:.3f}",
                fill=INK,
                font=("Arial", FS(9), "bold"),
                anchor="s",
            )



    # ---------------------------------------------------------
    # Strip drain symbol (downslope only)
    # Draw a boxed 100mm flat section after the 1:8 zone, with title below.
    # ---------------------------------------------------------
    if res.get("direction") == "Down from boundary":
        drain_start = None
        drain_end = None
        cur_st = 0.0
        for s in segments:
            st0 = cur_st
            st1 = cur_st + s.length_m
            if getattr(s, "sign", 1) == 0 and "DRAIN" in s.name:
                drain_start, drain_end = st0, st1
                break
            cur_st = st1

        if drain_start is not None and drain_end is not None:
            # RL at drain (flat), use the RL at drain start station if present
            drain_rl = None
            for st, rl in points:
                if abs(st - drain_start) < 1e-9:
                    drain_rl = rl
                    break
            if drain_rl is None:
                drain_rl = points[-1][1]

            x0, x1 = X(drain_start), X(drain_end)
            # --- Drain box: true 100x100 mm (100x100), sitting BELOW the profile ---
            # Requirement: top of box touches the graphed RL line at the drain station.
            box_size_m = 0.100  # 100mm
            box_h = box_size_m * px_per_m

            # Top of the box touches the profile (no gap). Box extends downward.
            y_top = Y(drain_rl)
            y_bottom = y_top + box_h

            canvas.create_rectangle(
                x0,
                y_top,
                x1,
                y_bottom,
                fill=WHITE,
                outline=INK,
                width=2
            )
            if show_labels:
                canvas.create_text(
                    (x0 + x1) / 2,
                    y_bottom + max(6, int(6 * zoom)),
                    text="DRAIN\n100mm", justify="center",
                    fill=INK,
                    font=("Arial", FS(10), "bold"),
                    anchor="n"
                )



# =============================
# SPLINE / RATE-OF-CHANGE CHECK
# =============================
def _in_any_span(x0: float, x1: float, spans: list[tuple[float, float]], tol: float = 1e-9) -> bool:
    """True when the whole station interval sits inside one ignored/flat span."""
    lo, hi = min(x0, x1), max(x0, x1)
    for a, b in spans:
        sa, sb = min(a, b), max(a, b)
        if lo >= sa - tol and hi <= sb + tol:
            return True
    return False


def _at_span_edge(x: float, spans: list[tuple[float, float]], tol: float = 1e-9) -> bool:
    """True when a station is the start/end of an ignored/flat span."""
    for a, b in spans:
        if abs(x - a) <= tol or abs(x - b) <= tol:
            return True
    return False


def _profile_rate_change_flags(
    points: list[tuple[float, float]],
    threshold_ratio: float = 8.0,
    flat_spans: list[tuple[float, float]] | None = None,
) -> tuple[bool, list[str]]:
    """
    Returns (non_compliant, messages) for abrupt profile changes.

    The check is intentionally conservative for drafting review:
    - any individual non-flat run shorter than 1.0m that is steeper than 1:8 is flagged; and
    - any change in segment grade greater than 1:8 where one side of the break is under 1.0m is flagged.

    Intentional fixed flat details such as the 100mm strip drain can be passed in
    as flat_spans. Those spans, and their immediate entry/exit breakpoints, are
    ignored so the drain does not create a false V-shaped rate-change failure.
    """
    flat_spans = flat_spans or []
    threshold_grade = 1.0 / threshold_ratio
    messages: list[str] = []

    seg_grades: list[float] = []
    seg_lens: list[float] = []
    seg_ignored: list[bool] = []
    seg_stations: list[tuple[float, float]] = []

    for i in range(len(points) - 1):
        x0, y0 = points[i]
        x1, y1 = points[i + 1]
        run = max(0.0, x1 - x0)
        ignore = _in_any_span(x0, x1, flat_spans)
        seg_stations.append((x0, x1))
        seg_lens.append(run)
        seg_ignored.append(ignore)
        grade = 0.0 if run <= 1e-9 else (y1 - y0) / run
        seg_grades.append(grade)
        if not ignore and run < 1.0 - 1e-9 and abs(grade) > threshold_grade + 1e-9:
            messages.append(f"Segment {i + 1}: {run:.2f}m run exceeds 1:8 grade")

    for i in range(len(seg_grades) - 1):
        # Ignore the drain entry/exit breakpoints. The drain is a deliberate flat
        # slot detail, not a driveway transition length.
        break_station = seg_stations[i][1]
        if seg_ignored[i] or seg_ignored[i + 1] or _at_span_edge(break_station, flat_spans):
            continue
        change = abs(seg_grades[i + 1] - seg_grades[i])
        if change > threshold_grade + 1e-9 and min(seg_lens[i], seg_lens[i + 1]) < 1.0 - 1e-9:
            messages.append(f"Breakpoint {i + 1}: rate change exceeds 1:8 within <1m")

    return bool(messages), messages


def _catmull_style_spline_points(
    profile_points: list[tuple[float, float]],
    samples_per_segment: int = 18,
    flat_spans: list[tuple[float, float]] | None = None,
) -> list[tuple[float, float]]:
    """
    Build a smooth cubic Hermite-style spline through the profile points.
    Start and end tangents are forced horizontal so the curve enters and exits flat.

    For intentional flat spans such as the 100mm strip drain, the spline is drawn
    as an exact horizontal line across that span and the tangents at both drain
    edges are forced to 0. This prevents the drain from becoming a V-shaped dip.
    """
    if len(profile_points) < 2:
        return profile_points[:]

    flat_spans = flat_spans or []
    pts = sorted(profile_points, key=lambda p: p[0])

    def force_horizontal_at_station(x: float) -> bool:
        return _at_span_edge(x, flat_spans)

    tangents: list[float] = []
    for i, (x, y) in enumerate(pts):
        if i == 0 or i == len(pts) - 1 or force_horizontal_at_station(x):
            tangents.append(0.0)  # horizontal entry/exit and drain edges
        else:
            x_prev, y_prev = pts[i - 1]
            x_next, y_next = pts[i + 1]
            dx = x_next - x_prev
            tangents.append(0.0 if abs(dx) < 1e-9 else (y_next - y_prev) / dx)

    out: list[tuple[float, float]] = []
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        dx = x1 - x0
        if dx <= 1e-9:
            continue

        n = max(6, samples_per_segment)

        # Draw intentional drain/flat spans as a true horizontal segment. Keep
        # y locked to the start RL so it passes across the top of the drain box.
        if _in_any_span(x0, x1, flat_spans):
            for j in range(n):
                t = j / float(n)
                x = x0 + dx * t
                out.append((x, y0))
            continue

        m0 = tangents[i]
        m1 = tangents[i + 1]
        for j in range(n):
            t = j / float(n)
            h00 = 2*t**3 - 3*t**2 + 1
            h10 = t**3 - 2*t**2 + t
            h01 = -2*t**3 + 3*t**2
            h11 = t**3 - t**2
            x = x0 + dx * t
            y = h00*y0 + h10*dx*m0 + h01*y1 + h11*dx*m1
            out.append((x, y))
    out.append(pts[-1])
    return out


# =============================
# SIMPLE TOOLTIP
# =============================
class ToolTip:
    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self.tipwindow = None
        self.after_id = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        try:
            self.after_id = self.widget.after(450, self._show)
        except Exception:
            self.after_id = None

    def _cancel(self):
        if self.after_id:
            try:
                self.widget.after_cancel(self.after_id)
            except Exception:
                pass
            self.after_id = None

    def _show(self):
        if self.tipwindow or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 18
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
            self.tipwindow = tw = tk.Toplevel(self.widget)
            tw.wm_overrideredirect(True)
            tw.wm_geometry(f"+{x}+{y}")
            label = tk.Label(
                tw, text=self.text, justify="left",
                bg="#ffffe8", fg="#222222",
                relief="solid", borderwidth=1,
                font=("Segoe UI", 9), padx=7, pady=4
            )
            label.pack(ipadx=1)
        except Exception:
            self.tipwindow = None

    def _hide(self, _event=None):
        self._cancel()
        if self.tipwindow:
            try:
                self.tipwindow.destroy()
            except Exception:
                pass
            self.tipwindow = None

# =============================
# GUI
# =============================
class CalculatorPane(ttk.Frame):
    def __init__(self, parent, tolerance_m: float = TOLERANCE_M, custom_mode: bool = False):
        super().__init__(parent)

        self.tolerance_m = tolerance_m
        self.custom_mode = custom_mode
        # -----------------------------
        # THEME / TYPOGRAPHY
        # -----------------------------
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        # Technical / CAD workstation UI palette
        UI_BG = "#0d1117"          # app shell
        APP_BG = "#0b1220"         # notebook / outer areas
        CARD_BG = "#151c29"        # control panels
        CARD_ALT_BG = "#1d2635"    # selected tabs / alternate panels
        PANEL_BORDER = "#334155"   # fine technical border lines
        PANEL_INSET = "#263244"
        HEADER_BG = "#070b12"      # command-bar header
        HEADER_HILITE = "#22d3ee"  # cyan CAD accent
        HEADER_TEXT = "#e5f6ff"
        HEADER_SUB = "#8fb3c7"
        TEXT_DARK = "#dce7f3"
        TEXT_MUTED = "#8ea4b8"
        BUTTON_BG = "#1f2a3a"
        BUTTON_ACTIVE = "#27364b"
        BUTTON_BORDER = "#3f5872"
        BUTTON_TEXT = "#e7f8ff"
        PRIMARY_BG = "#00a3c7"
        PRIMARY_ACTIVE = "#00c2e8"
        PRIMARY_BORDER = "#66e8ff"
        INPUT_BG = "#0b1220"
        COMBO_BG = "#0b1220"
        COMBO_HOVER = "#122238"
        COMBO_ARROW = "#66e8ff"
        COMBO_BORDER_HOVER = "#22d3ee"

        self.configure(style="App.TFrame")

        base_font = ("Segoe UI", 10)
        style.configure(".", font=base_font)
        style.configure("App.TFrame", background=UI_BG)
        style.configure("TFrame", background=UI_BG)
        style.configure("Card.TFrame", background=CARD_BG)
        style.configure("RightPane.TFrame", background=UI_BG)
        style.configure("TLabel", background=UI_BG, foreground=TEXT_DARK)
        style.configure("Muted.TLabel", background=UI_BG, foreground=TEXT_MUTED)
        style.configure("Card.TLabel", background=CARD_BG, foreground=TEXT_DARK)
        style.configure("CardMuted.TLabel", background=CARD_BG, foreground=TEXT_MUTED)
        style.configure("Panel.TLabel", background=CARD_BG, foreground=TEXT_DARK)
        style.configure("PanelMuted.TLabel", background=CARD_BG, foreground=TEXT_MUTED)
        style.configure("TCheckbutton", background=UI_BG, foreground=TEXT_DARK)
        style.configure("Panel.TCheckbutton", background=CARD_BG, foreground=TEXT_DARK)
        style.map("TCheckbutton", background=[("active", UI_BG)])
        style.map("Panel.TCheckbutton", background=[("active", CARD_BG)])

        # Dark schematic-style scrollbar. Tkinter on Windows can ignore some ttk
        # scrollbar colours, so the actual left-panel scrollbar below uses the
        # classic tk.Scrollbar with these matching colours applied directly.
        SCROLL_BG = "#1d2635"
        SCROLL_ACTIVE = "#27364b"
        SCROLL_TROUGH = "#0b1220"
        SCROLL_BORDER = "#334155"
        style.configure(
            "DarkSchematic.Vertical.TScrollbar",
            gripcount=0,
            background=SCROLL_BG,
            darkcolor=SCROLL_BORDER,
            lightcolor=SCROLL_BORDER,
            troughcolor=SCROLL_TROUGH,
            bordercolor=SCROLL_BORDER,
            arrowcolor=TEXT_MUTED,
            relief="flat",
            width=16,
        )
        style.map(
            "DarkSchematic.Vertical.TScrollbar",
            background=[("active", SCROLL_ACTIVE), ("pressed", "#111827")],
            arrowcolor=[("active", TEXT_DARK), ("pressed", TEXT_DARK)],
        )

        style.configure(
            "TButton",
            padding=(8, 4),
            font=("Segoe UI", 8, "bold"),
            background=BUTTON_BG,
            foreground=BUTTON_TEXT,
            bordercolor=BUTTON_BORDER,
            lightcolor=BUTTON_BG,
            darkcolor=BUTTON_BORDER,
            relief="flat",
            focusthickness=1,
            focuscolor=BUTTON_BORDER,
        )
        style.map(
            "TButton",
            background=[("active", BUTTON_ACTIVE), ("pressed", BUTTON_BORDER)],
            foreground=[("disabled", "#c2cad8")],
            bordercolor=[("active", "#89aee8"), ("focus", "#89aee8"), ("pressed", BUTTON_BORDER)],
            lightcolor=[("active", "#dce9ff"), ("focus", "#dce9ff"), ("pressed", BUTTON_BORDER)],
            darkcolor=[("active", "#6f8fc8"), ("focus", "#6f8fc8"), ("pressed", BUTTON_BORDER)],
        )

        style.configure(
            "Primary.TButton",
            padding=(8, 3),
            font=("Segoe UI", 9, "bold"),
            background=PRIMARY_BG,
            foreground="#ffffff",
            bordercolor=PRIMARY_BORDER,
            lightcolor=PRIMARY_BG,
            darkcolor=PRIMARY_BORDER,
            relief="raised",
            focusthickness=2,
            focuscolor=PRIMARY_BORDER,
        )
        style.map(
            "Primary.TButton",
            background=[("active", PRIMARY_ACTIVE), ("pressed", PRIMARY_BORDER)],
            bordercolor=[("active", "#9dc0ff"), ("focus", "#9dc0ff"), ("pressed", PRIMARY_BORDER)],
            lightcolor=[("active", "#d9e8ff"), ("focus", "#d9e8ff"), ("pressed", PRIMARY_BORDER)],
            darkcolor=[("active", "#6f95d6"), ("focus", "#6f95d6"), ("pressed", PRIMARY_BORDER)],
        )

        style.configure(
            "Icon.TButton",
            padding=(5, 2),
            font=("Segoe UI Symbol", 10, "bold"),
            background="#6f89bb",
            foreground="#ffffff",
            bordercolor="#5570a1",
            lightcolor="#6f89bb",
            darkcolor="#5570a1",
            relief="raised",
            focusthickness=1,
            focuscolor="#5570a1",
        )
        style.map(
            "Icon.TButton",
            background=[("active", "#5f79ac"), ("pressed", "#4f6793")],
            foreground=[("disabled", "#dbe3f2")],
            bordercolor=[("active", "#9ab8ef"), ("focus", "#9ab8ef"), ("pressed", "#4f6793")],
            lightcolor=[("active", "#d9e7ff"), ("focus", "#d9e7ff"), ("pressed", "#4f6793")],
            darkcolor=[("active", "#7597d1"), ("focus", "#7597d1"), ("pressed", "#4f6793")],
        )

        style.configure(
            "Secondary.TButton",
            padding=(12, 6),
            font=("Segoe UI", 8, "bold"),
            background="#6f89bb",
            foreground="#ffffff",
            bordercolor="#5570a1",
            lightcolor="#6f89bb",
            darkcolor="#5570a1",
            relief="raised",
            focusthickness=1,
            focuscolor="#5570a1",
        )
        style.map(
            "Secondary.TButton",
            background=[("active", "#5f79ac"), ("pressed", "#4f6793")],
            foreground=[("disabled", "#dbe3f2")],
            bordercolor=[("active", "#9ab8ef"), ("focus", "#9ab8ef"), ("pressed", "#4f6793")],
            lightcolor=[("active", "#d9e7ff"), ("focus", "#d9e7ff"), ("pressed", "#4f6793")],
            darkcolor=[("active", "#7597d1"), ("focus", "#7597d1"), ("pressed", "#4f6793")],
        )

        style.configure(
            "FloatingPrimary.TButton",
            padding=(16, 8),
            font=("Segoe UI", 10, "bold"),
            background=PRIMARY_BG,
            foreground="#ffffff",
            bordercolor=PRIMARY_BORDER,
            lightcolor="#7df3ff",
            darkcolor="#006b83",
            relief="raised",
            focusthickness=2,
            focuscolor=PRIMARY_BORDER,
        )
        style.map(
            "FloatingPrimary.TButton",
            background=[("active", PRIMARY_ACTIVE), ("pressed", PRIMARY_BORDER)],
            bordercolor=[("active", "#b7f4ff"), ("focus", "#b7f4ff"), ("pressed", PRIMARY_BORDER)],
        )
        style.configure(
            "FloatingSecondary.TButton",
            padding=(16, 8),
            font=("Segoe UI", 10, "bold"),
            background="#243247",
            foreground="#ffffff",
            bordercolor="#6f89bb",
            lightcolor="#3f5872",
            darkcolor="#111827",
            relief="raised",
            focusthickness=1,
            focuscolor="#6f89bb",
        )
        style.map(
            "FloatingSecondary.TButton",
            background=[("active", "#32435c"), ("pressed", "#1c2738")],
            bordercolor=[("active", "#9ab8ef"), ("focus", "#9ab8ef"), ("pressed", "#4f6793")],
        )

        style.configure(
            "TLabelframe",
            padding=(12, 12),
            background=CARD_BG,
            bordercolor=PANEL_BORDER,
            lightcolor=PANEL_INSET,
            darkcolor=PANEL_BORDER,
            relief="solid",
            borderwidth=1,
        )
        style.configure(
            "TLabelframe.Label",
            font=("Segoe UI", 11, "bold"),
            background=CARD_BG,
            foreground=TEXT_DARK,
        )
        style.configure(
            "TEntry",
            fieldbackground=INPUT_BG,
            foreground=TEXT_DARK,
            bordercolor=PANEL_BORDER,
            lightcolor=PANEL_INSET,
            darkcolor=PANEL_BORDER,
            insertcolor=TEXT_DARK,
            padding=6,
        )
        style.configure(
            "Modern.TCombobox",
            fieldbackground=INPUT_BG,
            background=INPUT_BG,
            foreground=TEXT_DARK,
            bordercolor=PANEL_BORDER,
            lightcolor=PANEL_BORDER,
            darkcolor=PANEL_BORDER,
            arrowsize=15,
            padding=(8, 6),
            relief="flat",
        )
        style.configure(
            "Tight.TCombobox",
            fieldbackground=INPUT_BG,
            background=INPUT_BG,
            foreground=TEXT_DARK,
            bordercolor=PANEL_BORDER,
            lightcolor=PANEL_BORDER,
            darkcolor=PANEL_BORDER,
            arrowsize=15,
            padding=(6, 2),
            relief="flat",
        )
        style.map(
            "Modern.TCombobox",
            fieldbackground=[("readonly", INPUT_BG), ("active", COMBO_HOVER)],
            background=[("readonly", INPUT_BG), ("active", COMBO_HOVER)],
            foreground=[("readonly", TEXT_DARK)],
        )
        style.map(
            "Modern.TCombobox",
            fieldbackground=[("readonly", INPUT_BG), ("active", COMBO_HOVER)],
            background=[("readonly", INPUT_BG), ("active", COMBO_HOVER)],
            foreground=[("readonly", TEXT_DARK), ("active", TEXT_DARK)],
            bordercolor=[("focus", PRIMARY_BORDER), ("active", COMBO_BORDER_HOVER)],
            lightcolor=[("focus", PRIMARY_BORDER), ("active", COMBO_BORDER_HOVER)],
            darkcolor=[("focus", PRIMARY_BORDER), ("active", COMBO_BORDER_HOVER)],
            arrowcolor=[("readonly", COMBO_ARROW), ("active", PRIMARY_BORDER)],
        )

        style.map(
            "Tight.TCombobox",
            fieldbackground=[("readonly", INPUT_BG), ("active", COMBO_HOVER)],
            background=[("readonly", INPUT_BG), ("active", COMBO_HOVER)],
            foreground=[("readonly", TEXT_DARK), ("active", TEXT_DARK)],
            bordercolor=[("focus", PRIMARY_BORDER), ("active", COMBO_BORDER_HOVER)],
            lightcolor=[("focus", PRIMARY_BORDER), ("active", COMBO_BORDER_HOVER)],
            darkcolor=[("focus", PRIMARY_BORDER), ("active", COMBO_BORDER_HOVER)],
            arrowcolor=[("readonly", COMBO_ARROW), ("active", PRIMARY_BORDER)],
        )

        try:
            self.option_add("*TCombobox*Listbox.background", INPUT_BG)
            self.option_add("*TCombobox*Listbox.foreground", TEXT_DARK)
            self.option_add("*TCombobox*Listbox.selectBackground", "#0e7490")
            self.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
            self.option_add("*TCombobox*Listbox.font", "{Segoe UI} 10")
        except Exception:
            pass
        style.configure("TNotebook", background=APP_BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(12, 8), font=("Segoe UI", 8, "bold"))
        style.map("TNotebook.Tab", background=[("selected", CARD_BG), ("active", CARD_ALT_BG)])

        style.configure("Header.TFrame", background=HEADER_BG)
        style.configure("Header.TLabel", background=HEADER_BG, foreground=HEADER_TEXT)
        style.configure("HeaderTitle.TLabel", background=HEADER_BG, foreground=HEADER_TEXT)
        style.configure("HeaderSub.TLabel", background=HEADER_BG, foreground=HEADER_SUB)

        LEFT_COLUMN_WIDTH = 520
        LEFT_CONTENT_PAD_X = 12
        HEADER_MATCH_WIDTH = LEFT_COLUMN_WIDTH - (LEFT_CONTENT_PAD_X * 2)
        self.header_disclaimer_text = (
            "© 2026 Ryan Anderson. All rights reserved.  "
            "This software is licensed for internal use only.  "
            "Unauthorized copying, modification, or distribution is prohibited."
        )

        # -----------------------------
        # LAYOUT ROOT
        # -----------------------------
        # Header/logo product block removed for clean full-height technical layout.

        # Ribbon-first layout: all controls run across the top, and the
        # profile schematic sits below full-width of the app window.
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=0)
        self.rowconfigure(1, weight=1)
        self.rowconfigure(2, weight=0)

        ribbon = ttk.Frame(self, padding=10, style="App.TFrame")
        ribbon.grid(row=0, column=0, sticky="ew", padx=(8, 8), pady=(8, 4))
        ribbon.columnconfigure(0, weight=0, minsize=330)
        ribbon.columnconfigure(1, weight=1, minsize=440)
        ribbon.columnconfigure(2, weight=0, minsize=360)
        ribbon.columnconfigure(3, weight=1, minsize=430)
        ribbon.rowconfigure(0, weight=1)

        # Existing control-builder code still writes into `left`; it is now the
        # top ribbon container instead of a left sidebar.
        left = ribbon

        right = ttk.Frame(self, padding=10, style="RightPane.TFrame")
        right.grid(row=1, column=0, sticky="nsew", padx=(8, 8), pady=(4, 8))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)  # canvas grows

        # --------------------------------
        # LEFT: INPUTS (Step 2)
        # --------------------------------
        entry_kw = dict(
            bg=INPUT_BG,
            fg=TEXT_DARK,
            insertbackground=PRIMARY_BORDER,
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightbackground=PANEL_BORDER,
            highlightcolor=PRIMARY_BORDER,
            selectbackground="#0e7490",
            selectforeground="#ffffff",
        )
        inputs_card = tk.Frame(
            left,
            bg=CARD_BG,
            bd=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground=PANEL_BORDER,
            highlightcolor=PANEL_BORDER,
            padx=12,
            pady=10,
        )
        inputs_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=0)
        inputs_card.grid_columnconfigure(0, weight=1)
        self.inputs_card = inputs_card
        self.inputs_card.bind("<Configure>", self._sync_header_to_inputs)
        # Re-sync once Tk has finished calculating the real card width.
        self.after_idle(self._sync_header_to_inputs)

        tk.Label(
            inputs_card,
            text="INPUT PARAMETERS",
            bg=CARD_BG,
            fg=TEXT_DARK,
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        lf_inputs = tk.Frame(inputs_card, bg=CARD_BG)
        lf_inputs.grid(row=1, column=0, sticky="ew")
        lf_inputs.columnconfigure(1, weight=1)

        # Boundary RL
        ttk.Label(lf_inputs, text="Boundary level", style="Panel.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=3)
        self.boundary_var = tk.StringVar(value="10.000")
        self.boundary_entry = tk.Entry(lf_inputs, textvariable=self.boundary_var, width=16, **entry_kw)
        self.boundary_entry.grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Label(lf_inputs, text="m", style="Panel.TLabel").grid(row=0, column=2, sticky="w", padx=(4, 0), pady=3)

        # Driveway length
        ttk.Label(lf_inputs, text="Driveway length", style="Panel.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=3)
        self.length_var = tk.StringVar(value="6.0")
        self.length_entry = tk.Entry(lf_inputs, textvariable=self.length_var, width=16, **entry_kw)
        self.length_entry.grid(row=1, column=1, sticky="ew", pady=3)
        ttk.Label(lf_inputs, text="m", style="Panel.TLabel").grid(row=1, column=2, sticky="w", padx=(4, 0), pady=3)

        # Direction
        ttk.Label(lf_inputs, text="Direction", style="Panel.TLabel").grid(row=3, column=0, sticky="w", padx=(0, 6), pady=3)
        self.direction_var = tk.StringVar(value="Up from boundary")
        self.direction_combo = ttk.Combobox(
            lf_inputs,
            textvariable=self.direction_var,
            values=["Up from boundary", "Down from boundary"],
            state="readonly",
            style="Tight.TCombobox",
        )
        self.direction_combo.grid(row=3, column=1, sticky="ew", pady=3)

        # Auto best-fit profile controls
        auto_panel = tk.Frame(
            inputs_card,
            bg="#111927",
            highlightthickness=1,
            highlightbackground=PANEL_BORDER,
            padx=8,
            pady=7,
        )
        auto_panel.grid(row=2, column=0, sticky="ew", pady=(9, 0))
        auto_panel.columnconfigure(1, weight=1)

        self.auto_best_fit_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            auto_panel,
            text="AUTO GENERATE DRIVEWAY",
            style="Panel.TCheckbutton",
            variable=self.auto_best_fit_var,
            command=self._toggle_auto_best_fit,
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 5))

        ttk.Label(auto_panel, text="Boundary RL", style="Panel.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=2)
        self.auto_boundary_var = tk.StringVar(value=self.boundary_var.get())
        self.auto_boundary_entry = tk.Entry(auto_panel, textvariable=self.auto_boundary_var, width=12, **entry_kw)
        self.auto_boundary_entry.grid(row=1, column=1, sticky="ew", pady=2)
        ttk.Label(auto_panel, text="m", style="Panel.TLabel").grid(row=1, column=2, sticky="w", padx=(4, 0))

        ttk.Label(auto_panel, text="Driveway length", style="Panel.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=2)
        self.auto_length_var = tk.StringVar(value=self.length_var.get())
        self.auto_length_entry = tk.Entry(auto_panel, textvariable=self.auto_length_var, width=12, **entry_kw)
        self.auto_length_entry.grid(row=2, column=1, sticky="ew", pady=2)
        ttk.Label(auto_panel, text="m", style="Panel.TLabel").grid(row=2, column=2, sticky="w", padx=(4, 0))

        ttk.Label(auto_panel, text="Target RL", style="Panel.TLabel").grid(row=3, column=0, sticky="w", padx=(0, 6), pady=2)
        self.auto_target_type_var = tk.StringVar(value="Platform RL")
        self.auto_target_type_combo = ttk.Combobox(
            auto_panel,
            textvariable=self.auto_target_type_var,
            values=["Platform RL", "Garage Slab RL"],
            state="readonly",
            style="Tight.TCombobox",
            width=16,
        )
        self.auto_target_type_combo.grid(row=3, column=1, columnspan=2, sticky="ew", pady=2)
        self.auto_target_type_combo.bind("<<ComboboxSelected>>", lambda _event: self._update_auto_target_label())

        self.auto_target_label = ttk.Label(auto_panel, text="Platform RL", style="Panel.TLabel")
        self.auto_target_label.grid(row=4, column=0, sticky="w", padx=(0, 6), pady=2)
        self.auto_target_rl_var = tk.StringVar(value="10.000")
        self.auto_target_rl_entry = tk.Entry(auto_panel, textvariable=self.auto_target_rl_var, width=12, **entry_kw)
        self.auto_target_rl_entry.grid(row=4, column=1, sticky="ew", pady=2)
        ttk.Label(auto_panel, text="m", style="Panel.TLabel").grid(row=4, column=2, sticky="w", padx=(4, 0))

        ttk.Label(auto_panel, text="Boundary end-profile length", style="Panel.TLabel").grid(row=5, column=0, sticky="w", padx=(0, 6), pady=2)
        self.auto_boundary_len_var = tk.StringVar(value="1.0")
        self.auto_boundary_len_entry = tk.Entry(auto_panel, textvariable=self.auto_boundary_len_var, width=12, **entry_kw)
        self.auto_boundary_len_entry.grid(row=5, column=1, sticky="ew", pady=2)
        ttk.Label(auto_panel, text="m", style="Panel.TLabel").grid(row=5, column=2, sticky="w", padx=(4, 0))

        ttk.Label(auto_panel, text="Garage end-profile length", style="Panel.TLabel").grid(row=6, column=0, sticky="w", padx=(0, 6), pady=2)
        self.auto_garage_len_var = tk.StringVar(value="1.5")
        self.auto_garage_len_entry = tk.Entry(auto_panel, textvariable=self.auto_garage_len_var, width=12, **entry_kw)
        self.auto_garage_len_entry.grid(row=6, column=1, sticky="ew", pady=2)
        ttk.Label(auto_panel, text="m", style="Panel.TLabel").grid(row=6, column=2, sticky="w", padx=(4, 0))

        ttk.Label(auto_panel, text="Transition changes", style="Panel.TLabel").grid(row=7, column=0, sticky="w", padx=(0, 6), pady=2)
        self.auto_transition_var = tk.StringVar(value="4")
        self.auto_transition_combo = ttk.Combobox(
            auto_panel,
            textvariable=self.auto_transition_var,
            values=[str(i) for i in range(2, 13)],
            state="readonly",
            style="Tight.TCombobox",
            width=10,
        )
        self.auto_transition_combo.grid(row=7, column=1, sticky="ew", pady=2)
        self._toggle_auto_best_fit()

        # Tolerance
        ttk.Label(lf_inputs, text="Tolerance", style="Panel.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=3)
        self.tol_input_var = tk.StringVar()
        if abs(self.tolerance_m) > 1e-9:
            self.tol_input_var.set(str(int(round(self.tolerance_m * 1000))))
        else:
            self.tol_input_var.set("0")
        self.tol_entry = tk.Entry(lf_inputs, textvariable=self.tol_input_var, width=16, **entry_kw)
        self.tol_entry.grid(row=2, column=1, sticky="ew", pady=3)
        ttk.Label(lf_inputs, text="mm", style="Panel.TLabel").grid(row=2, column=2, sticky="w", padx=(4, 0), pady=3)

        # =============================
        # Custom segments editor (embedded in Driveway tab)
        # - Always visible
        # - Locked unless "Customize" is ticked
        # =============================
        custom_card = tk.Frame(
            left,
            bg=CARD_BG,
            bd=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground=PANEL_BORDER,
            highlightcolor=PANEL_BORDER,
            padx=12,
            pady=10,
        )
        custom_card.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
        custom_card.grid_columnconfigure(0, weight=1)

        tk.Label(
            custom_card,
            text="CUSTOM ZONE MATRIX",
            bg=CARD_BG,
            fg=TEXT_DARK,
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        lf_custom = tk.Frame(custom_card, bg=CARD_BG)
        lf_custom.grid(row=1, column=0, sticky="ew")
        lf_custom.columnconfigure(0, weight=1)

        # Customize toggle (locks/unlocks custom zone editing)
        self._custom_rows = []
        self.customize_var = tk.BooleanVar(value=False)
        self.chk_customize = ttk.Checkbutton(
            lf_custom,
            text="Customize",
            style="Panel.TCheckbutton",
            variable=self.customize_var,
            command=self._on_customize_toggle,
        )
        self.chk_customize.grid(row=0, column=0, columnspan=4, sticky="w", padx=8, pady=(4, 1))

        headers = ["Zone", "Len (mm)", "1:", "Type"]
        for c, h in enumerate(headers):
            ttk.Label(lf_custom, text=h, style="Panel.TLabel").grid(row=1, column=c, sticky="w", padx=4, pady=(0, 1))

        lf_custom.columnconfigure(0, weight=1)
        lf_custom.columnconfigure(1, weight=0)
        lf_custom.columnconfigure(2, weight=0)
        lf_custom.columnconfigure(3, weight=0)

        # Fixed maximum rows keeps UI simple and reliable
        for r in range(2, 10):
            name_var = tk.StringVar(value="")
            len_var = tk.StringVar(value="")
            ratio_var = tk.StringVar(value="")
            typ_var = tk.StringVar(value="FALL")

            name_entry = tk.Entry(lf_custom, textvariable=name_var, width=16, **entry_kw)
            name_entry.grid(row=r, column=0, sticky="ew", padx=4, pady=1)

            len_entry = tk.Entry(lf_custom, textvariable=len_var, width=10, **entry_kw)
            len_entry.grid(row=r, column=1, sticky="w", padx=4, pady=1)

            ratio_entry = tk.Entry(lf_custom, textvariable=ratio_var, width=8, **entry_kw)
            ratio_entry.grid(row=r, column=2, sticky="w", padx=4, pady=1)

            type_combo = ttk.Combobox(
                lf_custom,
                textvariable=typ_var,
                values=["FALL", "RISE", "FLAT"],
                width=8,
                state="readonly",
                style="Tight.TCombobox",
            )
            type_combo.grid(row=r, column=3, sticky="w", padx=4, pady=1)

            def _toggle_ratio(*_, tv=typ_var, rv=ratio_var, re_=ratio_entry):
                if tv.get() == "FLAT":
                    rv.set("")
                    try:
                        re_.configure(state="disabled")
                    except Exception:
                        pass
                else:
                    try:
                        re_.configure(state="normal")
                    except Exception:
                        pass

            typ_var.trace_add("write", _toggle_ratio)
            _toggle_ratio()

            self._custom_rows.append(
                (name_var, len_var, ratio_var, typ_var, name_entry, len_entry, ratio_entry, type_combo)
            )

        # Buttons
        btn_row = 10
        # Reset buttons - forced side-by-side on one row
        reset_row = tk.Frame(lf_custom, bg=CARD_BG)
        reset_row.grid(row=btn_row, column=0, columnspan=4, sticky="ew", padx=4, pady=(4, 2))
        reset_row.columnconfigure(0, weight=1, uniform="reset_buttons")
        reset_row.columnconfigure(1, weight=1, uniform="reset_buttons")

        self.btn_reset_defaults = ttk.Button(
            reset_row,
            text="Reset to defaults",
            command=self._custom_reset_defaults,
            style="TButton",
        )
        self.btn_reset_defaults.grid(row=0, column=0, sticky="ew", padx=(0, 2))

        self.btn_reset_clear = ttk.Button(
            reset_row,
            text="Reset",
            command=self._custom_clear_all,
            style="TButton",
        )
        self.btn_reset_clear.grid(row=0, column=1, sticky="ew", padx=(2, 0))

        # Saved custom driveway profiles
        profile_sep = tk.Frame(lf_custom, bg=PANEL_BORDER, height=1)
        profile_sep.grid_remove()

        profile_card = tk.Frame(
            left,
            bg=CARD_BG,
            bd=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground=PANEL_BORDER,
            highlightcolor=PANEL_BORDER,
            padx=8,
            pady=8,
        )
        profile_card.grid(row=0, column=2, sticky="nsew", padx=(10, 0), pady=0)
        profile_card.columnconfigure(0, weight=1)
        profile_card.columnconfigure(1, weight=1)
        profile_card.columnconfigure(2, weight=1)
        profile_card.columnconfigure(3, weight=1)

        tk.Label(
            profile_card,
            text="SAVED PROFILE BANK",
            bg=CARD_BG,
            fg=TEXT_DARK,
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 6))

        ttk.Label(profile_card, text="Profile / job name", style="Panel.TLabel").grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(0, 1)
        )
        self.profile_name_var = tk.StringVar(value="")
        self.profile_name_entry = tk.Entry(profile_card, textvariable=self.profile_name_var, **entry_kw)
        self.profile_name_entry.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(0, 5))

        ttk.Label(profile_card, text="Notes / job details", style="Panel.TLabel").grid(
            row=3, column=0, columnspan=4, sticky="w", pady=(0, 1)
        )
        self.profile_notes_var = tk.StringVar(value="")
        self.profile_notes_entry = tk.Entry(profile_card, textvariable=self.profile_notes_var, **entry_kw)
        self.profile_notes_entry.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(0, 5))

        ttk.Label(profile_card, text="Saved profile", style="Panel.TLabel").grid(
            row=5, column=0, columnspan=4, sticky="w", pady=(0, 1)
        )
        self.profile_select_var = tk.StringVar(value="")
        self.profile_combo = ttk.Combobox(
            profile_card,
            textvariable=self.profile_select_var,
            values=[],
            state="readonly",
            style="Tight.TCombobox",
        )
        self.profile_combo.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(0, 6))

        tk.Label(
            profile_card,
            text="SAVE · LOAD · DUPLICATE · RENAME · DELETE · EXPORT · IMPORT",
            bg=CARD_BG,
            fg=TEXT_MUTED,
            font=("Segoe UI", 8),
            anchor="w",
        ).grid(row=7, column=0, columnspan=4, sticky="w", pady=(0, 2))

        profile_tools = tk.Frame(profile_card, bg=CARD_BG)
        profile_tools.grid(row=8, column=0, columnspan=4, sticky="ew", pady=(0, 2))
        for _c in range(7):
            profile_tools.columnconfigure(_c, weight=1)

        self.btn_profile_save = ttk.Button(profile_tools, text="💾", width=3, style="Icon.TButton", command=self._profile_save_current)
        self.btn_profile_save.grid(row=0, column=0, sticky="ew", padx=(0, 2))
        ToolTip(self.btn_profile_save, "Save current driveway settings as the named profile")

        self.btn_profile_load = ttk.Button(profile_tools, text="⤓", width=3, style="Icon.TButton", command=self._profile_load_selected)
        self.btn_profile_load.grid(row=0, column=1, sticky="ew", padx=2)
        ToolTip(self.btn_profile_load, "Load selected saved profile")

        self.btn_profile_duplicate = ttk.Button(profile_tools, text="⧉", width=3, style="Icon.TButton", command=self._profile_duplicate)
        self.btn_profile_duplicate.grid(row=0, column=2, sticky="ew", padx=2)
        ToolTip(self.btn_profile_duplicate, "Duplicate selected profile")

        self.btn_profile_rename = ttk.Button(profile_tools, text="✎", width=3, style="Icon.TButton", command=self._profile_rename)
        self.btn_profile_rename.grid(row=0, column=3, sticky="ew", padx=2)
        ToolTip(self.btn_profile_rename, "Rename selected profile using the profile/job name field")

        self.btn_profile_delete = ttk.Button(profile_tools, text="🗑", width=3, style="Icon.TButton", command=self._profile_delete_selected)
        self.btn_profile_delete.grid(row=0, column=4, sticky="ew", padx=2)
        ToolTip(self.btn_profile_delete, "Delete selected saved profile")

        self.btn_profile_export = ttk.Button(profile_tools, text="↗", width=3, style="Icon.TButton", command=self._profile_export)
        self.btn_profile_export.grid(row=0, column=5, sticky="ew", padx=2)
        ToolTip(self.btn_profile_export, "Export saved profiles to a JSON file")

        self.btn_profile_import = ttk.Button(profile_tools, text="↙", width=3, style="Icon.TButton", command=self._profile_import)
        self.btn_profile_import.grid(row=0, column=6, sticky="ew", padx=(2, 0))
        ToolTip(self.btn_profile_import, "Import profiles from a JSON file")

        self._refresh_profile_combo()


        # Initialize custom zone table to match current direction and lock until Customize is ticked
        self._custom_reset_defaults()
        self._set_custom_editor_enabled(False)

        # Keep defaults synced with direction selector (only when NOT customizing)
        self.direction_var.trace_add("write", lambda *_: (not self.customize_var.get()) and self._custom_reset_defaults())
        ttk.Label(lf_inputs, text="Garage slab type", style="Panel.TLabel").grid(row=4, column=0, sticky="w", padx=(0, 6), pady=3)
        self.slab_var = tk.StringVar(value=list(SLAB_OPTIONS.keys())[0])
        self.slab_combo = ttk.Combobox(
            lf_inputs,
            textvariable=self.slab_var,
            values=list(SLAB_OPTIONS.keys()),
            state="readonly",
            style="Tight.TCombobox",
        )
        self.slab_combo.grid(row=4, column=1, sticky="ew", pady=3)

        self.use_custom_slab_var = tk.BooleanVar(value=False)
        self.custom_slab_mm_var = tk.StringVar(value="")

        self.custom_slab_check = ttk.Checkbutton(
            lf_inputs,
            text="Custom slab height",
            style="Panel.TCheckbutton",
            variable=self.use_custom_slab_var,
            command=self._toggle_custom_slab_height,
        )
        self.custom_slab_check.grid(row=5, column=0, columnspan=3, sticky="w", pady=(3, 1))

        self.custom_slab_entry = tk.Entry(lf_inputs, textvariable=self.custom_slab_mm_var, width=16, **entry_kw)
        self.custom_slab_entry.grid(row=6, column=1, sticky="ew", pady=3)
        ttk.Label(lf_inputs, text="mm", style="Panel.TLabel").grid(row=6, column=2, sticky="w", padx=(4, 0), pady=3)

        ttk.Label(lf_inputs, text="Garage door rebate", style="Panel.TLabel").grid(row=7, column=0, sticky="w", padx=(0, 6), pady=3)
        self.rebate_mm_var = tk.StringVar(value="35")
        self.rebate_entry = tk.Entry(lf_inputs, textvariable=self.rebate_mm_var, width=16, **entry_kw)
        self.rebate_entry.grid(row=7, column=1, sticky="ew", pady=3)
        ttk.Label(lf_inputs, text="mm", style="Panel.TLabel").grid(row=7, column=2, sticky="w", padx=(4, 0), pady=3)

        self._toggle_custom_slab_height()

        # Export controls moved to the bottom-right action bar

        # Bind Enter to calculate for fast use
        self.bind("<Return>", lambda _e: self.on_calculate())

        # Safe live calculation bindings
        for _live_var in (self.boundary_var, self.length_var, self.tol_input_var, self.direction_var, self.slab_var, self.rebate_mm_var):
            try:
                _live_var.trace_add("write", lambda *_: self._safe_live_calculate())
            except Exception:
                pass

        # --------------------------------
        # FULL-WIDTH LOWER AREA: RESULTS + CANVAS
        # --------------------------------

        # Results row (command buttons now float over schematic)
        results_row = ttk.Frame(left, style="RightPane.TFrame")
        results_row.rowconfigure(0, weight=1)
        results_row.grid(row=0, column=3, sticky="nsew", padx=(10, 0), pady=0)
        results_row.columnconfigure(0, weight=1)

        results_card = tk.Frame(
            results_row,
            bg=CARD_BG,
            bd=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground=PANEL_BORDER,
            highlightcolor=PANEL_BORDER,
            padx=14,
            pady=10,
        )
        results_card.grid(row=0, column=0, sticky="nsew", padx=0)
        results_card.grid_columnconfigure(0, weight=1)
        results_card.grid_columnconfigure(1, weight=1)

        tk.Label(
            results_card,
            text="CALCULATION OUTPUT",
            bg=CARD_BG,
            fg=TEXT_DARK,
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        # Clean calculation output list — consistent plain text, no bold headline values.
        output_font = ("Segoe UI", 10)

        self.platform_var = tk.StringVar(value="Platform level: —")
        self.garage_slab_var = tk.StringVar(value="Garage slab level: —")
        self.length_result_var = tk.StringVar(value="Driveway length: —")
        self.rise_platform_var = tk.StringVar(value="Rise/Fall to platform: —")
        self.rebate_output_var = tk.StringVar(value="Garage door rebate: —")
        self.tolerance_output_var = tk.StringVar(value="Tolerance: 0 mm")
        self.status_output_var = tk.StringVar(value="Status: OK")

        output_vars = [
            self.platform_var,
            self.garage_slab_var,
            self.length_result_var,
            self.rise_platform_var,
            self.rebate_output_var,
            self.tolerance_output_var,
            self.status_output_var,
        ]

        for row_i, var in enumerate(output_vars, start=1):
            tk.Label(
                results_card,
                textvariable=var,
                bg=CARD_BG,
                fg=TEXT_DARK,
                font=output_font,
                anchor="w",
            ).grid(row=row_i, column=0, columnspan=2, sticky="w", pady=1)

        # Backwards-compatible variables used by older methods; not separately displayed.
        self.tol_var = self.tolerance_output_var
        self.sum_status_var = self.status_output_var
        self.sum_len_var = self.length_result_var
        self.sum_pf_var = self.platform_var
        self.sum_rf_var = self.rise_platform_var
        self.sum_tol_var = self.tolerance_output_var

        # --------------------------------
        # FULL-WIDTH SCHEMATIC VIEWPORT
        # --------------------------------
        self.ov_show_rl = tk.BooleanVar(value=True)
        self.ov_show_lengths = tk.BooleanVar(value=True)
        self.ov_show_grades = tk.BooleanVar(value=True)
        self.ov_show_labels = tk.BooleanVar(value=True)
        self.ov_show_ref = tk.BooleanVar(value=True)
        # Hidden compatibility flag retained for the Window menu command.
        # Profile visibility is always on; the dropdown selects its line style.
        self.ov_show_spline = tk.BooleanVar(value=True)
        self.profile_style_var = tk.StringVar(value="Spline Line")
        self.ov_show_slope_pct = tk.BooleanVar(value=False)

        # App-style profile output controls.
        layer_sep = tk.Frame(results_card, bg=PANEL_BORDER, height=1)
        layer_sep.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(10, 8))

        layer_panel = tk.Frame(
            results_card,
            bg="#111927",
            bd=0,
            highlightthickness=1,
            highlightbackground=PANEL_BORDER,
            highlightcolor=PANEL_BORDER,
            padx=10,
            pady=9,
        )
        layer_panel.grid(row=9, column=0, columnspan=2, sticky="ew")
        layer_panel.columnconfigure(0, weight=1)

        title_row = tk.Frame(layer_panel, bg="#111927")
        title_row.grid(row=0, column=0, sticky="ew", pady=(0, 7))
        title_row.columnconfigure(0, weight=1)
        tk.Label(
            title_row,
            text="PROFILE OUTPUT",
            bg="#111927",
            fg=TEXT_DARK,
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            title_row,
            text="DISPLAY",
            bg="#162438",
            fg=PRIMARY_BORDER,
            font=("Segoe UI", 8, "bold"),
            padx=7,
            pady=2,
        ).grid(row=0, column=1, sticky="e")

        layer_controls = tk.Frame(layer_panel, bg="#111927")
        layer_controls.grid(row=1, column=0, sticky="ew")
        layer_controls.columnconfigure(0, weight=1)
        layer_controls.columnconfigure(1, weight=1)

        layer_items = [
            ("RL Levels", self.ov_show_rl),
            ("Lengths", self.ov_show_lengths),
            ("Gradient Ratios", self.ov_show_grades),
            ("Zone Labels", self.ov_show_labels),
            ("Reference Lines", self.ov_show_ref),
            ("Slope Percentage", self.ov_show_slope_pct),
        ]
        for i, (label, variable) in enumerate(layer_items):
            cell = tk.Frame(
                layer_controls,
                bg="#162131",
                highlightthickness=1,
                highlightbackground="#2d3b4f",
                padx=7,
                pady=4,
            )
            cell.grid(row=i // 2, column=i % 2, sticky="ew", padx=(0, 5) if i % 2 == 0 else (5, 0), pady=3)
            cell.columnconfigure(0, weight=1)
            ttk.Checkbutton(
                cell,
                text=label,
                style="Panel.TCheckbutton",
                variable=variable,
                command=self._apply_overlays_and_redraw,
            ).grid(row=0, column=0, sticky="w")

        style_row = tk.Frame(
            layer_panel,
            bg="#0f1724",
            highlightthickness=1,
            highlightbackground="#2d3b4f",
            padx=8,
            pady=7,
        )
        style_row.grid(row=2, column=0, sticky="ew", pady=(7, 0))
        style_row.columnconfigure(1, weight=1)
        tk.Label(
            style_row,
            text="PROFILE STYLE",
            bg="#0f1724",
            fg=TEXT_MUTED,
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.profile_style_combo = ttk.Combobox(
            style_row,
            textvariable=self.profile_style_var,
            values=["Spline Line", "Straight Line"],
            state="readonly",
            style="Tight.TCombobox",
            width=18,
        )
        self.profile_style_combo.grid(row=0, column=1, sticky="ew")
        self.profile_style_combo.bind(
            "<<ComboboxSelected>>",
            lambda _event: self._apply_overlays_and_redraw(),
            add="+",
        )

        lf_canvas = tk.Frame(
            right,
            bg=CARD_BG,
            bd=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground=PANEL_BORDER,
            highlightcolor=PANEL_BORDER,
        )
        lf_canvas.grid(row=0, column=0, sticky="nsew")
        lf_canvas.columnconfigure(0, weight=1)
        lf_canvas.rowconfigure(1, weight=1)

        profile_banner = tk.Frame(lf_canvas, bg=CARD_BG, padx=8, pady=4)
        profile_banner.grid(row=0, column=0, sticky="ew")
        profile_banner.columnconfigure(0, weight=1)

        tk.Label(
            profile_banner,
            text="PROFILE SCHEMATIC // TRUE-SCALE VIEW",
            bg=CARD_BG,
            fg=TEXT_DARK,
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        self.canvas = tk.Canvas(lf_canvas, bg=WHITE, highlightthickness=0)
        self.canvas.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

        # Floating command buttons over the schematic viewport
        self.export_menu = tk.Menu(self, tearoff=0)
        self.export_menu.add_command(label="Export PDF", command=self.export_pdf)
        self.export_menu.add_command(label="Export PNG", command=self.export_png)
        self.export_menu.add_command(label="Export JPG", command=self.export_jpg)
        self.export_menu.add_command(label="Export PostScript (.ps)", command=self.export_postscript)
        self.export_menu.add_separator()
        self.export_menu.add_command(label="Export DXF (mm @ 1:1)", command=self.export_dxf_1_1)
        self.export_menu.add_command(label="Export DXF (mm @ 1:100)", command=self.export_dxf_1_100)

        self.commands_shadow = tk.Frame(lf_canvas, bg="#030712", bd=0, highlightthickness=0)
        self.commands_card = tk.Frame(
            lf_canvas,
            bg=WHITE,
            bd=0,
            relief="flat",
            highlightthickness=0,
            padx=0,
            pady=0,
        )
        self.commands_card.grid_columnconfigure(0, weight=1, uniform="floating_commands")
        self.commands_card.grid_columnconfigure(1, weight=1, uniform="floating_commands")

        self.calc_btn_bottom = ttk.Button(
            self.commands_card,
            text="Calculate",
            command=self.on_calculate,
            style="FloatingPrimary.TButton"
        )
        self.calc_btn_bottom.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.export_run_btn = ttk.Button(
            self.commands_card,
            text="Export ▼",
            style="FloatingSecondary.TButton",
            command=self.show_export_menu,
        )
        self.export_run_btn.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        # Floating viewport action buttons: bottom-right over the schematic.
        # Width is kept generous so the Calculate label never clips.
        self.commands_shadow.place(in_=self.canvas, relx=1.0, rely=1.0, anchor="se", x=-15, y=-15, width=310, height=46)
        self.commands_card.place(in_=self.canvas, relx=1.0, rely=1.0, anchor="se", x=-20, y=-20, width=310, height=46)
        self.commands_shadow.lift()
        self.commands_card.lift()

        self._install_button_effects(
            self.calc_btn_bottom,
            self.export_run_btn,
            self.btn_reset_defaults,
            self.btn_reset_clear,
            self.btn_profile_save,
            self.btn_profile_load,
            self.btn_profile_duplicate,
            self.btn_profile_rename,
            self.btn_profile_delete,
            self.btn_profile_export,
            self.btn_profile_import,
        )


        # No horizontal scroll: the graph always fits within the viewport.

        self._last_res = None
        self._clear_summary()
        # Bottom licence/disclaimer band removed.
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        # Live update on field exit (FocusOut) / Enter (no popup errors)
        for w in [self.boundary_entry, self.length_entry, self.tol_entry]:
            w.bind("<FocusOut>", lambda _e: self._compute_and_update(show_errors=False))
            w.bind("<Return>", lambda _e: self._compute_and_update(show_errors=False))

        self.direction_combo.bind("<<ComboboxSelected>>", lambda _e: self._compute_and_update(show_errors=False))
        self.slab_combo.bind("<<ComboboxSelected>>", lambda _e: self._compute_and_update(show_errors=False))
        self.custom_slab_entry.bind("<FocusOut>", lambda _e: self._compute_and_update(show_errors=False))
        self.custom_slab_entry.bind("<Return>", lambda _e: self._compute_and_update(show_errors=False))
        self.rebate_entry.bind("<FocusOut>", lambda _e: self._compute_and_update(show_errors=False))
        self.rebate_entry.bind("<Return>", lambda _e: self._compute_and_update(show_errors=False))

        # Custom zones: update when leaving a cell / changing dropdown
        if hasattr(self, "_custom_rows"):
            for row in self._custom_rows:
                # row layout: name_var, len_var, ratio_var, typ_var, name_entry, len_entry, ratio_entry, type_combo
                try:
                    name_entry, len_entry, ratio_entry, type_combo = row[4], row[5], row[6], row[7]
                    for ew in [name_entry, len_entry, ratio_entry]:
                        ew.bind("<FocusOut>", lambda _e: self._compute_and_update(show_errors=False))
                        ew.bind("<Return>", lambda _e: self._compute_and_update(show_errors=False))
                    type_combo.bind("<<ComboboxSelected>>", lambda _e: self._compute_and_update(show_errors=False))
                except Exception:
                    pass

        if hasattr(self, "customize_chk"):
            self.customize_chk.configure(command=lambda: [self._toggle_customize(), self._compute_and_update(show_errors=False)])

        self.after(50, self._sync_header_to_inputs)

    def _install_button_effects(self, *buttons):
        """Add subtle hover glow + press feedback to buttons."""
        self._button_fx = getattr(self, "_button_fx", {})
        for btn in buttons:
            if not btn:
                continue
            key = str(btn)
            if key in self._button_fx:
                continue
            self._button_fx[key] = {
                "base_padding": btn.cget("padding"),
                "style": str(btn.cget("style") or "TButton"),
            }
            try:
                btn.configure(cursor="hand2")
            except Exception:
                pass
            btn.bind("<Enter>", lambda e, b=btn: self._button_hover_on(b), add="+")
            btn.bind("<Leave>", lambda e, b=btn: self._button_hover_off(b), add="+")
            btn.bind("<ButtonPress-1>", lambda e, b=btn: self._button_press_fx(b), add="+")
            btn.bind("<ButtonRelease-1>", lambda e, b=btn: self._button_release_fx(b), add="+")

    def _button_hover_on(self, btn):
        try:
            btn.state(["active"])
        except Exception:
            pass

    def _button_hover_off(self, btn):
        try:
            btn.state(["!pressed", "!active"])
        except Exception:
            pass
        self._button_restore_padding(btn)

    def _button_press_fx(self, btn):
        fx = getattr(self, "_button_fx", {}).get(str(btn), {})
        base_padding = fx.get("base_padding")
        new_padding = self._pressed_padding(base_padding)
        if new_padding is not None:
            try:
                btn.configure(padding=new_padding)
            except Exception:
                pass

    def _button_release_fx(self, btn):
        self.after(90, lambda b=btn: self._button_restore_padding(b))

    def _button_restore_padding(self, btn):
        fx = getattr(self, "_button_fx", {}).get(str(btn), {})
        base_padding = fx.get("base_padding")
        if base_padding is None:
            return
        try:
            btn.configure(padding=base_padding)
        except Exception:
            pass

    @staticmethod
    def _pressed_padding(padding):
        try:
            if isinstance(padding, (tuple, list)):
                vals = [int(float(v)) for v in padding]
            else:
                vals = [int(float(v)) for v in str(padding).split()]
            if len(vals) == 1:
                px = max(0, vals[0] - 1)
                py = max(0, vals[0] - 1)
                return (px, py)
            if len(vals) == 2:
                return (max(0, vals[0] - 1), max(0, vals[1]))
            if len(vals) >= 4:
                return (max(0, vals[0] - 1), max(0, vals[1]), max(0, vals[2] - 1), max(0, vals[3]))
        except Exception:
            return None
        return None

    def _sync_header_to_inputs(self, _event=None):
        try:
            if not hasattr(self, "header") or not hasattr(self, "inputs_card"):
                return
            self.update_idletasks()
            target_w = self.inputs_card.winfo_width()
            if target_w <= 1:
                target_w = getattr(self, "_header_match_width", max(1, getattr(self, "_left_column_width", 430) - 24))
            # Keep the top-left DrivewayIQ logo/header section the same
            # visual width as the Inputs / Custom Zones card stack.
            self.header.configure(width=target_w)
        except Exception:
            pass

    def report_callback_exception(self, exc, val, tb):
        """Tkinter callback exception hook (prevents silent crashes)."""
        try:
            err_text = "".join(_traceback.format_exception(exc, val, tb))
        except Exception:
            err_text = "Unhandled Tkinter exception (failed to format traceback).\n"
        log_path = _write_runtime_crash_log(err_text)
        try:
            messagebox.showerror(
                "Unexpected error",
                "The app hit an unexpected error and wrote a crash log to:\n\n"
                f"{log_path}\n\n"
                "Please send that log back if you want me to diagnose the crash."
            )
        except Exception:
            pass

    def report_callback_exception(self, exc, val, tb):
        """Tkinter callback exceptions: write to runtime crash log."""
        try:
            base = os.path.dirname(os.path.abspath(__file__))
        except Exception:
            base = os.getcwd()
        path = os.path.join(base, "driveway_platform_runtime_crash.log")
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write("\n\n--- Tk callback exception ---\n")
                f.write(''.join(traceback.format_exception(exc, val, tb)))
        except Exception:
            pass
        # show user-friendly dialog
        try:
            messagebox.showerror("Error", f"An error occurred.\n\nA crash log was written to:\n{path}\n\n{val}")
        except Exception:
            pass

    def _update_auto_target_label(self):
        target_type = self.auto_target_type_var.get() if hasattr(self, "auto_target_type_var") else "Platform RL"
        label = "Garage Slab RL" if target_type == "Garage Slab RL" else "Platform RL"
        if hasattr(self, "auto_target_label"):
            self.auto_target_label.configure(text=label)

    def _toggle_auto_best_fit(self):
        enabled = bool(self.auto_best_fit_var.get()) if hasattr(self, "auto_best_fit_var") else False
        state = "normal" if enabled else "disabled"
        for widget_name in ("auto_boundary_entry", "auto_length_entry", "auto_target_rl_entry", "auto_boundary_len_entry", "auto_garage_len_entry"):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                try:
                    widget.configure(state=state)
                except Exception:
                    pass
        target_combo = getattr(self, "auto_target_type_combo", None)
        if target_combo is not None:
            try:
                target_combo.state(["!disabled"] if enabled else ["disabled"])
            except Exception:
                pass
        combo = getattr(self, "auto_transition_combo", None)
        if combo is not None:
            try:
                combo.state(["!disabled"] if enabled else ["disabled"])
            except Exception:
                pass
        # Manual custom zones are not used while auto best fit is active.
        if enabled and hasattr(self, "customize_var"):
            self.customize_var.set(False)
            try:
                self._set_custom_editor_enabled(False)
            except Exception:
                pass

    def _toggle_custom_slab_height(self):
        enabled = bool(self.use_custom_slab_var.get()) if hasattr(self, "use_custom_slab_var") else False
        try:
            if enabled:
                self.custom_slab_entry.configure(state="normal")
                if hasattr(self, "slab_combo"):
                    self.slab_combo.state(["disabled"])
            else:
                self.custom_slab_entry.configure(state="disabled")
                if hasattr(self, "slab_combo"):
                    self.slab_combo.state(["!disabled"])
        except Exception:
            pass

    def _on_canvas_resize(self, _evt):
        if self._last_res is not None:
            draw_schematic(self.canvas, self._last_res)
        try:
            self.commands_shadow.lift()
            self.commands_card.lift()
        except Exception:
            pass

    def _current_overlays(self) -> dict:
        return {
            "rl": bool(self.ov_show_rl.get()) if hasattr(self, "ov_show_rl") else True,
            "lengths": bool(self.ov_show_lengths.get()) if hasattr(self, "ov_show_lengths") else True,
            "grades": bool(self.ov_show_grades.get()) if hasattr(self, "ov_show_grades") else True,
            "labels": bool(self.ov_show_labels.get()) if hasattr(self, "ov_show_labels") else True,
            "ref": bool(self.ov_show_ref.get()) if hasattr(self, "ov_show_ref") else True,
            "spline": bool(self.ov_show_spline.get()) if hasattr(self, "ov_show_spline") else True,
            "straight_spline": (
                self.profile_style_var.get() == "Straight Line"
                if hasattr(self, "profile_style_var") else False
            ),
            "slope_pct": bool(self.ov_show_slope_pct.get()) if hasattr(self, "ov_show_slope_pct") else False,
        }

    def _apply_overlays_and_redraw(self):
        if self._last_res is None:
            return
        self._last_res["overlays"] = self._current_overlays()
        draw_schematic(self.canvas, self._last_res)

    def _update_summary(self, res: dict, status: str = "OK"):
        """Keep the output ribbon as a clean, consistent list.

        The main output values are set in _compute_and_update so they can include
        the active input values. This helper only updates the status line.
        """
        if hasattr(self, "status_output_var"):
            self.status_output_var.set(f"Status: {status}")
        elif hasattr(self, "sum_status_var"):
            self.sum_status_var.set(status)

    def _clear_summary(self, status: str = "OK"):
        if hasattr(self, "platform_var"):
            self.platform_var.set("Platform level: —")
            self.garage_slab_var.set("Garage slab level: —")
            self.length_result_var.set("Driveway length: —")
            self.rise_platform_var.set("Rise/Fall to platform: —")
            if hasattr(self, "rebate_output_var"):
                self.rebate_output_var.set("Garage door rebate: —")
            if hasattr(self, "tolerance_output_var"):
                self.tolerance_output_var.set("Tolerance: 0 mm")
            if hasattr(self, "status_output_var"):
                self.status_output_var.set(f"Status: {status}")

    def _compute_and_update(self, show_errors: bool):
        try:
            boundary = float(self.boundary_var.get().strip())
            length = float(self.length_var.get().strip())
            if length <= 0:
                raise ValueError("Driveway length must be > 0.")

            direction = self.direction_var.get()

            if hasattr(self, "use_custom_slab_var") and self.use_custom_slab_var.get():
                try:
                    slab_mm = int(round(float(self.custom_slab_mm_var.get().strip())))
                except Exception:
                    raise ValueError("Custom slab height must be a valid number in mm.")
                if slab_mm <= 0:
                    raise ValueError("Custom slab height must be greater than 0 mm.")
            else:
                slab_mm = SLAB_OPTIONS[self.slab_var.get()]

            # Tolerance (mm -> m)
            if hasattr(self, "tol_entry"):
                try:
                    tol_mm = float(self.tol_input_var.get().strip() or "0")
                except Exception:
                    tol_mm = 0.0
                self.tolerance_m = tol_mm / 1000.0

            try:
                rebate_mm = float(self.rebate_mm_var.get().strip() or "0")
            except Exception:
                raise ValueError("Rebate must be a valid number in mm.")
            if rebate_mm < 0:
                raise ValueError("Rebate cannot be negative.")
            rebate_m = rebate_mm / 1000.0

            custom_segments = None
            if getattr(self, 'custom_mode', False):
                # If Customize is OFF, keep defaults visible but locked
                if hasattr(self, 'customize_var') and (not self.customize_var.get()):
                    # ensure defaults are loaded
                    try:
                        self._custom_reset_defaults()
                    except Exception:
                        pass
                if hasattr(self, 'customize_var') and self.customize_var.get():
                    custom_segments = self._custom_get_segments()

            res = None
            if hasattr(self, "auto_best_fit_var") and self.auto_best_fit_var.get():
                try:
                    auto_boundary = float(self.auto_boundary_var.get().strip())
                    auto_length = float(self.auto_length_var.get().strip())
                    target_rl = float(self.auto_target_rl_var.get().strip())
                    target_rl_type = self.auto_target_type_var.get().strip()
                    boundary_grade_len = float(self.auto_boundary_len_var.get().strip())
                    garage_grade_len = float(self.auto_garage_len_var.get().strip())
                    transition_count = int(self.auto_transition_var.get().strip())
                except Exception:
                    raise ValueError("Auto best-fit inputs must contain valid numbers.")
                if target_rl_type not in ("Platform RL", "Garage Slab RL"):
                    raise ValueError("Select either Platform RL or Garage Slab RL as the target.")
                boundary = auto_boundary
                length = auto_length
                res = compute_best_fit(
                    boundary_rl=auto_boundary,
                    total_len=auto_length,
                    target_rl=target_rl,
                    target_rl_type=target_rl_type,
                    slab_mm=slab_mm,
                    rebate_m=rebate_m,
                    boundary_grade_len=boundary_grade_len,
                    garage_grade_len=garage_grade_len,
                    transition_count=transition_count,
                    direction=direction,
                )
            # If Customize is enabled, use the manual segments; otherwise use the built-in defaults
            elif hasattr(self, 'customize_var') and self.customize_var.get():
                res = compute_custom(boundary, direction, slab_mm, custom_segments, tolerance_m=self.tolerance_m, rebate_m=rebate_m)
            else:
                res = compute(boundary, length, direction, slab_mm, tolerance_m=self.tolerance_m, rebate_m=rebate_m)
            res["custom_mode"] = bool(self.custom_mode)
            res["overlays"] = self._current_overlays()

            self._last_res = res

            # Update headline results (top box)
            rise_to_platform = res["platform_rl"] - boundary
            self.platform_var.set(f"Platform level: RL {fmt(res['platform_rl'])} m")
            slab_label = "Garage slab level"
            if hasattr(self, "use_custom_slab_var") and self.use_custom_slab_var.get():
                slab_label = f"Garage slab level ({slab_mm} mm custom)"
            self.garage_slab_var.set(f"{slab_label}: RL {fmt(res['slab_step_rl'])} m")
            self.rise_platform_var.set(
                f"{'Rise' if rise_to_platform >= 0 else 'Fall'} to platform: {fmt(abs(rise_to_platform))} m"
            )
            self.length_result_var.set(f"Driveway length: {fmt(length)} m")
            self.rebate_output_var.set(f"Garage door rebate: {int(round(rebate_mm))} mm")
            self.tolerance_output_var.set(f"Tolerance: {int(round(self.tolerance_m * 1000))} mm")
            if res.get("auto_best_fit"):
                if res.get("best_fit_failed"):
                    self.status_output_var.set("Status: FAIL — " + str(res.get("best_fit_fail_reason", "Driveway profile is non-compliant.")))
                else:
                    self.status_output_var.set(
                        f"Status: Auto best fit OK — peak grade {res.get('best_fit_peak_grade', 0.0) * 100:.2f}% · max adjacent change {res['best_fit_max_grade_change'] * 100:.2f}%"
                    )
            else:
                self.status_output_var.set("Status: OK")

            draw_schematic(self.canvas, res)
            self._update_summary(res, status=("FAIL" if res.get("best_fit_failed") else "OK"))
        except Exception as e:
            # don't spam dialogs for live updates
            self._clear_summary(status=f"Error: {e}")
            if show_errors:
                messagebox.showerror("Error", str(e))

    def on_calculate(self):
        self._compute_and_update(show_errors=True)

    def show_export_menu(self):
        if not hasattr(self, "export_menu"):
            return

        self.update_idletasks()
        x = self.export_run_btn.winfo_rootx()
        y = self.export_run_btn.winfo_rooty() + self.export_run_btn.winfo_height()
        try:
            self.export_menu.tk_popup(x, y)
        finally:
            try:
                self.export_menu.grab_release()
            except Exception:
                pass

    def on_export_selected(self):
        self.show_export_menu()

    def copy_results(self):
        """Copies a clean text summary (headline + segments) to the clipboard."""
        if self._last_res is None:
            self.clipboard_clear()
            self.clipboard_append("No results yet. Click Calculate first.")
            return

        res = self._last_res

        lines = []
        lines.append(f"TOS (finish): {fmt(res['tos_rl'])} m")
        lines.append(f"Platform: {fmt(res['platform_rl'])} m")
        lines.append(f"ΔRL (total): {fmt(res['total_delta'])} m")
        lines.append(f"{res['maxmin']} PLATFORM INCLUDING 100MM’S TOLERANCE = {fmt(res['platform_rl'])} m")
        lines.append("")
        lines.append("SEGMENTS")
        lines.append("Zone\tLength(mm)\tGrade\tDir\tΔRL(m)")
        for seg in res["segments"]:
            d_rl = seg.delta_rl()
            direction = "FLAT" if (seg.sign == 0 or seg.ratio <= 0) else ("UP" if seg.sign > 0 else "DN")
            lines.append(
                f"{seg.name}\t{int(round(seg.length_m*1000))}\t1:{seg.ratio:g}\t{direction}\t{fmt(d_rl)}"
            )

        txt = "\n".join(lines)
        self.clipboard_clear()
        self.clipboard_append(txt)

    
    def export_postscript(self):
        """Export the visible schematic graph as a PostScript (.ps) file.

        This is vector-friendly (great for CAD/Illustrator/printing) and uses the
        canvas' native PostScript exporter (no Pillow required).
        """
        # Ensure we have up-to-date results / drawing
        if self._last_res is None:
            self.on_calculate()
            if self._last_res is None:
                return

        self.update_idletasks()

        path = filedialog.asksaveasfilename(
            title="Export PostScript",
            defaultextension=".ps",
            filetypes=[("PostScript", "*.ps"), ("All files", "*.*")],
        )
        if not path:
            return  # user cancelled

        try:
            # colormode="color" preserves fills/lines as seen on the canvas
            self.canvas.postscript(file=path, colormode="color")
            messagebox.showinfo("Export PostScript", f"Saved PostScript file to:\n{path}")
        except Exception as e:
            messagebox.showerror("Export PostScript", str(e))

    

    def export_pdf(self):
        """
        Export a TRUE-SCALE 1:100 PDF.

        Important:
        - This does NOT use  because that destroys real-world scale.
        - DXF geometry is built in paper millimetres at 1:100.
        - Matplotlib page size is set in physical millimetres converted to inches.
        - Axes fill the entire page, so 1 data unit = 1 paper millimetre.
        """
        if ezdxf is None:
            messagebox.showerror(
                "PDF Export Error",
                "PDF export requires the 'ezdxf' package.\n\n"
                "Install it with:\n"
                "    py -m pip install ezdxf"
            )
            return

        if self._last_res is None:
            self.on_calculate()
            if self._last_res is None:
                return

        self.update_idletasks()

        path = filedialog.asksaveasfilename(
            title="Export PDF - TRUE SCALE 1:100",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf"), ("All files", "*.*")]
        )
        if not path:
            return

        try:
            doc = self._build_dxf_document(scale=100)
            if doc is None:
                return

            import matplotlib.pyplot as plt
            from matplotlib.patches import Circle

            MM_PER_INCH = 25.4
            PT_PER_MM = 72.0 / MM_PER_INCH

            msp = doc.modelspace()

            # ------------------------------------------------------------
            # Collect extents in paper millimetres
            # ------------------------------------------------------------
            x_vals = []
            y_vals = []

            def _collect_xy(x: float, y: float):
                x_vals.append(float(x))
                y_vals.append(float(y))

            for entity in msp:
                dxftype = entity.dxftype()
                if dxftype == "LINE":
                    _collect_xy(entity.dxf.start[0], entity.dxf.start[1])
                    _collect_xy(entity.dxf.end[0], entity.dxf.end[1])
                elif dxftype == "LWPOLYLINE":
                    for p in entity.get_points("xy"):
                        _collect_xy(p[0], p[1])
                elif dxftype == "CIRCLE":
                    cx = float(entity.dxf.center[0])
                    cy = float(entity.dxf.center[1])
                    r = float(entity.dxf.radius)
                    _collect_xy(cx - r, cy - r)
                    _collect_xy(cx + r, cy + r)

            for item in getattr(doc, "_pdf_text_items", []):
                x = float(item.get("x", 0.0))
                y = float(item.get("y", 0.0))
                h = float(item.get("height", 2.0))
                # Approx allowance for text width so labels don't get cropped.
                txt = str(item.get("text", ""))
                _collect_xy(x, y)
                _collect_xy(x + max(6.0, len(txt) * h * 0.65), y + h * 1.5)
                _collect_xy(x - max(6.0, len(txt) * h * 0.20), y - h * 1.5)

            if not x_vals or not y_vals:
                raise ValueError("No PDF geometry was generated.")

            min_x, max_x = min(x_vals), max(x_vals)
            min_y, max_y = min(y_vals), max(y_vals)

            margin_mm = 15.0
            drawing_w = max_x - min_x
            drawing_h = max_y - min_y

            # TRUE crop-to-geometry page size (no forced A4)
            page_w_mm = drawing_w + margin_mm * 2.0
            page_h_mm = drawing_h + margin_mm * 2.0

            shift_x = margin_mm - min_x
            shift_y = margin_mm - min_y

            fig = plt.figure(
                figsize=(page_w_mm / MM_PER_INCH, page_h_mm / MM_PER_INCH),
                dpi=300,
            )
            ax = fig.add_axes([0, 0, 1, 1])
            ax.set_xlim(0, page_w_mm)
            ax.set_ylim(0, page_h_mm)
            ax.set_aspect("equal", adjustable="box")
            ax.axis("off")
            ax.set_facecolor("white")
            fig.patch.set_facecolor("white")

            def _tx(x): return float(x) + shift_x
            def _ty(y): return float(y) + shift_y

            def _plot_line(start, end, lw_mm=0.25):
                ax.plot(
                    [_tx(start[0]), _tx(end[0])],
                    [_ty(start[1]), _ty(end[1])],
                    color="black",
                    linewidth=lw_mm * PT_PER_MM,
                    solid_capstyle="round",
                )

            for entity in msp:
                dxftype = entity.dxftype()
                if dxftype == "LINE":
                    lw = 0.35 if entity.dxf.layer == "PROFILE" else 0.22
                    _plot_line(entity.dxf.start, entity.dxf.end, lw_mm=lw)
                elif dxftype == "LWPOLYLINE":
                    pts = list(entity.get_points("xy"))
                    if len(pts) >= 2:
                        xs = [_tx(p[0]) for p in pts]
                        ys = [_ty(p[1]) for p in pts]
                        lw = 0.35 if entity.dxf.layer == "PROFILE" else 0.22
                        ax.plot(xs, ys, color="black", linewidth=lw * PT_PER_MM, solid_capstyle="round")
                elif dxftype == "CIRCLE":
                    cx = _tx(entity.dxf.center[0])
                    cy = _ty(entity.dxf.center[1])
                    radius = float(entity.dxf.radius)
                    ax.add_patch(
                        Circle(
                            (cx, cy),
                            radius=radius,
                            fill=False,
                            edgecolor="black",
                            linewidth=0.18 * PT_PER_MM,
                        )
                    )

            def _map_alignment(align_name: str):
                align_name = (align_name or "LEFT").upper()
                if "CENTER" in align_name:
                    ha = "center"
                elif "RIGHT" in align_name:
                    ha = "right"
                else:
                    ha = "left"

                if "TOP" in align_name:
                    va = "top"
                elif "MIDDLE" in align_name:
                    va = "center"
                elif "BOTTOM" in align_name:
                    va = "bottom"
                else:
                    va = "baseline"
                return ha, va

            for item in getattr(doc, "_pdf_text_items", []):
                x = _tx(float(item["x"]))
                y = _ty(float(item["y"]))
                height_mm = float(item.get("height", 2.0))
                fontsize_pt = max(height_mm * PT_PER_MM, 3.5)
                ha, va = _map_alignment(item.get("align", "LEFT"))

                ax.text(
                    x,
                    y,
                    item["text"],
                    fontsize=fontsize_pt,
                    rotation=float(item.get("rotation", 0.0)),
                    ha=ha,
                    va=va,
                    family="DejaVu Sans",
                    color="black",
                )

            # DO NOT use  — it changes the PDF physical size
            # and breaks 1:100 scaling when imported into CAD.
            fig.savefig(path, format="pdf", dpi=300)
            plt.close(fig)

            messagebox.showinfo(
                "Export PDF",

                "Saved TRUE-SCALE 1:100 PDF to:\n"
                f"{path}\n\n"
                "CAD import check:\n"
                "A 6000 mm driveway should measure 60 mm in the imported PDF."
            )

        except ImportError:
            messagebox.showerror(
                "PDF Export Error",
                "True-scale PDF export requires matplotlib and ezdxf.\n\n"
                "Install / update with:\n"
                "    py -m pip install matplotlib ezdxf"
            )
        except Exception as e:
            messagebox.showerror("PDF Export Error", str(e))



    def _export_raster_from_dxf(self, path: str, image_format: str = "png", dpi: int = 300):
        """
        Export PNG/JPG from the same DXF geometry as the PDF export.

        This exports the drawing geometry, not a screen screenshot.
        Output is tightly cropped to the drawing extents + margin.
        """
        if ezdxf is None:
            messagebox.showerror(
                "Image Export Error",
                "PNG/JPG export requires the 'ezdxf' package.\n\n"
                "Install it with:\n"
                "    py -m pip install ezdxf"
            )
            return

        if self._last_res is None:
            self.on_calculate()
            if self._last_res is None:
                return

        try:
            doc = self._build_dxf_document(scale=100)
            if doc is None:
                return

            import matplotlib.pyplot as plt
            from matplotlib.patches import Circle

            MM_PER_INCH = 25.4
            PT_PER_MM = 72.0 / MM_PER_INCH
            msp = doc.modelspace()

            x_vals = []
            y_vals = []

            def _collect_xy(x: float, y: float):
                x_vals.append(float(x))
                y_vals.append(float(y))

            for entity in msp:
                dxftype = entity.dxftype()
                if dxftype == "LINE":
                    _collect_xy(entity.dxf.start[0], entity.dxf.start[1])
                    _collect_xy(entity.dxf.end[0], entity.dxf.end[1])
                elif dxftype == "LWPOLYLINE":
                    for p in entity.get_points("xy"):
                        _collect_xy(p[0], p[1])
                elif dxftype == "CIRCLE":
                    cx = float(entity.dxf.center[0])
                    cy = float(entity.dxf.center[1])
                    r = float(entity.dxf.radius)
                    _collect_xy(cx - r, cy - r)
                    _collect_xy(cx + r, cy + r)

            for item in getattr(doc, "_pdf_text_items", []):
                x = float(item.get("x", 0.0))
                y = float(item.get("y", 0.0))
                h = float(item.get("height", 2.0))
                txt = str(item.get("text", ""))
                _collect_xy(x, y)
                _collect_xy(x + max(6.0, len(txt) * h * 0.65), y + h * 1.5)
                _collect_xy(x - max(6.0, len(txt) * h * 0.20), y - h * 1.5)

            if not x_vals or not y_vals:
                raise ValueError("No image geometry was generated.")

            min_x, max_x = min(x_vals), max(x_vals)
            min_y, max_y = min(y_vals), max(y_vals)

            margin_mm = 15.0
            drawing_w = max_x - min_x
            drawing_h = max_y - min_y
            page_w_mm = drawing_w + margin_mm * 2.0
            page_h_mm = drawing_h + margin_mm * 2.0

            shift_x = margin_mm - min_x
            shift_y = margin_mm - min_y

            fig = plt.figure(
                figsize=(page_w_mm / MM_PER_INCH, page_h_mm / MM_PER_INCH),
                dpi=dpi,
            )
            ax = fig.add_axes([0, 0, 1, 1])
            ax.set_xlim(0, page_w_mm)
            ax.set_ylim(0, page_h_mm)
            ax.set_aspect("equal", adjustable="box")
            ax.axis("off")
            ax.set_facecolor("white")
            fig.patch.set_facecolor("white")

            def _tx(x): return float(x) + shift_x
            def _ty(y): return float(y) + shift_y

            def _plot_line(start, end, lw_mm=0.25):
                ax.plot(
                    [_tx(start[0]), _tx(end[0])],
                    [_ty(start[1]), _ty(end[1])],
                    color="black",
                    linewidth=lw_mm * PT_PER_MM,
                    solid_capstyle="round",
                )

            for entity in msp:
                dxftype = entity.dxftype()
                if dxftype == "LINE":
                    lw = 0.35 if entity.dxf.layer == "PROFILE" else 0.22
                    _plot_line(entity.dxf.start, entity.dxf.end, lw_mm=lw)
                elif dxftype == "LWPOLYLINE":
                    pts = list(entity.get_points("xy"))
                    if len(pts) >= 2:
                        xs = [_tx(p[0]) for p in pts]
                        ys = [_ty(p[1]) for p in pts]
                        lw = 0.35 if entity.dxf.layer == "PROFILE" else 0.22
                        ax.plot(xs, ys, color="black", linewidth=lw * PT_PER_MM, solid_capstyle="round")
                elif dxftype == "CIRCLE":
                    cx = _tx(entity.dxf.center[0])
                    cy = _ty(entity.dxf.center[1])
                    radius = float(entity.dxf.radius)
                    ax.add_patch(
                        Circle(
                            (cx, cy),
                            radius=radius,
                            fill=False,
                            edgecolor="black",
                            linewidth=0.18 * PT_PER_MM,
                        )
                    )

            def _map_alignment(align_name: str):
                align_name = (align_name or "LEFT").upper()
                if "CENTER" in align_name:
                    ha = "center"
                elif "RIGHT" in align_name:
                    ha = "right"
                else:
                    ha = "left"

                if "TOP" in align_name:
                    va = "top"
                elif "MIDDLE" in align_name:
                    va = "center"
                elif "BOTTOM" in align_name:
                    va = "bottom"
                else:
                    va = "baseline"
                return ha, va

            for item in getattr(doc, "_pdf_text_items", []):
                x = _tx(float(item["x"]))
                y = _ty(float(item["y"]))
                height_mm = float(item.get("height", 2.0))
                fontsize_pt = max(height_mm * PT_PER_MM, 3.5)
                ha, va = _map_alignment(item.get("align", "LEFT"))

                ax.text(
                    x,
                    y,
                    item["text"],
                    fontsize=fontsize_pt,
                    rotation=float(item.get("rotation", 0.0)),
                    ha=ha,
                    va=va,
                    family="DejaVu Sans",
                    color="black",
                )

            save_kwargs = {"format": image_format.lower(), "dpi": dpi}
            if image_format.lower() in ("jpg", "jpeg"):
                save_kwargs["pil_kwargs"] = {"quality": 95}
                fig.savefig(path, **save_kwargs)
            else:
                fig.savefig(path, **save_kwargs)

            plt.close(fig)

        except ImportError:
            messagebox.showerror(
                "Image Export Error",
                "PNG/JPG export requires matplotlib and ezdxf.\n\n"
                "Install / update with:\n"
                "    py -m pip install matplotlib ezdxf"
            )
        except Exception as e:
            messagebox.showerror("Image Export Error", str(e))

    def export_png(self):
        """Export a cropped 300 DPI PNG from the drawing geometry."""
        if self._last_res is None:
            self.on_calculate()
            if self._last_res is None:
                return

        path = filedialog.asksaveasfilename(
            title="Export PNG",
            defaultextension=".png",
            filetypes=[("PNG image", "*.png"), ("All files", "*.*")]
        )
        if not path:
            return

        self._export_raster_from_dxf(path, image_format="png", dpi=300)
        messagebox.showinfo("Export PNG", f"Saved PNG to:\n{path}")

    def export_jpg(self):
        """Export a cropped 300 DPI JPG from the drawing geometry."""
        if self._last_res is None:
            self.on_calculate()
            if self._last_res is None:
                return

        path = filedialog.asksaveasfilename(
            title="Export JPG",
            defaultextension=".jpg",
            filetypes=[("JPEG image", "*.jpg"), ("JPEG image", "*.jpeg"), ("All files", "*.*")]
        )
        if not path:
            return

        self._export_raster_from_dxf(path, image_format="jpg", dpi=300)
        messagebox.showinfo("Export JPG", f"Saved JPG to:\n{path}")


    def _build_dxf_document(self, scale: float):
        """Build the DXF document used by both DXF export and PDF export.

        scale=100 -> 1:100 (mm = real_mm / 100)
        scale=1   -> 1:1   (mm = real_mm)
        """
        if ezdxf is None:
                messagebox.showerror(
                    "DXF export unavailable",
                    "DXF export requires the 'ezdxf' package.\n\n"
                    "Install it with:\n"
                    "    py -m pip install ezdxf"
                )
                return


        # Ensure we have up-to-date results
        if self._last_res is None:
            self.on_calculate()
            if self._last_res is None:
                return

        res = self._last_res

        doc = ezdxf.new(dxfversion="R2010")
        doc.header["$INSUNITS"] = 4  # millimetres

        # --- Text style: Arial Narrow (fallback to Arial if CAD can't find it) ---
        # NOTE: AutoCAD/BricsCAD will substitute if the font isn't available.
        try:
            if "ARIALN" not in doc.styles:
                doc.styles.new("ARIALN", dxfattribs={"font": "arialn.ttf"})
        except Exception:
            # Most DXF templates already include DASHED; if not, CAD will substitute.
            pass

        msp = doc.modelspace()

        def to_mm(meters: float) -> float:
            # convert metres -> mm, then apply drawing scale (1:100 etc)
            return (meters * 1000.0) / float(scale)

        pts = res["points"]
        boundary_rl = pts[0][1]

        def x_of(st_m: float) -> float:
            return to_mm(st_m)

        def y_of(rl_m: float) -> float:
            # keep profile true by drawing RL relative to boundary (so boundary is y=0)
            return to_mm(rl_m - boundary_rl)

        # --- Layers (ACI colours chosen to match the sample monochrome look) ---
        def ensure_layer(name: str, color: int, linetype=None):
            if name in doc.layers:
                return
            attribs = {"color": color}
            if linetype:
                attribs["linetype"] = linetype
            doc.layers.new(name=name, dxfattribs=attribs)

        ensure_layer("INK", 7)                    # black/white
        ensure_layer("GUIDES", 95, "DASHED")
        ensure_layer("POINTS", 2)                  # Archicad Pen 2 (gradient change point circles)  # Archicad: maps to Pen 95 in most DXF translators        # light grey dashed
        ensure_layer("PROFILE", 4)                 # Archicad Pen 3
        ensure_layer("SLAB", 4)                    # Archicad Pen 3
        ensure_layer("ZONES", 3)
        ensure_layer("DRAIN", 4)                   # Archicad Pen 3 (zone lines)

        # --- Derived geometry ---
        y_profile = [y_of(p[1]) for p in pts]
        plat_y = y_of(res["platform_rl"])
        tos_y = y_of(res["tos_rl"])
        slab_step_y = y_of(res.get("slab_step_rl", res["tos_rl"]))

        y_min = min(y_profile + [plat_y, tos_y, slab_step_y])
        y_max = max(y_profile + [plat_y, tos_y, slab_step_y])

        # Text heights: aim for plotted sizes that match the sample.
        # At 1:100 we want ~2.5mm on paper -> 250mm in model (because model is scaled 1:100).
        # Our DXF is already *scaled*, so use paper-mm values directly.
        txt_small = 1.8  # amended per request
        ZONE_LENGTH_OFFSET = 1.0  # locked drop for zone length text
        GRADIENT_EXTRA_OFFSET = 1.65  # locked drop for gradient text
        txt_med = 2.5  # amended per request
        PLATFORM_TEXT_OFFSET_MULT = 1.70  # locked platform text offset multiplier
        def PLATFORM_TEXT_Y(plat_y, txt_med):
            return plat_y - (txt_med * PLATFORM_TEXT_OFFSET_MULT)

        txt_big = 2.5  # amended per request
        txt_rl = 1.5  # adjusted per request   # top RL labels (per request)

        style_name = "ARIALN" if "ARIALN" in doc.styles else "STANDARD"
        pdf_text_items = []
        doc._pdf_text_items = pdf_text_items

        def add_text(s: str, x: float, y: float, h: float, rot: float = 0.0,
                     align=ezdxf.enums.TextEntityAlignment.LEFT, layer: str = "INK"):
            t = msp.add_text(
                s,
                dxfattribs={"height": h, "layer": layer, "style": style_name, "rotation": rot},
            )
            t.set_placement((x, y), align=align)
            pdf_text_items.append({
                "text": s,
                "x": x,
                "y": y,
                "height": h,
                "rotation": rot,
                "align": getattr(align, "name", str(align)),
                "layer": layer,
            })
            return t

        # --- Boundary line + label ---
        # place boundary at x=0
        boundary_x = 0.0
        # stop at the lower of (y=0 datum) or platform datum, matching the on-screen logic
        origin_y = y_of(pts[0][1])  # = 0
        y_stop = origin_y if (res["platform_rl"] >= pts[0][1]) else plat_y
        msp.add_line((boundary_x, y_max), (boundary_x, y_stop), dxfattribs={"layer": "ZONES"})  # Archicad Pen 3  # trimmed: no upper stub

        add_text(
            "BOUNDARY",
            (((boundary_x - 12.0 + 6.0) + 2.0) + 1.5), ((((y_max + y_stop + 2.0 + 2.0 + 1.5)))) / 2.0,
            2.0, rot=90.0,
            align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER,
            layer="INK",
        )

        # --- Profile polyline + points ---
        pl_pts = [(x_of(st), y_of(rl)) for (st, rl) in pts]
        msp.add_lwpolyline(
            pl_pts,
            dxfattribs={
                "layer": "PROFILE",
                "lineweight": 35,  # 0.35mm plotted thickness for driveway profile

            }
        )


        # 35mm step down from driveway end (TOS) to slab top
        msp.add_line(
            (x_of(pts[-1][0]), tos_y),
            (x_of(pts[-1][0]), slab_step_y),
            dxfattribs={"layer": "PROFILE"}
        )

        # point markers (open circles)
        r_pt = max(0.8, txt_small * 0.35) * 0.5
        for (st, rl) in pts:
            x = x_of(st)
            y = y_of(rl)
            msp.add_circle((x, y), radius=r_pt, dxfattribs={"layer": "POINTS"})

        
        # --- Horizontal datum lines: origin RL and platform RL (dashed) ---
        end_x = x_of(pts[-1][0])
        # extra projection to the right (like the sample), ~3.5m real
        proj_real_mm = 3500.0
        proj_x = (proj_real_mm / float(scale))

        # REMOVED: origin RL horizontal line (per request)
        # REMOVED: platform RL horizontal line (per request)

        # --- Slab rectangle (outline only, matching sample) ---
        slab_w_real_mm = 4500.0
        slab_w = slab_w_real_mm / float(scale)
        slab_x0 = end_x
        slab_x1 = end_x + slab_w
        slab_y0 = slab_step_y
        slab_y1 = plat_y
        msp.add_lwpolyline(
            [(slab_x0, slab_y0), (slab_x1, slab_y0), (slab_x1, slab_y1), (slab_x0, slab_y1), (slab_x0, slab_y0)],
            dxfattribs={"layer": "SLAB"},
        )

        # --- Strip drain box (downslope only): match viewport (100x100mm, below profile, touching RL) ---
        if res.get("direction") == "Down from boundary":
            drain_start_m = None
            drain_end_m = None
            cur_st = 0.0
            for s in res.get("segments", []):
                st0 = cur_st
                st1 = cur_st + s.length_m
                if getattr(s, "sign", 1) == 0 and "DRAIN" in s.name:
                    drain_start_m, drain_end_m = st0, st1
                    break
                cur_st = st1

            if drain_start_m is not None and drain_end_m is not None:
                x0 = x_of(drain_start_m)
                x1 = x_of(drain_end_m)
                drain_rl = next((rl for (st, rl) in pts if abs(st - drain_start_m) < 1e-9), pts[-1][1])
                y_top = y_of(drain_rl)  # profile line at drain (TOP of box touches this)
                box_size_real_mm = 100.0  # true 100mm
                box_h = box_size_real_mm / float(scale)  # scale to drawing units
                y_bottom = y_top - box_h  # BELOW the profile (DXF +Y is up)

                # Box outline
                msp.add_lwpolyline(
                    [(x0, y_top), (x1, y_top), (x1, y_bottom), (x0, y_bottom), (x0, y_top)],
                    dxfattribs={"layer": "DRAIN"},
                )

                # Text labels centered under the box (like viewport)
                add_text(
                    "DRAIN",
                    (x0 + x1) / 2.0,
                    (y_bottom - (txt_small * 1.2)) - 1.0,
                    txt_small,
                    align=ezdxf.enums.TextEntityAlignment.TOP_CENTER,
                    layer="INK",
                )
                add_text(
                    "100mm",
                    (x0 + x1) / 2.0,
                    (y_bottom - (txt_small * 1.2) - (txt_small * 1.4)) - 1.0,
                    txt_small,
                    align=ezdxf.enums.TextEntityAlignment.TOP_CENTER,
                    layer="INK",
                )


        # --- Labels at slab / platform (snapped to edges, like reference) ---
        y_platform_text = PLATFORM_TEXT_Y(plat_y, txt_med)  # locked shared Y for PLATFORM + RISE/FALL
        # Snap GARAGE SLAB text to slab TOP edge (just above the top line)
        add_text(
            f"GARAGE SLAB - RL {res.get('slab_step_rl', pts[-1][1]):.3f}",
            end_x + 6.0 - 5.0, slab_step_y + (1.8 * 0.60),
            txt_med,
            align=ezdxf.enums.TextEntityAlignment.LEFT,
            layer="INK",
        )
        # Snap PLATFORM text to underside of the platform line (just below the line)
        add_text(
            f"PLATFORM - RL {res['platform_rl']:.3f}",
            end_x + 6.0 - 5.0, y_platform_text,  # top of text just under platform line
            txt_med,
            align=ezdxf.enums.TextEntityAlignment.TOP_LEFT,
            layer="INK",
        )

        # --- Rise/Fall (compact, near boundary like reference) ---
        d_pf = res["platform_rl"] - pts[0][1]
        rf_txt = ("RISE TO PLATFORM " if d_pf >= 0 else "FALL TO PLATFORM - ") + f"({abs(d_pf):.3f} m)"
        add_text(
            rf_txt,
            boundary_x, (rf_y := (origin_y - (txt_med * PLATFORM_TEXT_OFFSET_MULT)) if (res.get("direction") == "Up from boundary") else y_platform_text),
            1.8,
            align=ezdxf.enums.TextEntityAlignment.LEFT,
            layer="INK",
        )

        # --- Slab thickness note (no leader) ---
        # Bracketed note placed above the slab, offset slightly left/down per request.
        slab_thk_mm = int(res.get("slab_mm", 0))
        slab_note_core = f"SLAB THK {slab_thk_mm} mm" if slab_thk_mm else "SLAB THK"
        slab_note = f"({slab_note_core})"

        # Text position (offset above and to the right of the slab top-left corner)
        note_x = slab_x0 + (max(12.0, txt_med * 6.0)) - 5.0  # move left 5 units
        note_y = slab_y0 + (max(10.0, txt_med * 6.0)) - 5.0  # move down 5 units

        # Note text (size 2mm on paper)
        add_text(
            slab_note,
            note_x, note_y,
            2.0,
            align=ezdxf.enums.TextEntityAlignment.LEFT,
            layer="INK",
        )

# --- Bottom title block text (sample) ---
        add_text(
            "MAXIMUM DRIVEWAY GRADIENT",
            boundary_x + 0.0, (((y_min - 20.0 + 7.0 + 3.0))),
            txt_big,
            align=ezdxf.enums.TextEntityAlignment.LEFT,
            layer="INK",
        )
        add_text(
            "SCALE 1:100",
            boundary_x + 0.0, (((y_min - 34.0 + 19.0 + 1.0))),
            txt_big,
            align=ezdxf.enums.TextEntityAlignment.LEFT,
            layer="INK",
        )

        # ==========================================================
        # TOP BAND: RL labels + segment length/grade (match reference layout)
        # ==========================================================
        # Reference-like stacking:
        #   RL (top)
        #   length (above dim line)
        #   dim line
        #   ratio (below dim line)
        dim_y_line = y_max + 6.0  # lowered zone band again by same amount  # lowered zone band per request
        rl_y = dim_y_line + 11.0 - 5.0  # RL text lowered by 5 units
        len_y = dim_y_line + 2.0 - ZONE_LENGTH_OFFSET  # lowered zone length text by 3 units
        ratio_y = dim_y_line - (txt_small * 0.20) - GRADIENT_EXTRA_OFFSET  # dropped gradient values by additional 0.4  # dropped gradient values by additional 0.75  # dropped gradient values by 0.5  # snap gradient text to underside of zone line
        zone_name_y = ratio_y - (txt_small * 1.55)


        # Continuous line through all zones (per markup)
        msp.add_line(
            (x_of(0.0), dim_y_line),
            (x_of(pts[-1][0]), dim_y_line),
            dxfattribs={"layer": "ZONES"},
        )
        # RL labels (above each guide line)
        for i, (st, rl) in enumerate(pts):
            # Suppress RL at RHS of drain (second-last point) for downslope only
            if res.get("direction") == "Down from boundary" and i == len(pts) - 2:
                continue

            add_text(
                f"RL {rl:.3f}",
                x_of(st),
                rl_y - 1.0,
                txt_rl,
                align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER,
                layer="INK",
            )

        # Segment dimension lines with length + ratio
        # Simple drafting look: underline + two stacked texts (length above, ratio below).
        segments = res["segments"]
        # build station list from segments to ensure the "varies" regions align
        seg_starts = []
        cur = 0.0
        for s in segments:
            seg_starts.append(cur)
            cur += s.length_m
        seg_ends = seg_starts[1:] + [pts[-1][0]]

        for s, st0, st1 in zip(segments, seg_starts, seg_ends):

            x0, x1 = x_of(st0), x_of(st1)
            # dimension line
            # (top dimension line removed per request)
# end ticks
            msp.add_line((x0, dim_y_line - 2.0), (x0, dim_y_line + 2.0), dxfattribs={"layer": "ZONES"})
            msp.add_line((x1, dim_y_line - 2.0), (x1, dim_y_line + 2.0), dxfattribs={"layer": "ZONES"})

            cx = (x0 + x1) / 2.0
            if getattr(s, "sign", 1) != 0:
                length_txt = f"{int(round(s.length_m * 1000)):,}"
                add_text(
                    length_txt,
                    cx, len_y,
                    txt_small,
                    align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER,
                    layer="INK",
                )
# (underline removed per request)
            if getattr(s, "sign", 1) != 0:
                slope_txt = (f"1:{int(s.ratio)}" if float(s.ratio).is_integer() else f"1:{s.ratio:g}")
                add_text(
                    slope_txt,
                    cx, ratio_y,
                    txt_small,
                    align=ezdxf.enums.TextEntityAlignment.TOP_CENTER,
                    layer="INK",
                )
            else:
                add_text(
                    "FLAT",
                    cx, ratio_y,
                    txt_small,
                    align=ezdxf.enums.TextEntityAlignment.TOP_CENTER,
                    layer="INK",
                )

            zone_name = (getattr(s, "name", "") or "").strip()
            if zone_name:
                add_text(
                    zone_name,
                    cx, zone_name_y,
                    txt_small,
                    align=ezdxf.enums.TextEntityAlignment.TOP_CENTER,
                    layer="INK",
                )

        return doc

    def _dxf_common(self, path: str, scale: float):
        """Internal helper: export DXF in millimetres, scaled."""
        doc = self._build_dxf_document(scale)
        if doc is None:
            return
        doc.saveas(path)

    def export_dxf_1_100(self):
        """Export DXF in millimetres, scaled 1:100."""
        path = filedialog.asksaveasfilename(
            title="Export DXF (mm @ 1:100)",
            defaultextension=".dxf",
            filetypes=[("DXF", "*.dxf"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            self._dxf_common(path, scale=100)
            messagebox.showinfo("Export DXF", f"Saved DXF file to:\n{path}")
        except Exception:
            _write_crash_log()
            messagebox.showerror("Export DXF", "DXF export failed. See startup_crash.log for details.")

    def export_dxf_1_1(self):
        """Export DXF in millimetres at 1:1 (full size)."""
        path = filedialog.asksaveasfilename(
            title="Export DXF (mm @ 1:1)",
            defaultextension=".dxf",
            filetypes=[("DXF", "*.dxf"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            self._dxf_common(path, scale=1)
            messagebox.showinfo("Export DXF", f"Saved DXF file to:\n{path}")
        except Exception:
            _write_crash_log()
            messagebox.showerror("Export DXF", "DXF export failed. See startup_crash.log for details.")

    def _safe_live_calculate(self):
        """Live calculation wrapper used by input field traces."""
        try:
            self.after_cancel(getattr(self, "_live_calc_after_id", ""))
        except Exception:
            pass
        try:
            self._live_calc_after_id = self.after(300, self.on_calculate)
        except Exception:
            pass

    # -----------------------------
    # Saved profile helpers
    # -----------------------------
    def _profiles_path(self) -> str:
        """Local JSON file used to store named driveway profiles beside the script."""
        try:
            base = os.path.dirname(os.path.abspath(__file__))
        except Exception:
            base = os.getcwd()
        return os.path.join(base, "drivewayiq_profiles.json")

    def _load_profiles_file(self) -> dict:
        path = self._profiles_path()
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    def _save_profiles_file(self, profiles: dict) -> None:
        path = self._profiles_path()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(profiles, f, indent=2, sort_keys=True)

    def _refresh_profile_combo(self) -> None:
        if not hasattr(self, "profile_combo"):
            return
        profiles = self._load_profiles_file()
        names = sorted(profiles.keys(), key=str.lower)
        self.profile_combo.configure(values=names)
        if self.profile_select_var.get() not in names:
            self.profile_select_var.set(names[0] if names else "")

    def _collect_profile_data(self) -> dict:
        rows = []
        for row in getattr(self, "_custom_rows", []):
            name_var, len_var, ratio_var, typ_var = row[:4]
            rows.append({
                "name": name_var.get(),
                "length_mm": len_var.get(),
                "ratio": ratio_var.get(),
                "type": typ_var.get(),
            })

        return {
            "boundary_level": self.boundary_var.get(),
            "driveway_length": self.length_var.get(),
            "direction": self.direction_var.get(),
            "tolerance_mm": self.tol_input_var.get(),
            "slab_type": self.slab_var.get(),
            "use_custom_slab": bool(self.use_custom_slab_var.get()),
            "custom_slab_mm": self.custom_slab_mm_var.get(),
            "rebate_mm": self.rebate_mm_var.get(),
            "customize": bool(self.customize_var.get()),
            "profile_notes": self.profile_notes_var.get() if hasattr(self, "profile_notes_var") else "",
            "custom_rows": rows,
        }

    def _apply_profile_data(self, data: dict) -> None:
        self.boundary_var.set(str(data.get("boundary_level", "10.000")))
        self.length_var.set(str(data.get("driveway_length", "6.0")))

        direction = data.get("direction", "Up from boundary")
        if direction in ("Up from boundary", "Down from boundary"):
            self.direction_var.set(direction)

        self.tol_input_var.set(str(data.get("tolerance_mm", "0")))

        slab_type = data.get("slab_type", list(SLAB_OPTIONS.keys())[0])
        if slab_type in SLAB_OPTIONS:
            self.slab_var.set(slab_type)

        self.use_custom_slab_var.set(bool(data.get("use_custom_slab", False)))
        self.custom_slab_mm_var.set(str(data.get("custom_slab_mm", "")))
        self.rebate_mm_var.set(str(data.get("rebate_mm", "35")))

        if hasattr(self, "profile_notes_var"):
            self.profile_notes_var.set(str(data.get("profile_notes", "")))

        self.customize_var.set(bool(data.get("customize", False)))

        rows = data.get("custom_rows", [])
        for i, row in enumerate(getattr(self, "_custom_rows", [])):
            name_var, len_var, ratio_var, typ_var = row[:4]
            if i < len(rows):
                src = rows[i] if isinstance(rows[i], dict) else {}
                name_var.set(str(src.get("name", "")))
                len_var.set(str(src.get("length_mm", "")))
                ratio_var.set(str(src.get("ratio", "")))
                tp = str(src.get("type", "FALL")).upper()
                typ_var.set(tp if tp in ("FALL", "RISE", "FLAT") else "FALL")
            else:
                name_var.set("")
                len_var.set("")
                ratio_var.set("")
                typ_var.set("FALL")

        self._toggle_custom_slab_height()
        self._set_custom_editor_enabled(bool(self.customize_var.get()))
        self._compute_and_update(show_errors=False)

    def _profile_save_current(self) -> None:
        name = self.profile_name_var.get().strip()
        if not name:
            messagebox.showerror("Save profile", "Enter a profile name first.")
            return

        profiles = self._load_profiles_file()
        replacing = name in profiles
        if replacing:
            ok = messagebox.askyesno("Save profile", f"Replace existing profile?\\n\\n{name}")
            if not ok:
                return

        data = self._collect_profile_data()
        if not data.get("driveway_length"):
            messagebox.showerror("Validation","Driveway length missing")
            return
        profiles[name] = data
        self._save_profiles_file(profiles)
        self.profile_select_var.set(name)
        self._refresh_profile_combo()
        messagebox.showinfo("Save profile", f"Saved profile:\\n{name}")

    def _profile_load_selected(self) -> None:
        name = self.profile_select_var.get().strip()
        if not name:
            messagebox.showerror("Load profile", "Select a saved profile first.")
            return

        profiles = self._load_profiles_file()
        data = profiles.get(name)
        if not isinstance(data, dict):
            messagebox.showerror("Load profile", "Selected profile could not be loaded.")
            self._refresh_profile_combo()
            return

        self.profile_name_var.set(name)
        self._apply_profile_data(data)

    def _profile_delete_selected(self) -> None:
        name = self.profile_select_var.get().strip()
        if not name:
            messagebox.showerror("Delete profile", "Select a saved profile first.")
            return

        ok = messagebox.askyesno("Delete profile", f"Delete saved profile?\\n\\n{name}")
        if not ok:
            return

        profiles = self._load_profiles_file()
        if name in profiles:
            del profiles[name]
            self._save_profiles_file(profiles)

        self.profile_select_var.set("")
        self.profile_name_var.set("")
        self._refresh_profile_combo()

    
    def _profile_duplicate(self):
        name = self.profile_select_var.get().strip()
        if not name: return
        profiles = self._load_profiles_file()
        new_name = name + " (copy)"
        profiles[new_name] = profiles[name]
        self._save_profiles_file(profiles)
        self._refresh_profile_combo()

    def _profile_rename(self):
        old = self.profile_select_var.get().strip()
        new = self.profile_name_var.get().strip()
        if not old or not new: return
        profiles = self._load_profiles_file()
        profiles[new] = profiles.pop(old)
        self._save_profiles_file(profiles)
        self._refresh_profile_combo()

    def _profile_export(self):
        path = self._profiles_path()
        messagebox.showinfo("Export", f"Profiles saved at:\n{path}")

    def _profile_import(self):
        messagebox.showinfo("Import", "Place JSON file in app folder to load.")
# -----------------------------
    # Custom mode helpers
    # -----------------------------
    def _custom_reset_defaults(self):
        """Populate the custom table with the standard zones for the selected direction."""
        if not getattr(self, "custom_mode", False):
            return

        direction = self.direction_var.get()
        segs = build_segments(6.0, direction)  # length is replaced by user anyway; this is a template

        # Map template into rows
        template = []
        for s in segs:
            if "DRAIN" in s.name.upper():
                typ = "FLAT"
                rt = ""
            else:
                typ = "FLAT" if s.ratio <= 0 else ("RISE" if s.sign > 0 else "FALL")
                rt = int(round(s.ratio)) if s.ratio > 0 else ""
            template.append((s.name, int(round(s.length_m * 1000)), rt, typ))

        # Fill rows, clear remaining
        for i, row in enumerate(self._custom_rows):
            (name_var, len_var, ratio_var, typ_var) = row[:4]
            if i < len(template):
                nm, ln, rt, tp = template[i]
                name_var.set(nm)
                len_var.set(str(ln))
                ratio_var.set("" if rt == "" else str(rt))
                typ_var.set(tp)
            else:
                name_var.set("")
                len_var.set("")
                ratio_var.set("")
                typ_var.set("FALL")
    def _set_custom_editor_enabled(self, enabled: bool):
        """Enable/disable custom zone row widgets and reset buttons."""
        # Enable/disable row widgets
        for (name_var, len_var, ratio_var, typ_var, name_entry, len_entry, ratio_entry, type_combo) in getattr(self, "_custom_rows", []):
            state = "normal" if enabled else "disabled"
            try:
                name_entry.configure(state=("normal" if enabled else "disabled"))
                len_entry.configure(state=("normal" if enabled else "disabled"))
                if enabled and typ_var.get() != "FLAT":
                    ratio_entry.configure(state="normal")
                else:
                    ratio_entry.configure(state="disabled")
                type_combo.state(["!disabled"] if enabled else ["disabled"])
            except Exception:
                name_entry.configure(state=state)
                len_entry.configure(state=state)
                if enabled and typ_var.get() != "FLAT":
                    ratio_entry.configure(state="normal")
                else:
                    ratio_entry.configure(state="disabled")
                type_combo.configure(state="readonly" if enabled else "disabled")

        # Enable/disable reset buttons (if present)
        if hasattr(self, "btn_reset_defaults"):
            try:
                self.btn_reset_defaults.state(["!disabled"] if enabled else ["disabled"])
            except Exception:
                self.btn_reset_defaults.configure(state=("normal" if enabled else "disabled"))
        if hasattr(self, "btn_reset_clear"):
            try:
                self.btn_reset_clear.state(["!disabled"] if enabled else ["disabled"])
            except Exception:
                self.btn_reset_clear.configure(state=("normal" if enabled else "disabled"))

    def _on_customize_toggle(self):
        enabled = bool(self.customize_var.get())
        if not enabled:
            # Revert to direction defaults and lock editing
            self._custom_reset_defaults()
        self._set_custom_editor_enabled(enabled)



    
    def _custom_clear_all(self):
        """Clear all custom zone inputs back to blank."""
        for row in self._custom_rows:
            (name_var, len_var, ratio_var, typ_var) = row[:4]
            name_var.set("")
            len_var.set("")
            ratio_var.set("")
            typ_var.set("FALL")

    def _custom_get_segments(self):
        """Read segments from the custom table. Raises ValueError on invalid inputs."""
        segs = []
        for row in self._custom_rows:
            (name_var, len_var, ratio_var, typ_var) = row[:4]
            name = name_var.get().strip()
            if not name:
                continue

            try:
                length_mm = float(len_var.get())
            except Exception:
                raise ValueError(f"Invalid length for {name}. Use mm (e.g. 1000).")

            if length_mm <= 0:
                raise ValueError(f"Length must be > 0 for {name}.")

            tp = typ_var.get().strip().upper()
            if tp == "FLAT":
                ratio = 0.0
                sign = 0
            else:
                try:
                    ratio = float(ratio_var.get())
                except Exception:
                    raise ValueError(f"Invalid gradient for {name}. Use the denominator only (e.g. 20 for 1:20).")
                if ratio <= 0:
                    raise ValueError(f"Gradient must be > 0 for {name}.")
                sign = 1 if tp == "RISE" else -1

            segs.append(Segment(name=name, length_m=length_mm / 1000.0, ratio=ratio, sign=sign))
        if not segs:
            raise ValueError("Add at least one custom zone row.")
        return segs



    
class App(tk.Tk):
    def __init__(self):
        super().__init__()

        self.configure(bg="#0d1117")
        self.title("DrivewayIQ PRO - Driveway Gradient Calculator")
        self.geometry("1365x900")
        self.minsize(1180, 760)

        # Main calculator pane. Stored as self.pane so the menu can safely call
        # existing app actions without duplicating calculator logic.
        self.pane = CalculatorPane(self, tolerance_m=0.0, custom_mode=True)
        self.pane.pack(fill="both", expand=True)

        # Placeholder top menu system. Items either call existing functions or
        # show a simple placeholder message so the menu structure is ready for
        # future commands.
        self._build_menu_system()

    def _build_menu_system(self) -> None:
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New Profile", command=self._menu_new_profile)
        file_menu.add_command(label="Open Profile", command=self._menu_open_profile)
        file_menu.add_command(label="Save Profile", command=self._menu_save_profile)
        file_menu.add_command(label="Save As...", command=self._menu_save_as_profile)
        file_menu.add_separator()
        file_menu.add_command(label="Export DXF", command=self._menu_export_dxf)
        file_menu.add_command(label="Export PDF", command=self._menu_export_pdf)
        file_menu.add_command(label="Export PNG", command=self._menu_export_png)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="Undo", command=lambda: self._menu_placeholder("Undo"))
        edit_menu.add_command(label="Redo", command=lambda: self._menu_placeholder("Redo"))
        edit_menu.add_separator()
        edit_menu.add_command(label="Copy", command=lambda: self._menu_placeholder("Copy"))
        edit_menu.add_command(label="Paste", command=lambda: self._menu_placeholder("Paste"))
        edit_menu.add_separator()
        edit_menu.add_command(label="Reset Inputs", command=self._menu_reset_inputs)
        menubar.add_cascade(label="Edit", menu=edit_menu)

        window_menu = tk.Menu(menubar, tearoff=0)
        window_menu.add_command(label="Toggle Zone Names", command=lambda: self._toggle_overlay("ov_show_labels"))
        window_menu.add_command(label="Toggle RL Labels", command=lambda: self._toggle_overlay("ov_show_rl"))
        window_menu.add_command(label="Toggle Average Spline", command=lambda: self._toggle_overlay("ov_show_spline"))
        window_menu.add_separator()
        window_menu.add_command(label="Reset Layout", command=self._menu_reset_layout)
        menubar.add_cascade(label="Window", menu=window_menu)

        options_menu = tk.Menu(menubar, tearoff=0)
        options_menu.add_command(label="Preferences", command=lambda: self._menu_placeholder("Preferences"))
        options_menu.add_command(label="Units", command=lambda: self._menu_placeholder("Units"))
        options_menu.add_command(label="Colours", command=lambda: self._menu_placeholder("Colours"))
        options_menu.add_command(label="Default Settings", command=lambda: self._menu_placeholder("Default Settings"))
        menubar.add_cascade(label="Options", menu=options_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="User Guide", command=lambda: self._menu_placeholder("User Guide"))
        help_menu.add_command(label="Driveway Standards", command=lambda: self._menu_placeholder("Driveway Standards"))
        help_menu.add_command(label="Check for Updates", command=lambda: self._menu_placeholder("Check for Updates"))
        help_menu.add_separator()
        help_menu.add_command(label="About DrivewayIQ", command=self._menu_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        license_menu = tk.Menu(menubar, tearoff=0)
        license_menu.add_command(label="Activate License", command=lambda: self._menu_placeholder("Activate License"))
        license_menu.add_command(label="Deactivate License", command=lambda: self._menu_placeholder("Deactivate License"))
        license_menu.add_command(label="Manage Subscription", command=lambda: self._menu_placeholder("Manage Subscription"))
        license_menu.add_separator()
        license_menu.add_command(label="Terms of Use", command=lambda: self._menu_placeholder("Terms of Use"))
        menubar.add_cascade(label="License", menu=license_menu)

        self.config(menu=menubar)

    def _menu_placeholder(self, feature_name: str) -> None:
        messagebox.showinfo(feature_name, f"{feature_name} command placeholder.\n\nAdd command logic here later.")

    def _menu_about(self) -> None:
        messagebox.showinfo(
            "About DrivewayIQ",
            "DrivewayIQ PRO\nDriveway Gradient Calculator\n\nPlaceholder menu system installed.",
        )

    def _menu_new_profile(self) -> None:
        pane = self.pane
        if hasattr(pane, "profile_name_var"):
            pane.profile_name_var.set("")
        if hasattr(pane, "profile_select_var"):
            pane.profile_select_var.set("")
        self._menu_reset_inputs()

    def _menu_open_profile(self) -> None:
        if hasattr(self.pane, "_profile_load_selected"):
            self.pane._profile_load_selected()
        else:
            self._menu_placeholder("Open Profile")

    def _menu_save_profile(self) -> None:
        if hasattr(self.pane, "_profile_save_current"):
            self.pane._profile_save_current()
        else:
            self._menu_placeholder("Save Profile")

    def _menu_save_as_profile(self) -> None:
        # Placeholder behaviour: clear the profile name so the user can type a new
        # name in the Saved Profile Bank, then use Save Profile.
        if hasattr(self.pane, "profile_name_var"):
            self.pane.profile_name_var.set("")
        messagebox.showinfo("Save As...", "Enter a new profile name in the Saved Profile Bank, then choose Save Profile.")

    def _menu_export_dxf(self) -> None:
        if hasattr(self.pane, "export_dxf_1_100"):
            self.pane.export_dxf_1_100()
        elif hasattr(self.pane, "export_dxf_1_1"):
            self.pane.export_dxf_1_1()
        else:
            self._menu_placeholder("Export DXF")

    def _menu_export_pdf(self) -> None:
        if hasattr(self.pane, "export_pdf"):
            self.pane.export_pdf()
        else:
            self._menu_placeholder("Export PDF")

    def _menu_export_png(self) -> None:
        if hasattr(self.pane, "export_png"):
            self.pane.export_png()
        else:
            self._menu_placeholder("Export PNG")

    def _menu_reset_inputs(self) -> None:
        pane = self.pane
        try:
            pane.boundary_var.set("10.000")
            pane.length_var.set("6.0")
            pane.direction_var.set("Up from boundary")
            pane.tol_input_var.set("0")
            if hasattr(pane, "rebate_mm_var"):
                pane.rebate_mm_var.set("35")
            if hasattr(pane, "use_custom_slab_var"):
                pane.use_custom_slab_var.set(False)
            if hasattr(pane, "custom_slab_mm_var"):
                pane.custom_slab_mm_var.set("")
            if hasattr(pane, "slab_var"):
                pane.slab_var.set(list(SLAB_OPTIONS.keys())[0])
            if hasattr(pane, "customize_var"):
                pane.customize_var.set(False)
            if hasattr(pane, "_custom_reset_defaults"):
                pane._custom_reset_defaults()
            if hasattr(pane, "_toggle_custom_slab_height"):
                pane._toggle_custom_slab_height()
            if hasattr(pane, "_compute_and_update"):
                pane._compute_and_update(show_errors=False)
        except Exception:
            messagebox.showerror("Reset Inputs", traceback.format_exc())

    def _toggle_overlay(self, var_name: str) -> None:
        var = getattr(self.pane, var_name, None)
        if isinstance(var, tk.BooleanVar):
            var.set(not bool(var.get()))
            if hasattr(self.pane, "_apply_overlays_and_redraw"):
                self.pane._apply_overlays_and_redraw()
        else:
            self._menu_placeholder(var_name)

    def _menu_reset_layout(self) -> None:
        # Reset the visible overlay/layout controls to their default state.
        for var_name in ("ov_show_rl", "ov_show_lengths", "ov_show_grades", "ov_show_labels", "ov_show_ref", "ov_show_spline"):
            var = getattr(self.pane, var_name, None)
            if isinstance(var, tk.BooleanVar):
                var.set(True)
        if hasattr(self.pane, "profile_style_var"):
            self.pane.profile_style_var.set("Spline Line")
        if hasattr(self.pane, "_apply_overlays_and_redraw"):
            self.pane._apply_overlays_and_redraw()

    def report_callback_exception(self, exc, val, tb):
        try:
            _write_runtime_crash_log("".join(traceback.format_exception(exc, val, tb)))
        except Exception:
            pass
        messagebox.showerror("Error", "".join(traceback.format_exception_only(exc, val)))


if __name__ == "__main__":
    _install_global_crash_hooks()
    try:
        App().mainloop()
    except Exception:
        _write_startup_error(traceback.format_exc())
        raise

try:
    self.license_label.lift()
except:
    pass
