from dataclasses import dataclass
from typing import Optional

import numpy as np

# Base thresholds in mm
DANGER_MM = 800
WARN_MM = 1500
CLEAR_MM = 2000

# Slightly stronger bottom-band thresholds for walking safety
BOTTOM_DANGER_MM = 700
BOTTOM_WARN_MM = 1200

# Hysteresis thresholds
DANGER_ENTER_MM = DANGER_MM
DANGER_EXIT_MM = 1000
WARN_ENTER_MM = WARN_MM
WARN_EXIT_MM = 1700

# Side-selection margins
SIDE_MARGIN_MM = 400
SIDE_STRONG_MARGIN_MM = 600

# Occupancy threshold to consider a zone genuinely blocked
OCCUPANCY_THRESHOLD = 0.12

# Zone layout: (row_start, row_end, col_start, col_end) as fractions of frame dims.
ZONES = {
    "cone_top": (0.10, 0.38, 0.42, 0.58),
    "cone_mid": (0.38, 0.62, 0.35, 0.65),
    "cone_bot": (0.62, 0.78, 0.28, 0.72),
    "left": (0.20, 0.68, 0.00, 0.25),
    "right": (0.20, 0.68, 0.75, 1.00),
}

# Cone trapezoid corners
CONE_TL = (0.42, 0.10)
CONE_TR = (0.58, 0.10)
CONE_BR = (0.72, 0.78)
CONE_BL = (0.28, 0.78)

DEPTH_PERCENTILE = 15


@dataclass
class ZoneMetrics:
    dist_mm: float
    median_mm: float
    valid_ratio: float
    occupied_ratio: float
    valid_count: int


@dataclass
class DynamicThresholds:
    warn_mm: float
    danger_mm: float
    bottom_warn_mm: float
    bottom_danger_mm: float
    closing_speed_mm_s: float
    ttc_s: float


def zone_dist(frame: np.ndarray, r0: float, r1: float, c0: float, c1: float) -> float:
    H, W = frame.shape
    roi = frame[int(r0 * H):int(r1 * H), int(c0 * W):int(c1 * W)]
    valid = roi[roi > 0]
    if len(valid) == 0:
        return float(CLEAR_MM * 2)
    return float(np.percentile(valid, DEPTH_PERCENTILE))


def zone_metrics(frame: np.ndarray, r0: float, r1: float, c0: float, c1: float) -> ZoneMetrics:
    H, W = frame.shape
    roi = frame[int(r0 * H):int(r1 * H), int(c0 * W):int(c1 * W)]
    valid = roi[roi > 0]

    if len(valid) == 0:
        return ZoneMetrics(
            dist_mm=float(CLEAR_MM * 2),
            median_mm=float(CLEAR_MM * 2),
            valid_ratio=0.0,
            occupied_ratio=0.0,
            valid_count=0,
        )

    p = float(np.percentile(valid, DEPTH_PERCENTILE))
    med = float(np.median(valid))
    valid_ratio = float(len(valid) / roi.size)
    occupied_ratio = float(np.mean(valid <= WARN_MM))

    return ZoneMetrics(
        dist_mm=p,
        median_mm=med,
        valid_ratio=valid_ratio,
        occupied_ratio=occupied_ratio,
        valid_count=int(len(valid)),
    )


def get_zone_metrics(frame: np.ndarray) -> dict[str, ZoneMetrics]:
    return {
        name: zone_metrics(frame, *fracs)
        for name, fracs in ZONES.items()
    }


def classify(dist: float, danger_mm: float = DANGER_MM, warn_mm: float = WARN_MM) -> str:
    if dist <= danger_mm:
        return "danger"
    if dist <= warn_mm:
        return "warn"
    return "clear"


def classify_with_hysteresis(
    cone_top: float,
    cone_mid: float,
    cone_bot: float,
    previous: str,
    dynamic: Optional[DynamicThresholds] = None,
) -> str:
    danger_enter = dynamic.danger_mm if dynamic else DANGER_ENTER_MM
    danger_exit = max(DANGER_EXIT_MM, danger_enter + 200)
    warn_enter = dynamic.warn_mm if dynamic else WARN_ENTER_MM
    warn_exit = max(WARN_EXIT_MM, warn_enter + 250)

    bottom_danger = dynamic.bottom_danger_mm if dynamic else BOTTOM_DANGER_MM
    bottom_warn = dynamic.bottom_warn_mm if dynamic else BOTTOM_WARN_MM

    if previous == "danger":
        if cone_bot > bottom_danger and min(cone_mid, cone_top) > danger_exit:
            previous = "warn"
        else:
            return "danger"

    if previous == "warn":
        if cone_bot <= bottom_danger or min(cone_mid, cone_top) <= danger_enter:
            return "danger"
        if cone_bot > bottom_warn and min(cone_mid, cone_top) > warn_exit:
            return "clear"
        return "warn"

    if cone_bot <= bottom_danger or min(cone_mid, cone_top) <= danger_enter:
        return "danger"
    if cone_bot <= bottom_warn or min(cone_mid, cone_top) <= warn_enter:
        return "warn"
    return "clear"


def zone_is_blocked(metrics: ZoneMetrics, warn_threshold_mm: float = WARN_MM) -> bool:
    return (
        metrics.dist_mm <= warn_threshold_mm
        and metrics.occupied_ratio >= OCCUPANCY_THRESHOLD
        and metrics.valid_ratio > 0.05
    )


def pick_escape_or_stop(
    left_dist: float,
    right_dist: float,
    left_blocked: bool,
    right_blocked: bool,
    strong: bool = False,
) -> str:
    margin = SIDE_STRONG_MARGIN_MM if strong else SIDE_MARGIN_MM

    if not left_blocked and (right_blocked or left_dist > right_dist + margin):
        return "STEP_LEFT"

    if not right_blocked and (left_blocked or right_dist > left_dist + margin):
        return "STEP_RIGHT"

    if left_dist > right_dist + margin:
        return "STEP_LEFT"
    if right_dist > left_dist + margin:
        return "STEP_RIGHT"

    return "STOP" if strong else "WAIT"


def estimate_dynamic_thresholds(
    closing_speed_mm_s: float,
    hazard_dist_mm: float,
) -> DynamicThresholds:
    """
    Expand thresholds based on closing speed.
    Uses both:
    - dynamic distance buffer = speed * reaction_time
    - time-to-collision estimate
    """

    speed = max(0.0, min(closing_speed_mm_s, 2500.0))

    warn_reaction_s = 1.2
    danger_reaction_s = 0.55
    bottom_warn_reaction_s = 0.9
    bottom_danger_reaction_s = 0.45

    warn_mm = min(3200.0, WARN_MM + speed * warn_reaction_s)
    danger_mm = min(1800.0, DANGER_MM + speed * danger_reaction_s)
    bottom_warn_mm = min(2600.0, BOTTOM_WARN_MM + speed * bottom_warn_reaction_s)
    bottom_danger_mm = min(1500.0, BOTTOM_DANGER_MM + speed * bottom_danger_reaction_s)

    if speed > 100.0:
        ttc_s = hazard_dist_mm / speed
    else:
        ttc_s = float("inf")

    return DynamicThresholds(
        warn_mm=warn_mm,
        danger_mm=danger_mm,
        bottom_warn_mm=bottom_warn_mm,
        bottom_danger_mm=bottom_danger_mm,
        closing_speed_mm_s=speed,
        ttc_s=ttc_s,
    )


def decide_command(
    zone_metrics_map: dict[str, ZoneMetrics],
    previous_state: str = "clear",
    dynamic: Optional[DynamicThresholds] = None,
) -> tuple[Optional[str], str]:
    cone_top = zone_metrics_map["cone_top"].dist_mm
    cone_mid = zone_metrics_map["cone_mid"].dist_mm
    cone_bot = zone_metrics_map["cone_bot"].dist_mm

    left = zone_metrics_map["left"].dist_mm
    right = zone_metrics_map["right"].dist_mm

    warn_mm = dynamic.warn_mm if dynamic else WARN_MM
    danger_mm = dynamic.danger_mm if dynamic else DANGER_MM
    bottom_warn_mm = dynamic.bottom_warn_mm if dynamic else BOTTOM_WARN_MM
    bottom_danger_mm = dynamic.bottom_danger_mm if dynamic else BOTTOM_DANGER_MM

    left_blocked = zone_is_blocked(zone_metrics_map["left"], warn_mm)
    right_blocked = zone_is_blocked(zone_metrics_map["right"], warn_mm)

    state = classify_with_hysteresis(
        cone_top, cone_mid, cone_bot, previous_state, dynamic=dynamic
    )

    # Emergency handling
    if cone_bot <= bottom_danger_mm or (
        cone_mid <= danger_mm and cone_bot <= max(bottom_danger_mm, danger_mm + 150)
    ):
        return pick_escape_or_stop(left, right, left_blocked, right_blocked, strong=True), state

    if dynamic and dynamic.ttc_s < 0.9:
        return pick_escape_or_stop(left, right, left_blocked, right_blocked, strong=True), state

    if state == "danger":
        return pick_escape_or_stop(left, right, left_blocked, right_blocked, strong=True), state

    if state == "warn":
        return pick_escape_or_stop(left, right, left_blocked, right_blocked, strong=False), state

    if dynamic and dynamic.ttc_s < 1.8:
        return pick_escape_or_stop(left, right, left_blocked, right_blocked, strong=False), state

    if cone_top > CLEAR_MM and cone_mid > CLEAR_MM and cone_bot > CLEAR_MM:
        return "FORWARD", state

    return None, state


def command_confidence(
    zone_metrics_map: dict[str, ZoneMetrics],
    command: Optional[str],
) -> str:
    if command is None:
        return "LOW"

    top = zone_metrics_map["cone_top"].dist_mm
    mid = zone_metrics_map["cone_mid"].dist_mm
    bot = zone_metrics_map["cone_bot"].dist_mm
    left = zone_metrics_map["left"].dist_mm
    right = zone_metrics_map["right"].dist_mm

    if command == "STOP":
        if bot <= BOTTOM_DANGER_MM:
            return "HIGH"
        return "MED"

    if command in {"STEP_LEFT", "STEP_RIGHT"}:
        side_gap = abs(left - right)
        if side_gap > SIDE_STRONG_MARGIN_MM:
            return "HIGH"
        if side_gap > SIDE_MARGIN_MM:
            return "MED"
        return "LOW"

    if command == "FORWARD":
        if top > CLEAR_MM and mid > CLEAR_MM and bot > CLEAR_MM:
            return "HIGH"
        return "MED"

    if command == "WAIT":
        return "MED"

    return "LOW"