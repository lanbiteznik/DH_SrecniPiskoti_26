import subprocess
import time
from typing import List, Optional, TYPE_CHECKING

import depthai as dai
import numpy as np

from .zones import (
    ZONES,
    get_zone_metrics,
    decide_command,
    command_confidence,
    SIDE_MARGIN_MM,
)

if TYPE_CHECKING:
    from websocket_server import WebSocketBridge


def _clean_label(label: str) -> str:
    mapping = {
        "dining table": "table",
        "potted plant": "plant",
        "tvmonitor": "screen",
        "cell phone": "phone",
    }
    return mapping.get(label.lower(), label.lower())


class AssistiveAudioNode(dai.node.HostNode):
    DIRECTION_FLIP_EXTRA_MARGIN_MM = 400

    COMMAND_TEXT = {
        "STOP": "Stop.",
        "STEP_LEFT": "Step left.",
        "STEP_RIGHT": "Step right.",
        "WAIT": "Wait.",
        "FORWARD": "Forward.",
    }

    COMMAND_PRIORITY = {
        "STOP": 100,
        "STEP_LEFT": 70,
        "STEP_RIGHT": 70,
        "WAIT": 50,
        "FORWARD": 10,
    }

    SAFE_CONFIRM_SECONDS = {
        "STOP": 0.0,
        "STEP_LEFT": 0.40,
        "STEP_RIGHT": 0.40,
        "WAIT": 0.60,
        "FORWARD": 1.00,
    }

    CONFIDENT_CONFIRM_SECONDS = {
        "STOP": 0.0,
        "STEP_LEFT": 0.25,
        "STEP_RIGHT": 0.25,
        "WAIT": 0.35,
        "FORWARD": 0.60,
    }

    SAFE_COOLDOWN_SECONDS = {
        "STOP": 0.0,
        "STEP_LEFT": 1.8,
        "STEP_RIGHT": 1.8,
        "WAIT": 2.2,
        "FORWARD": 3.5,
    }

    CONFIDENT_COOLDOWN_SECONDS = {
        "STOP": 0.0,
        "STEP_LEFT": 1.0,
        "STEP_RIGHT": 1.0,
        "WAIT": 1.4,
        "FORWARD": 2.0,
    }

    def __init__(self) -> None:
        super().__init__()
        self.input_depth = self.createInput()
        self.input_detections = self.createInput()

        self._interval = 2.0
        self._mode = "safe"
        self.labels: List[str] = []

        self._tts_proc = None
        self._tts_priority = 0

        self._smoothing_alpha = 0.25
        self._smoothed_dists: dict[str, float] = {}

        self._last_state = "clear"
        self._last_command: Optional[str] = None
        self._last_spoken: float = 0.0

        self._candidate_command: Optional[str] = None
        self._candidate_since: float = 0.0

        self._refractory_until: float = 0.0
        self._last_nonstop_command: Optional[str] = None

        self._last_stair: Optional[str] = None
        self._last_stair_spoken: float = 0.0

        self._history: list[tuple[float, str, str]] = []

        # WebSocket bridge (set after build)
        self._ws: Optional["WebSocketBridge"] = None
        # Recent detections for search queries: label → (distance_m, direction, timestamp)
        self._recent_detections: dict[str, tuple[float, str, float]] = {}

    def build(
        self,
        depth: dai.Node.Output,
        detections: dai.Node.Output,
        labels: List[str],
        interval: float = 2.0,
        mode: str = "safe",
        ws: Optional["WebSocketBridge"] = None,
    ) -> "AssistiveAudioNode":
        self._interval = interval
        self._mode = mode
        self.labels = labels
        self._ws = ws
        if ws is not None:
            ws.set_search_callback(self._handle_search)
        self.link_args(depth, detections)
        return self

    @property
    def _confirm_seconds(self) -> dict[str, float]:
        return (
            self.CONFIDENT_CONFIRM_SECONDS
            if self._mode == "confident"
            else self.SAFE_CONFIRM_SECONDS
        )

    @property
    def _cooldown_seconds(self) -> dict[str, float]:
        return (
            self.CONFIDENT_COOLDOWN_SECONDS
            if self._mode == "confident"
            else self.SAFE_COOLDOWN_SECONDS
        )

    @property
    def _refractory_duration(self) -> float:
        return 0.9 if self._mode == "confident" else 1.3

    def process(
        self,
        depth_message: dai.ImgFrame,
        detections_message: dai.Buffer,
    ) -> None:
        assert isinstance(detections_message, dai.SpatialImgDetections)

        frame = depth_message.getCvFrame()
        if frame is None or not frame.any():
            return

        if not hasattr(self, "_sample_printed"):
            self._sample_printed = True
            self._print_sample(frame)

        zone_metrics_map = get_zone_metrics(frame)

        # Smooth only distances for calmer audio
        for name, metrics in zone_metrics_map.items():
            metrics.dist_mm = self._smooth_distance(name, metrics.dist_mm)

        self._update_recent_detections(detections_message)

        candidate, state = decide_command(zone_metrics_map, self._last_state)
        self._last_state = state
        confidence = command_confidence(zone_metrics_map, candidate)
        now = time.monotonic()

        self._debug_print(candidate, zone_metrics_map, confidence)

        # Stair detection gets high priority
        stair = self._detect_stairs(frame)
        stair_changed = stair != self._last_stair
        stair_repeat = stair is not None and now - self._last_stair_spoken > 3.0
        if stair_changed or stair_repeat:
            self._last_stair = stair
            if stair is not None:
                stair_msg = (
                    "Stairs ahead. Step up."
                    if stair == "stairs_down"
                    else "Warning. Stairs going down."
                )
                self._last_stair_spoken = now
                print(f"\n[AUDIO] {stair_msg}")
                self._speak(stair_msg, priority=90)
                if self._ws:
                    self._ws.broadcast({
                        "type": "obstacle",
                        "label": "stairs",
                        "distance": 1.0,
                        "direction": "ahead",
                        "urgency": "high",
                    })
                return

        if candidate is None:
            self._candidate_command = None
            return

        candidate = self._apply_direction_stickiness(candidate, zone_metrics_map, now)

        if candidate != self._candidate_command:
            self._candidate_command = candidate
            self._candidate_since = now
            return

        confirm_seconds = self._confirm_seconds.get(candidate, 0.4)
        if now - self._candidate_since < confirm_seconds:
            return

        if not self._should_speak(candidate, now):
            return

        hazard_label = None
        if confidence in {"HIGH", "MED"}:
            hazard_label = self._get_primary_hazard_label(detections_message)

        spoken = self._compose_message(candidate, hazard_label)

        self._last_command = candidate
        self._last_spoken = now

        if candidate != "STOP":
            self._last_nonstop_command = candidate
            self._refractory_until = now + self._refractory_duration

        self._history.append((now, candidate, spoken))
        self._history = self._history[-5:]

        print(f"\n[AUDIO] {spoken}")
        self._speak(spoken, priority=self.COMMAND_PRIORITY[candidate])
        self._broadcast_obstacle(candidate, hazard_label, zone_metrics_map)

    def _label_name(self, label_idx: int) -> str:
        if 0 <= label_idx < len(self.labels):
            return _clean_label(self.labels[label_idx])
        return "obstacle"

    def _get_primary_hazard_label(
        self, detections_message: dai.SpatialImgDetections
    ) -> Optional[str]:
        closest_label = None
        closest_z = float("inf")

        for det in detections_message.detections:
            z = det.spatialCoordinates.z
            if z <= 0:
                continue
            if det.confidence < 0.5:
                continue
            if z < closest_z:
                closest_z = z
                closest_label = self._label_name(det.label)

        return closest_label

    def _compose_message(self, candidate: str, hazard_label: Optional[str]) -> str:
        base = self.COMMAND_TEXT[candidate]

        if hazard_label is None:
            return base

        if candidate == "STOP":
            return f"Stop. {hazard_label} ahead."
        if candidate == "WAIT":
            return f"Wait. {hazard_label} ahead."
        if candidate == "STEP_LEFT":
            return f"Step left. {hazard_label} ahead."
        if candidate == "STEP_RIGHT":
            return f"Step right. {hazard_label} ahead."
        return base

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
            cooldown = self._cooldown_seconds.get(candidate, self._interval)
            return (now - self._last_spoken) >= cooldown

        last_priority = self.COMMAND_PRIORITY.get(self._last_command, 0) if self._last_command else 0
        new_priority = self.COMMAND_PRIORITY.get(candidate, 0)

        if new_priority < last_priority and (now - self._last_spoken) < 1.2:
            return False

        if self._last_command == "STEP_LEFT" and candidate == "STEP_RIGHT":
            if (now - self._last_spoken) < 1.5:
                return False

        if self._last_command == "STEP_RIGHT" and candidate == "STEP_LEFT":
            if (now - self._last_spoken) < 1.5:
                return False

        if candidate == "FORWARD":
            if self._last_command not in {"STOP", "WAIT", "STEP_LEFT", "STEP_RIGHT"}:
                return False

        return True

    def _debug_print(self, candidate: Optional[str], zone_metrics_map: dict, confidence: str) -> None:
        top = zone_metrics_map["cone_top"].dist_mm
        mid = zone_metrics_map["cone_mid"].dist_mm
        bot = zone_metrics_map["cone_bot"].dist_mm
        left = zone_metrics_map["left"].dist_mm
        right = zone_metrics_map["right"].dist_mm
        occ_l = zone_metrics_map["left"].occupied_ratio
        occ_r = zone_metrics_map["right"].occupied_ratio

        print(
            "\r"
            f"mode={self._mode} "
            f"top={top/1000:.1f}m "
            f"mid={mid/1000:.1f}m "
            f"bot={bot/1000:.1f}m "
            f"left={left/1000:.1f}m "
            f"right={right/1000:.1f}m "
            f"occL={occ_l:.2f} "
            f"occR={occ_r:.2f} "
            f"state={self._last_state} "
            f"conf={confidence} "
            f"cand={candidate or '-'} "
            f"last={self._last_command or '-'}     ",
            end="",
            flush=True,
        )

    def _detect_stairs(self, frame: np.ndarray) -> Optional[str]:
        H, W = frame.shape
        c0, c1 = int(0.30 * W), int(0.70 * W)
        r0, r1 = int(0.60 * H), int(0.92 * H)
        strip = frame[r0:r1, c0:c1]
        n_rows = strip.shape[0]

        row_med = np.zeros(n_rows)
        row_ok = np.zeros(n_rows, dtype=bool)
        min_valid = max(3, strip.shape[1] // 5)
        for i, row in enumerate(strip):
            v = row[row > 0]
            if len(v) >= min_valid:
                row_med[i] = np.median(v)
                row_ok[i] = True

        if row_ok.sum() < n_rows // 2:
            return None

        xs = np.where(row_ok)[0]
        filled = np.interp(np.arange(n_rows), xs, row_med[xs])
        k = max(3, n_rows // 8)
        smoothed = np.convolve(filled, np.ones(k) / k, mode="valid")
        diffs = np.diff(smoothed)

        if diffs.max() > 600:
            return "stairs_down"

        neg_jumps = diffs[diffs < -250]
        if len(neg_jumps) >= 2 and abs(neg_jumps.sum()) > 500:
            return "stairs_up"

        return None

    def _update_recent_detections(self, detections_message: dai.SpatialImgDetections) -> None:
        now = time.monotonic()
        for det in detections_message.detections:
            if det.confidence < 0.4:
                continue
            z = det.spatialCoordinates.z
            if z <= 0:
                continue
            label = self._label_name(det.label)
            distance_m = round(z / 1000.0, 2)
            x = det.spatialCoordinates.x
            if x < -150:
                direction = "to your left"
            elif x > 150:
                direction = "to your right"
            else:
                direction = "ahead"
            self._recent_detections[label] = (distance_m, direction, now)

        # Expire detections older than 5 seconds
        self._recent_detections = {
            k: v for k, v in self._recent_detections.items() if now - v[2] < 5.0
        }

    def _broadcast_obstacle(
        self,
        command: str,
        hazard_label: Optional[str],
        zone_metrics_map: dict,
    ) -> None:
        if self._ws is None:
            return
        if command == "FORWARD":
            return

        urgency_map = {
            "STOP": "high",
            "STEP_LEFT": "medium",
            "STEP_RIGHT": "medium",
            "WAIT": "medium",
        }
        direction_map = {
            "STOP": "back",
            "STEP_LEFT": "left",
            "STEP_RIGHT": "right",
            "WAIT": "ahead",
        }

        cone_dists = [
            zone_metrics_map["cone_top"].dist_mm,
            zone_metrics_map["cone_mid"].dist_mm,
            zone_metrics_map["cone_bot"].dist_mm,
        ]
        distance_m = round(min(d for d in cone_dists if d > 0) / 1000.0, 2)

        self._ws.broadcast({
            "type": "obstacle",
            "label": hazard_label or "obstacle",
            "distance": distance_m,
            "direction": direction_map.get(command, "ahead"),
            "urgency": urgency_map.get(command, "medium"),
        })

    def _handle_search(self, query: str, ws) -> None:
        now = time.monotonic()
        best_label = None
        best_dist = float("inf")
        best_dir = "ahead"

        for label, (dist_m, direction, ts) in self._recent_detections.items():
            if now - ts > 5.0:
                continue
            if query in label or label in query:
                if dist_m < best_dist:
                    best_dist = dist_m
                    best_label = label
                    best_dir = direction

        if best_label is not None:
            self._ws.send_to(ws, {
                "type": "search_result",
                "found": True,
                "query": query,
                "distance": best_dist,
                "direction": best_dir,
            })
            print(f"[SEARCH] '{query}' → found: {best_label} at {best_dist}m {best_dir}")
        else:
            self._ws.send_to(ws, {
                "type": "search_result",
                "found": False,
                "query": query,
            })
            print(f"[SEARCH] '{query}' → not found in recent detections")

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
                ["espeak-ng", "-s", "145", text],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._tts_priority = priority
        except FileNotFoundError:
            print("[WARN] espeak-ng not found. Install: sudo pacman -S espeak-ng")