import subprocess
import time
from typing import List, Optional

import depthai as dai
import numpy as np


class AssistiveAudioNode(dai.node.HostNode):
    # Distance thresholds in mm
    CLEAR_MM = 4000    # beyond this: path is clear, stay silent
    WARN_MM = 2000     # warn zone: obstacle detected, suggest direction
    DANGER_MM = 1200    # danger zone: very close, urgent
    IGNORE_MM = 800     # ignore anything closer than this (could be noise)

    def __init__(self) -> None:
        super().__init__()
        self.input_depth = self.createInput()
        self._interval: float = 2.0
        self._last_spoken: float = 0.0
        self._last_state: str = "clear"
        self._tts_proc = None
        self._debug_printed: bool = False

    def build(
        self,
        depth: dai.Node.Output,
        interval: float = 2.0,
    ) -> "AssistiveAudioNode":
        self._interval = interval
        self.link_args(depth)
        return self

    def process(self, depth_message: dai.ImgFrame) -> None:
        frame = depth_message.getCvFrame()  # H x W, uint16, values in mm

        if not self._debug_printed:
            valid = frame[frame > 0]
            if len(valid) == 0:
                return  # wait for a real frame
            self._debug_printed = True
            print(f"\n{'='*50}")
            print(f"Depth frame shape : {frame.shape}  dtype={frame.dtype}")
            print(f"Valid pixels      : {len(valid)} / {frame.size} ({100*len(valid)/frame.size:.1f}%)")
            print(f"Valid range       : {valid.min():.0f}mm – {valid.max():.0f}mm")
            print(f"Valid median      : {np.median(valid):.0f}mm ({np.median(valid)/1000:.2f}m)")
            print(f"Sample row (center, every 20px): {frame[frame.shape[0]//2, ::20].tolist()}")
            print(f"{'='*50}\n")

        H, W = frame.shape
        # Focus on the lower 2/3 of the frame (torso/floor level obstacles)
        roi = frame[H // 3 :, :]

        left_dist = self._zone_dist(roi[:, : W // 3])
        center_dist = self._zone_dist(roi[:, W // 3 : 2 * W // 3])
        right_dist = self._zone_dist(roi[:, 2 * W // 3 :])

        print(
            f"\r  depth zones — left: {left_dist/1000:.1f}m  center: {center_dist/1000:.1f}m  right: {right_dist/1000:.1f}m   ",
            end="",
            flush=True,
        )

        new_state = self._classify(center_dist)
        now = time.monotonic()

        state_changed = new_state != self._last_state
        repeat_danger = new_state == "danger" and now - self._last_spoken > self._interval
        if not (state_changed or repeat_danger):
            return

        self._last_state = new_state
        msg = self._build_message(new_state, center_dist, left_dist, right_dist)
        if msg is None:
            return

        self._last_spoken = now
        print(f"\n[AUDIO] {msg}")
        self._speak(msg)

    def _zone_dist(self, zone: np.ndarray) -> float:
        valid = zone[zone > 0]
        if len(valid) == 0:
            return float(self.CLEAR_MM * 2)
        # 10th percentile: robust closest-obstacle estimate, ignores noise
        return float(np.percentile(valid, 10))

    def _classify(self, center_dist: float) -> str:
        if center_dist <= self.DANGER_MM:
            return "danger"
        if center_dist <= self.WARN_MM:
            return "warn"
        return "clear"

    def _build_message(
        self, state: str, center_dist: float, left_dist: float, right_dist: float
    ) -> Optional[str]:
        if state == "clear":
            return None  # path is clear — stay silent

        meters = center_dist / 1000.0
        direction = self._suggest_direction(left_dist, right_dist)

        if state == "danger":
            return f"Stop. Obstacle {meters:.1f} meters. {direction}."
        return f"Obstacle ahead, {meters:.1f} meters. {direction}."

    def _suggest_direction(self, left_dist: float, right_dist: float) -> str:
        margin = 300  # mm — minimum advantage to recommend a side
        if left_dist > right_dist + margin:
            return "Move left"
        if right_dist > left_dist + margin:
            return "Move right"
        return "Stop"

    def _speak(self, text: str) -> None:
        if self._tts_proc and self._tts_proc.poll() is None:
            self._tts_proc.terminate()
        try:
            self._tts_proc = subprocess.Popen(
                ["espeak-ng", "-s", "150", text],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            print("[WARN] espeak-ng not found. Install: sudo pacman -S espeak-ng")
