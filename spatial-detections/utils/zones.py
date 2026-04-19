import numpy as np

# Thresholds in mm
DANGER_MM = 800
WARN_MM   = 1500
CLEAR_MM  = 2000

# Named-object announcement tiers (mm): far warning / mid warning / stop
OBJ_TIERS = [8000, 5000, 2000]

# COCO classes worth announcing as navigation obstacles
OBSTACLE_CLASSES = {
    "person", "bicycle", "car", "motorcycle", "bus", "truck",
    "dog", "cat", "horse", "sheep", "cow", "elephant", "bear",
    "chair", "couch", "bed", "dining table", "toilet",
    "bench", "fire hydrant", "parking meter",
    "backpack", "umbrella", "suitcase",
}

# Zone layout: (row_start, row_end, col_start, col_end) as fractions of frame dims.
# The cone stops at row 0.78 — rows below that are near-floor which the camera
# always sees as close regardless of actual obstacles.
# Left/right corridors are capped at row 0.68 for the same reason.
ZONES = {
    "cone_top": (0.10, 0.38, 0.42, 0.58),  # narrow (far)
    "cone_mid": (0.38, 0.62, 0.35, 0.65),  # medium
    "cone_bot": (0.62, 0.78, 0.28, 0.72),  # wide (near), but above floor zone
    "left":     (0.20, 0.68, 0.00, 0.25),  # left escape corridor
    "right":    (0.20, 0.68, 0.75, 1.00),  # right escape corridor
}

# Cone trapezoid corners (col, row) for drawing — matches ZONES geometry
CONE_TL = (0.42, 0.10)
CONE_TR = (0.58, 0.10)
CONE_BR = (0.72, 0.78)
CONE_BL = (0.28, 0.78)

# Percentile used for robust "closest obstacle" estimate.
# 15th is less twitchy than 10th while still catching real obstacles.
DEPTH_PERCENTILE = 15


def in_cone(cx: float, cy: float) -> bool:
    r0, r1 = CONE_TL[1], CONE_BL[1]
    if not (r0 <= cy <= r1):
        return False
    t = (cy - r0) / (r1 - r0)
    left  = CONE_TL[0] + t * (CONE_BL[0] - CONE_TL[0])
    right = CONE_TR[0] + t * (CONE_BR[0] - CONE_TR[0])
    return left <= cx <= right


def zone_dist(frame: np.ndarray, r0: float, r1: float, c0: float, c1: float) -> float:
    H, W = frame.shape
    roi = frame[int(r0 * H):int(r1 * H), int(c0 * W):int(c1 * W)]
    valid = roi[roi > 0]
    if len(valid) == 0:
        return float(CLEAR_MM * 2)
    return float(np.percentile(valid, DEPTH_PERCENTILE))


def classify(dist: float) -> str:
    if dist <= DANGER_MM:
        return "danger"
    if dist <= WARN_MM:
        return "warn"
    return "clear"
