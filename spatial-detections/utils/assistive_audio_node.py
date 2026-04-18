import subprocess
import time
from typing import Optional

import depthai as dai
import numpy as np


class AssistiveAudioNode(dai.node.HostNode):
    # Thresholds in mm
    DANGER_MM = 2500
    WARN_MM   = 4000
    CLEAR_MM  = 8000

    # Zone layout (row_frac_start, row_frac_end, col_frac_start, col_frac_end)
    # Cone: widest at bottom (ground row), narrowest at top — approximated as three stacked bands
    # Left/right escape routes cover the same vertical range as the cone
    ZONES = {
        "cone_top":    (0.10, 0.40, 0.35, 0.65),  # narrow top of forward cone
        "cone_mid":    (0.40, 0.65, 0.25, 0.75),  # middle band
        "cone_bot":    (0.65, 0.90, 0.10, 0.90),  # wide base of cone (ground level)
        "left":        (0.20, 0.80, 0.00, 0.25),  # left escape corridor
        "right":       (0.20, 0.80, 0.75, 1.00),  # right escape corridor
    }

    def __init__(self) -> None:
        super().__init__()
        self.input_depth = self.createInput()
        self._interval   = 2.0
        self._last_state = "clear"
        self._last_spoken: float = 0.0
        self._tts_proc = None
        self._smoothing_alpha = 0.25
        self._smoothed_dists: dict[str, float] = {}

    def build(self, depth: dai.Node.Output, interval: float = 2.0) -> "AssistiveAudioNode":
        self._interval = interval
        self.link_args(depth)
        return self

    def process(self, depth_message: dai.ImgFrame) -> None:
        frame = depth_message.getCvFrame()          # (H, W) uint16, mm
        if not frame.any():
            return

        if not hasattr(self, "_sample_printed"):
            self._sample_printed = True
            self._print_sample(frame)

        dists = {
            name: self._smooth_distance(name, self._zone_dist(frame, *fracs))
            for name, fracs in self.ZONES.items()
        }
        cone_dist = min(dists["cone_top"], dists["cone_mid"], dists["cone_bot"])

        print(
            f"\r  cone={cone_dist/1000:.1f}m"
            f"  left={dists['left']/1000:.1f}m  right={dists['right']/1000:.1f}m   ",
            end="", flush=True,
        )

        new_state = self._classify(cone_dist)
        now = time.monotonic()

        state_changed = new_state != self._last_state
        repeat_alert  = new_state != "clear" and now - self._last_spoken > self._interval

        if not (state_changed or repeat_alert):
            return

        self._last_state = new_state
        msg = self._build_message(new_state, cone_dist, dists)
        if msg is None:
            return

        self._last_spoken = now
        print(f"\n[AUDIO] {msg}")
        self._speak(msg)

    def _print_sample(self, frame: np.ndarray) -> None:
        H, W = frame.shape
        valid = frame[frame > 0]
        print(f"\n{'='*60}")
        print(f"Frame shape: {frame.shape}  dtype: {frame.dtype}")
        print(f"Valid pixels: {len(valid)}/{frame.size} ({100*len(valid)/frame.size:.1f}%)")
        print(f"Depth range: {valid.min()}mm – {valid.max()}mm  median: {int(np.median(valid))}mm")
        print()
        # 8x16 downsampled grid (mm), 0=invalid
        step_r, step_c = H // 8, W // 16
        grid = frame[step_r//2::step_r, step_c//2::step_c][:8, :16]
        print("Downsampled depth grid (mm), rows=top→bottom, cols=left→right:")
        for row in grid:
            print("  " + "  ".join(f"{v:5d}" if v > 0 else "    0" for v in row))
        print()
        # Per-zone raw stats
        print("Zone stats (10th pct / median / valid%):")
        for name, (r0, r1, c0, c1) in self.ZONES.items():
            roi = frame[int(r0*H):int(r1*H), int(c0*W):int(c1*W)]
            v = roi[roi > 0]
            if len(v):
                print(f"  {name:7s}: p10={int(np.percentile(v,10)):5d}mm  "
                      f"median={int(np.median(v)):5d}mm  valid={100*len(v)/roi.size:.0f}%")
            else:
                print(f"  {name:7s}: no valid pixels")
        print(f"{'='*60}\n")

    def _zone_dist(self, frame: np.ndarray, r0: float, r1: float, c0: float, c1: float) -> float:
        H, W = frame.shape
        roi  = frame[int(r0*H):int(r1*H), int(c0*W):int(c1*W)]
        valid = roi[roi > 0]
        if len(valid) == 0:
            return float(self.CLEAR_MM * 2)
        # 10th percentile: robust closest obstacle, ignores noise
        return float(np.percentile(valid, 10))

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

    def _classify(self, path_dist: float) -> str:
        if path_dist <= self.DANGER_MM:
            return "danger"
        if path_dist <= self.WARN_MM:
            return "warn"
        return "clear"

    def _build_message(self, state: str, cone_dist: float, dists: dict) -> Optional[str]:
        if state == "clear":
            return None

        direction = self._escape_direction(dists["left"], dists["right"])
        dist_m = cone_dist / 1000

        if state == "danger":
            #return f"Stop. Obstacle {dist_m:.1f} meters. {direction}."
            return f"Stop. Obstacle. {direction}."
        #return f"Obstacle {dist_m:.1f} meters ahead. {direction}."
        return f"Obstacle ahead. {direction}."

    def _escape_direction(self, left_dist: float, right_dist: float) -> str:
        margin = 400  # mm — must be meaningfully clearer to recommend a side
        left_clear  = left_dist  > self.WARN_MM
        right_clear = right_dist > self.WARN_MM
        if left_clear and (not right_clear or left_dist > right_dist + margin):
            return "Move left"
        if right_clear and (not left_clear or right_dist > left_dist + margin):
            return "Move right"
        if left_dist > right_dist + margin:
            return "Move left"
        if right_dist > left_dist + margin:
            return "Move right"
        return "No clear path"

    def _speak(self, text: str) -> None:
        if self._tts_proc and self._tts_proc.poll() is None:
            #self._tts_proc.terminate()
            return
        try:
            self._tts_proc = subprocess.Popen(
                ["espeak-ng", "-s", "150", text],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            print("[WARN] espeak-ng not found. Install: sudo pacman -S espeak-ng")
