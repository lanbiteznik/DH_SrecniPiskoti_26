import subprocess
import time
from typing import Optional

import depthai as dai
import numpy as np


class AssistiveAudioNode(dai.node.HostNode):
    # Thresholds in mm
    DANGER_MM = 1500
    WARN_MM   = 3000
    CLEAR_MM  = 7000

    # Zone layout (row_frac_start, row_frac_end, col_frac_start, col_frac_end)
    # Image is H x W, top=0, left=0
    ZONES = {
        "top":    (0.00, 0.33, 0.25, 0.75),  # center column, upper third
        "center": (0.33, 0.67, 0.25, 0.75),  # center column, middle third
        "bottom": (0.67, 1.00, 0.25, 0.75),  # center column, lower third
        "left":   (0.25, 0.75, 0.00, 0.25),  # left quarter, mid-height     ← escape route
        "right":  (0.25, 0.75, 0.75, 1.00),  # right quarter, mid-height    ← escape route
    }

    def __init__(self) -> None:
        super().__init__()
        self.input_depth = self.createInput()
        self._interval   = 2.0
        self._last_state = "clear"
        self._last_spoken: float = 0.0
        self._tts_proc = None

    def build(self, depth: dai.Node.Output, interval: float = 2.0) -> "AssistiveAudioNode":
        self._interval = interval
        self.link_args(depth)
        return self

    def process(self, depth_message: dai.ImgFrame) -> None:
        frame = depth_message.getCvFrame()          # (H, W) uint16, mm
        if not frame.any():
            return

        dists = {name: self._zone_dist(frame, *fracs) for name, fracs in self.ZONES.items()}

        print(
            f"\r  top={dists['top']/1000:.1f}m  center={dists['center']/1000:.1f}m"
            f"  bottom={dists['bottom']/1000:.1f}m  left={dists['left']/1000:.1f}m"
            f"  right={dists['right']/1000:.1f}m   ",
            end="", flush=True,
        )

        new_state = self._classify(dists["center"])
        now = time.monotonic()

        state_changed   = new_state != self._last_state
        repeat_danger   = new_state == "danger" and now - self._last_spoken > self._interval

        if not (state_changed or repeat_danger):
            return

        self._last_state  = new_state
        msg = self._build_message(new_state, dists)
        if msg is None:
            return

        self._last_spoken = now
        print(f"\n[AUDIO] {msg}")
        self._speak(msg)

    def _zone_dist(self, frame: np.ndarray, r0: float, r1: float, c0: float, c1: float) -> float:
        H, W = frame.shape
        roi  = frame[int(r0*H):int(r1*H), int(c0*W):int(c1*W)]
        valid = roi[roi > 0]
        if len(valid) == 0:
            return float(self.CLEAR_MM * 2)
        # 10th percentile: robust closest obstacle, ignores noise
        return float(np.percentile(valid, 10))

    def _classify(self, path_dist: float) -> str:
        if path_dist <= self.DANGER_MM:
            return "danger"
        if path_dist <= self.WARN_MM:
            return "warn"
        return "clear"

    def _build_message(self, state: str, dists: dict) -> Optional[str]:
        if state == "clear":
            return None

        top_m    = dists["top"] / 1000
        center_m = dists["center"] / 1000
        bottom_m = dists["bottom"] / 1000

        # Bottom obstacle closer than center/top → step or curb
        bottom_hazard = (
            dists["bottom"] < dists["center"] - 300
            and dists["bottom"] < self.WARN_MM
        )

        direction = self._escape_direction(dists["left"], dists["right"])

        if state == "danger":
            if bottom_hazard:
                return f"Step or curb {bottom_m:.1f} meters. {direction}."
            return f"Stop. Obstacle {center_m:.1f} meters. {direction}."

        # warn state
        if bottom_hazard:
            return f"Low obstacle {bottom_m:.1f} meters ahead. {direction}."
        if top_m < center_m - 300 and top_m < self.WARN_MM:
            return f"High obstacle {top_m:.1f} meters ahead. {direction}."
        return f"Obstacle {center_m:.1f} meters ahead. {direction}."

    def _escape_direction(self, left_dist: float, right_dist: float) -> str:
        margin = 400  # mm — must be meaningfully clearer to recommend a side
        if left_dist > right_dist + margin:
            return "Move left"
        if right_dist > left_dist + margin:
            return "Move right"
        return "Stop"

    def _speak(self, text: str) -> None:
        if self._tts_proc and self._tts_proc.poll() is None:
            return
        try:
            self._tts_proc = subprocess.Popen(
                ["espeak-ng", "-s", "150", text],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            print("[WARN] espeak-ng not found. Install: sudo pacman -S espeak-ng")
