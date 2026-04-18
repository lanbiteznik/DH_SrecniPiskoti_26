import subprocess
import time
from typing import Optional

import depthai as dai
import numpy as np


class AssistiveAudioNode(dai.node.HostNode):
    # ----------------------------
    # Distance thresholds in mm
    # ----------------------------
    DANGER_ENTER_MM = 2500
    DANGER_EXIT_MM = 3000

    WARN_ENTER_MM = 4000
    WARN_EXIT_MM = 4700

    CLEAR_MM = 8000

    # Stronger near-ground emergency threshold
    BOTTOM_DANGER_MM = 1800
    BOTTOM_WARN_MM = 3000

    # Left/right recommendation margin
    SIDE_MARGIN_MM = 500
    SIDE_STRONG_MARGIN_MM = 700

    # Minimum occupied fraction of valid ROI pixels under WARN distance
    # required to consider a zone genuinely blocked
    OCCUPANCY_THRESHOLD = 0.12

    # Candidate command persistence before speaking
    CONFIRM_SECONDS = {
        "STOP": 0.0,
        "STEP_LEFT": 0.35,
        "STEP_RIGHT": 0.35,
        "WAIT": 0.50,
        "FORWARD": 0.80,
    }

    # Speech cooldowns
    COOLDOWN_SECONDS = {
        "STOP": 0.0,
        "STEP_LEFT": 1.0,
        "STEP_RIGHT": 1.0,
        "WAIT": 1.5,
        "FORWARD": 2.0,
    }

    # Spoken phrases
    COMMAND_TEXT = {
        "STOP": "Stop.",
        "STEP_LEFT": "Step left.",
        "STEP_RIGHT": "Step right.",
        "WAIT": "Wait.",
        "FORWARD": "Forward.",
    }

    # Command priorities (higher = more important)
    COMMAND_PRIORITY = {
        "STOP": 100,
        "STEP_LEFT": 70,
        "STEP_RIGHT": 70,
        "WAIT": 50,
        "FORWARD": 10,
    }

    # Zone layout (row_frac_start, row_frac_end, col_frac_start, col_frac_end)
    ZONES = {
        "cone_top": (0.10, 0.40, 0.35, 0.65),
        "cone_mid": (0.40, 0.65, 0.25, 0.75),
        "cone_bot": (0.65, 0.90, 0.10, 0.90),
        "left": (0.20, 0.80, 0.00, 0.25),
        "right": (0.20, 0.80, 0.75, 1.00),
    }

    def __init__(self) -> None:
        super().__init__()
        self.input_depth = self.createInput()

        self._interval = 2.0
        self._tts_proc = None

        self._smoothing_alpha = 0.25
        self._smoothed_dists: dict[str, float] = {}

        self._last_state = "clear"
        self._last_command: Optional[str] = None
        self._last_spoken: float = 0.0

        self._candidate_command: Optional[str] = None
        self._candidate_since: float = 0.0

    def build(self, depth: dai.Node.Output, interval: float = 2.0) -> "AssistiveAudioNode":
        self._interval = interval
        self.link_args(depth)
        return self

    def process(self, depth_message: dai.ImgFrame) -> None:
        frame = depth_message.getCvFrame()  # (H, W) uint16, mm
        if frame is None or not frame.any():
            return

        if not hasattr(self, "_sample_printed"):
            self._sample_printed = True
            self._print_sample(frame)

        zone_metrics = {
            name: self._zone_metrics(frame, *fracs)
            for name, fracs in self.ZONES.items()
        }

        dists = {
            name: self._smooth_distance(name, metrics["p10_mm"])
            for name, metrics in zone_metrics.items()
        }

        # Replace raw p10 with smoothed distances in the metrics dict
        for name, smoothed_dist in dists.items():
            zone_metrics[name]["dist_mm"] = smoothed_dist

        cone_top = zone_metrics["cone_top"]["dist_mm"]
        cone_mid = zone_metrics["cone_mid"]["dist_mm"]
        cone_bot = zone_metrics["cone_bot"]["dist_mm"]
        left_dist = zone_metrics["left"]["dist_mm"]
        right_dist = zone_metrics["right"]["dist_mm"]

        candidate = self._decide_command(zone_metrics)
        now = time.monotonic()

        self._debug_print(candidate, cone_top, cone_mid, cone_bot, left_dist, right_dist, zone_metrics)

        if candidate is None:
            self._candidate_command = None
            return

        # Track candidate persistence
        if candidate != self._candidate_command:
            self._candidate_command = candidate
            self._candidate_since = now
            return

        confirm_seconds = self.CONFIRM_SECONDS.get(candidate, 0.4)
        if now - self._candidate_since < confirm_seconds:
            return

        # Suppress repeats unless cooldown expired
        if candidate == self._last_command:
            cooldown = self.COOLDOWN_SECONDS.get(candidate, self._interval)
            if now - self._last_spoken < cooldown:
                return

        # Speak confirmed command
        self._last_command = candidate
        self._last_spoken = now
        spoken = self.COMMAND_TEXT[candidate]
        print(f"\n[AUDIO] {spoken}")
        self._speak(spoken, priority=self.COMMAND_PRIORITY[candidate])

    def _print_sample(self, frame: np.ndarray) -> None:
        H, W = frame.shape
        valid = frame[frame > 0]
        print(f"\n{'=' * 60}")
        print(f"Frame shape: {frame.shape}  dtype: {frame.dtype}")
        print(f"Valid pixels: {len(valid)}/{frame.size} ({100 * len(valid) / frame.size:.1f}%)")
        print(f"Depth range: {valid.min()}mm – {valid.max()}mm  median: {int(np.median(valid))}mm")
        print()

        step_r, step_c = H // 8, W // 16
        grid = frame[step_r // 2::step_r, step_c // 2::step_c][:8, :16]
        print("Downsampled depth grid (mm), rows=top→bottom, cols=left→right:")
        for row in grid:
            print("  " + "  ".join(f"{v:5d}" if v > 0 else "    0" for v in row))
        print()

        print("Zone stats (10th pct / median / valid% / occ%):")
        for name, (r0, r1, c0, c1) in self.ZONES.items():
            metrics = self._zone_metrics(frame, r0, r1, c0, c1)
            if metrics["valid_count"] > 0:
                print(
                    f"  {name:7s}: p10={int(metrics['p10_mm']):5d}mm  "
                    f"median={int(metrics['median_mm']):5d}mm  "
                    f"valid={100*metrics['valid_ratio']:.0f}%  "
                    f"occ={100*metrics['occupied_ratio']:.0f}%"
                )
            else:
                print(f"  {name:7s}: no valid pixels")
        print(f"{'=' * 60}\n")

    def _zone_metrics(self, frame: np.ndarray, r0: float, r1: float, c0: float, c1: float) -> dict:
        H, W = frame.shape
        roi = frame[int(r0 * H):int(r1 * H), int(c0 * W):int(c1 * W)]
        valid = roi[roi > 0]

        if len(valid) == 0:
            return {
                "p10_mm": float(self.CLEAR_MM * 2),
                "median_mm": float(self.CLEAR_MM * 2),
                "valid_ratio": 0.0,
                "occupied_ratio": 0.0,
                "valid_count": 0,
            }

        p10 = float(np.percentile(valid, 10))
        median = float(np.median(valid))
        valid_ratio = float(len(valid) / roi.size)

        occupied = valid[valid <= self.WARN_ENTER_MM]
        occupied_ratio = float(len(occupied) / len(valid)) if len(valid) else 0.0

        return {
            "p10_mm": p10,
            "median_mm": median,
            "valid_ratio": valid_ratio,
            "occupied_ratio": occupied_ratio,
            "valid_count": int(len(valid)),
        }

    def _smooth_distance(self, zone: str, new_value: float) -> float:
        previous_value = self._smoothed_dists.get(zone)
        if previous_value is None:
            self._smoothed_dists[zone] = new_value
            return new_value

        smoothed_value = (
            self._smoothing_alpha * new_value
            + (1.0 - self._smoothing_alpha) * previous_value
        )
        self._smoothed_dists[zone] = smoothed_value
        return smoothed_value

    def _classify_with_hysteresis(self, cone_top: float, cone_mid: float, cone_bot: float) -> str:
        previous = self._last_state

        if previous == "danger":
            if cone_bot > self.BOTTOM_DANGER_MM and min(cone_mid, cone_top) > self.DANGER_EXIT_MM:
                previous = "warn"
            else:
                return "danger"

        if previous == "warn":
            if cone_bot <= self.BOTTOM_DANGER_MM or min(cone_mid, cone_top) <= self.DANGER_ENTER_MM:
                return "danger"
            if cone_bot > self.BOTTOM_WARN_MM and min(cone_mid, cone_top) > self.WARN_EXIT_MM:
                return "clear"
            return "warn"

        # Previous clear
        if cone_bot <= self.BOTTOM_DANGER_MM or min(cone_mid, cone_top) <= self.DANGER_ENTER_MM:
            return "danger"
        if cone_bot <= self.BOTTOM_WARN_MM or min(cone_mid, cone_top) <= self.WARN_ENTER_MM:
            return "warn"
        return "clear"

    def _zone_is_blocked(self, metrics: dict, warn_threshold_mm: float) -> bool:
        return (
            metrics["dist_mm"] <= warn_threshold_mm
            and metrics["occupied_ratio"] >= self.OCCUPANCY_THRESHOLD
            and metrics["valid_ratio"] > 0.05
        )

    def _decide_command(self, zone_metrics: dict) -> Optional[str]:
        cone_top = zone_metrics["cone_top"]["dist_mm"]
        cone_mid = zone_metrics["cone_mid"]["dist_mm"]
        cone_bot = zone_metrics["cone_bot"]["dist_mm"]

        left = zone_metrics["left"]["dist_mm"]
        right = zone_metrics["right"]["dist_mm"]

        left_blocked = self._zone_is_blocked(zone_metrics["left"], self.WARN_ENTER_MM)
        right_blocked = self._zone_is_blocked(zone_metrics["right"], self.WARN_ENTER_MM)

        state = self._classify_with_hysteresis(cone_top, cone_mid, cone_bot)
        self._last_state = state

        # Emergency handling: heavily prioritize lower region
        if cone_bot <= self.BOTTOM_DANGER_MM or (
            cone_mid <= self.DANGER_ENTER_MM and cone_bot <= self.DANGER_EXIT_MM
        ):
            return self._pick_escape_or_stop(left, right, left_blocked, right_blocked, strong=True)

        # Warning handling
        if state == "danger":
            return self._pick_escape_or_stop(left, right, left_blocked, right_blocked, strong=True)

        if state == "warn":
            return self._pick_escape_or_stop(left, right, left_blocked, right_blocked, strong=False)

        # Clear path recovery
        if (
            cone_top > self.CLEAR_MM
            and cone_mid > self.CLEAR_MM
            and cone_bot > self.CLEAR_MM
        ):
            return "FORWARD"

        return None

    def _pick_escape_or_stop(
        self,
        left_dist: float,
        right_dist: float,
        left_blocked: bool,
        right_blocked: bool,
        strong: bool = False,
    ) -> str:
        margin = self.SIDE_STRONG_MARGIN_MM if strong else self.SIDE_MARGIN_MM

        # Strong preference for a genuinely clear side
        if not left_blocked and (right_blocked or left_dist > right_dist + margin):
            return "STEP_LEFT"

        if not right_blocked and (left_blocked or right_dist > left_dist + margin):
            return "STEP_RIGHT"

        # If both sides are somewhat similar but one is still meaningfully better
        if left_dist > right_dist + margin:
            return "STEP_LEFT"
        if right_dist > left_dist + margin:
            return "STEP_RIGHT"

        # No reliable escape route
        return "STOP" if strong else "WAIT"

    def _debug_print(
        self,
        candidate: Optional[str],
        cone_top: float,
        cone_mid: float,
        cone_bot: float,
        left_dist: float,
        right_dist: float,
        zone_metrics: dict,
    ) -> None:
        print(
            "\r"
            f"top={cone_top/1000:.1f}m "
            f"mid={cone_mid/1000:.1f}m "
            f"bot={cone_bot/1000:.1f}m "
            f"left={left_dist/1000:.1f}m "
            f"right={right_dist/1000:.1f}m "
            f"occL={zone_metrics['left']['occupied_ratio']:.2f} "
            f"occR={zone_metrics['right']['occupied_ratio']:.2f} "
            f"state={self._last_state} "
            f"cand={candidate or '-'}     ",
            end="",
            flush=True,
        )

    def _speak(self, text: str, priority: int = 0) -> None:
        current_running = self._tts_proc and self._tts_proc.poll() is None

        if current_running:
            current_priority = getattr(self, "_tts_priority", 0)
            if priority > current_priority:
                try:
                    self._tts_proc.terminate()
                except Exception:
                    pass
            else:
                return

        try:
            self._tts_proc = subprocess.Popen(
                ["espeak-ng", "-s", "150", text],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._tts_priority = priority
        except FileNotFoundError:
            print("[WARN] espeak-ng not found. Install: sudo pacman -S espeak-ng")