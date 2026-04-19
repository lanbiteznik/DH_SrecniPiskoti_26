import subprocess
import time
from typing import Optional

import depthai as dai
import numpy as np

from .zones import (
    ZONES,
    get_zone_metrics,
    decide_command,
    SIDE_MARGIN_MM,
    SIDE_STRONG_MARGIN_MM,
)


class AssistiveAudioNode(dai.node.HostNode):
    # Extra margin required to flip direction shortly after speaking
    DIRECTION_FLIP_EXTRA_MARGIN_MM = 400

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
        "STEP_LEFT": 1.5,
        "STEP_RIGHT": 1.5,
        "WAIT": 2.0,
        "FORWARD": 3.0,
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

    def __init__(self) -> None:
        super().__init__()
        self.input_depth = self.createInput()

        self._interval = 2.0
        self._tts_proc = None
        self._tts_priority = 0

        self._smoothing_alpha = 0.25
        self._smoothed_dists: dict[str, float] = {}

        self._last_state = "clear"
        self._last_command: Optional[str] = None
        self._last_spoken: float = 0.0

        self._candidate_command: Optional[str] = None
        self._candidate_since: float = 0.0

        # Anti-spam controls
        self._refractory_until: float = 0.0
        self._last_nonstop_command: Optional[str] = None

    def build(self, depth: dai.Node.Output, interval: float = 2.0) -> "AssistiveAudioNode":
        self._interval = interval
        self.link_args(depth)
        return self

    def process(self, depth_message: dai.ImgFrame) -> None:
        frame = depth_message.getCvFrame()
        if frame is None or not frame.any():
            return

        if not hasattr(self, "_sample_printed"):
            self._sample_printed = True
            self._print_sample(frame)

        zone_metrics_map = get_zone_metrics(frame)

        # Apply smoothing to distances only for audio behavior
        for name, metrics in zone_metrics_map.items():
            smoothed = self._smooth_distance(name, metrics.dist_mm)
            metrics.dist_mm = smoothed

        candidate, state = decide_command(zone_metrics_map, self._last_state)
        self._last_state = state
        now = time.monotonic()

        self._debug_print(candidate, zone_metrics_map)

        if candidate is None:
            self._candidate_command = None
            return

        # Apply direction stickiness before persistence/speech gating
        candidate = self._apply_direction_stickiness(candidate, zone_metrics_map, now)

        if candidate != self._candidate_command:
            self._candidate_command = candidate
            self._candidate_since = now
            return

        confirm_seconds = self.CONFIRM_SECONDS.get(candidate, 0.4)
        if now - self._candidate_since < confirm_seconds:
            return

        if not self._should_speak(candidate, now):
            return

        self._last_command = candidate
        self._last_spoken = now

        if candidate != "STOP":
            self._last_nonstop_command = candidate
            self._refractory_until = now + 1.2

        spoken = self.COMMAND_TEXT[candidate]
        print(f"\n[AUDIO] {spoken}")
        self._speak(spoken, priority=self.COMMAND_PRIORITY[candidate])

    def _print_sample(self, frame: np.ndarray) -> None:
        H, W = frame.shape
        valid = frame[frame > 0]
        print(f"\n{'='*60}")
        print(f"Frame shape: {frame.shape}  dtype: {frame.dtype}")
        print(f"Valid pixels: {len(valid)}/{frame.size} ({100*len(valid)/frame.size:.1f}%)")
        print(f"Depth range: {valid.min()}mm – {valid.max()}mm  median: {int(np.median(valid))}mm")
        print()
        step_r, step_c = H // 8, W // 16
        grid = frame[step_r//2::step_r, step_c//2::step_c][:8, :16]
        print("Downsampled depth grid (mm), rows=top→bottom, cols=left→right:")
        for row in grid:
            print("  " + "  ".join(f"{v:5d}" if v > 0 else "    0" for v in row))
        print()
        print("Zone stats (p15 / median / valid% / occ%):")
        zone_metrics_map = get_zone_metrics(frame)
        for name in ZONES.keys():
            m = zone_metrics_map[name]
            if m.valid_count > 0:
                print(
                    f"  {name:9s}: p15={int(m.dist_mm):5d}mm  "
                    f"median={int(m.median_mm):5d}mm  "
                    f"valid={100*m.valid_ratio:.0f}%  "
                    f"occ={100*m.occupied_ratio:.0f}%"
                )
            else:
                print(f"  {name:9s}: no valid pixels")
        print(f"{'='*60}\n")

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

    def _apply_direction_stickiness(
        self,
        candidate: str,
        zone_metrics_map: dict,
        now: float,
    ) -> str:
        if candidate not in {"STEP_LEFT", "STEP_RIGHT"}:
            return candidate

        recent_direction = (
            self._last_command in {"STEP_LEFT", "STEP_RIGHT"}
            and (now - self._last_spoken) < 1.5
        )
        if not recent_direction:
            return candidate

        left_dist = zone_metrics_map["left"].dist_mm
        right_dist = zone_metrics_map["right"].dist_mm

        if self._last_command == "STEP_LEFT" and candidate == "STEP_RIGHT":
            required = SIDE_MARGIN_MM + self.DIRECTION_FLIP_EXTRA_MARGIN_MM
            if right_dist <= left_dist + required:
                return "STEP_LEFT"

        if self._last_command == "STEP_RIGHT" and candidate == "STEP_LEFT":
            required = SIDE_MARGIN_MM + self.DIRECTION_FLIP_EXTRA_MARGIN_MM
            if left_dist <= right_dist + required:
                return "STEP_RIGHT"

        return candidate

    def _should_speak(self, candidate: str, now: float) -> bool:
        if candidate == "STOP":
            return True

        if now < self._refractory_until:
            return False

        if candidate == self._last_command:
            cooldown = self.COOLDOWN_SECONDS.get(candidate, self._interval)
            return (now - self._last_spoken) >= cooldown

        last_priority = self.COMMAND_PRIORITY.get(self._last_command, 0) if self._last_command else 0
        new_priority = self.COMMAND_PRIORITY.get(candidate, 0)

        # Avoid immediate downgrade after stronger command
        if new_priority < last_priority and (now - self._last_spoken) < 1.2:
            return False

        # Don't flip directions too quickly
        if self._last_command == "STEP_LEFT" and candidate == "STEP_RIGHT":
            if (now - self._last_spoken) < 1.5:
                return False

        if self._last_command == "STEP_RIGHT" and candidate == "STEP_LEFT":
            if (now - self._last_spoken) < 1.5:
                return False

        # FORWARD should only be spoken as recovery from a blocked state
        if candidate == "FORWARD":
            if self._last_command not in {"STOP", "WAIT", "STEP_LEFT", "STEP_RIGHT"}:
                return False

        return True

    def _debug_print(self, candidate: Optional[str], zone_metrics_map: dict) -> None:
        top = zone_metrics_map["cone_top"].dist_mm
        mid = zone_metrics_map["cone_mid"].dist_mm
        bot = zone_metrics_map["cone_bot"].dist_mm
        left = zone_metrics_map["left"].dist_mm
        right = zone_metrics_map["right"].dist_mm
        occ_l = zone_metrics_map["left"].occupied_ratio
        occ_r = zone_metrics_map["right"].occupied_ratio

        print(
            "\r"
            f"top={top/1000:.1f}m "
            f"mid={mid/1000:.1f}m "
            f"bot={bot/1000:.1f}m "
            f"left={left/1000:.1f}m "
            f"right={right/1000:.1f}m "
            f"occL={occ_l:.2f} "
            f"occR={occ_r:.2f} "
            f"state={self._last_state} "
            f"cand={candidate or '-'} "
            f"last={self._last_command or '-'}     ",
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