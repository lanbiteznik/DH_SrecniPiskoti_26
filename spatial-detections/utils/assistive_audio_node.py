import subprocess
import time
from typing import List, Optional, Tuple

import depthai as dai
import numpy as np

from .zones import (
    ZONES, DANGER_MM, WARN_MM, CLEAR_MM,
    OBJ_TIERS, OBSTACLE_CLASSES,
    zone_dist, classify, in_cone,
)

CONFIDENCE_THRESHOLD = 0.45


class AssistiveAudioNode(dai.node.HostNode):
    def __init__(self) -> None:
        super().__init__()
        self.input_depth      = self.createInput()
        self.input_detections = self.createInput()
        self._interval        = 2.0
        self._labels: List[str] = []

        # Zone-based obstacle state
        self._last_state  = "clear"
        self._last_spoken = 0.0

        # Named-object tracking
        # _obj_tier[label] = last announced tier index (0=far, 1=mid, 2=stop)
        self._obj_tier: dict     = {}
        self._obj_spoken_at: dict = {}  # label -> timestamp last spoken

        # Stair detection state
        self._last_stair        = None
        self._last_stair_spoken = 0.0

        self._tts_proc = None

    def build(
        self,
        depth: dai.Node.Output,
        detections: dai.Node.Output,
        labels: List[str],
        interval: float = 2.0,
    ) -> "AssistiveAudioNode":
        self._interval = interval
        self._labels   = labels
        self.link_args(depth, detections)
        return self

    def process(
        self, depth_message: dai.ImgFrame, detections_message: dai.Buffer
    ) -> None:
        frame = depth_message.getCvFrame()
        if not frame.any():
            return

        if not hasattr(self, "_sample_printed"):
            self._sample_printed = True
            self._print_sample(frame)

        dists = {name: zone_dist(frame, *fracs) for name, fracs in ZONES.items()}
        cone_dist_mm = min(dists["cone_top"], dists["cone_mid"], dists["cone_bot"])

        print(
            f"\r  cone={cone_dist_mm/1000:.1f}m"
            f"  left={dists['left']/1000:.1f}m  right={dists['right']/1000:.1f}m   ",
            end="", flush=True,
        )

        now = time.monotonic()

        # --- stair detection ---
        stair = self._detect_stairs(frame)
        stair_changed = stair != self._last_stair
        stair_repeat  = stair is not None and now - self._last_stair_spoken > 3.0
        if stair_changed or stair_repeat:
            self._last_stair = stair
            if stair is not None:
                stair_msg = (
                    "Warning. Stairs going down."
                    if stair == "stairs_down"
                    else "Stairs ahead. Step up."
                )
                self._last_stair_spoken = now
                print(f"\n[AUDIO] {stair_msg}")
                self._speak(stair_msg)
                return

        # --- named object detection ---
        obj_msg, named_in_cone = self._process_detections(detections_message, now)
        if obj_msg:
            print(f"\n[AUDIO] {obj_msg}")
            self._speak(obj_msg)
            return

        # Suppress generic zone alert when a named object is already known to be in the cone
        if named_in_cone:
            return

        # --- zone-based obstacle alert (safety net for unnamed obstacles) ---
        new_state     = classify(cone_dist_mm)
        state_changed = new_state != self._last_state
        repeat_alert  = new_state != "clear" and now - self._last_spoken > self._interval

        if not (state_changed or repeat_alert):
            return

        self._last_state = new_state
        msg = self._build_zone_message(new_state, cone_dist_mm, dists)
        if msg is None:
            return

        self._last_spoken = now
        print(f"\n[AUDIO] {msg}")
        self._speak(msg)

    def _process_detections(
        self, detections_message: dai.Buffer, now: float
    ) -> Tuple[Optional[str], bool]:
        assert isinstance(detections_message, dai.SpatialImgDetections)

        # Filter: confidence, known obstacle class, inside cone
        candidates = []
        for det in detections_message.detections:
            if det.confidence < CONFIDENCE_THRESHOLD:
                continue
            label = self._labels[det.label] if det.label < len(self._labels) else None
            if label not in OBSTACLE_CLASSES:
                continue
            cx = (det.xmin + det.xmax) / 2
            cy = (det.ymin + det.ymax) / 2
            if not in_cone(cx, cy):
                continue
            z = det.spatialCoordinates.z
            if z <= 0:
                continue
            candidates.append((z, label))

        # Labels currently visible in cone
        visible_labels = {label for _, label in candidates}

        # Reset tier for objects that left the cone
        for label in list(self._obj_tier.keys()):
            if label not in visible_labels:
                del self._obj_tier[label]
                self._obj_spoken_at.pop(label, None)

        if not candidates:
            return None, False

        # Sort closest first; pick closest per label
        candidates.sort(key=lambda x: x[0])
        seen: dict = {}
        for z, label in candidates:
            if label not in seen:
                seen[label] = z
        ordered = sorted(seen.items(), key=lambda x: x[1])  # (label, z) closest first

        messages = []
        last_announced_tier = -1

        for label, z in ordered:
            tier = self._tier_for_z(z)
            if tier < 0:
                continue  # beyond 8m

            prev_tier   = self._obj_tier.get(label, -1)
            last_spoken = self._obj_spoken_at.get(label, 0.0)
            cooldown_ok = now - last_spoken > self._interval

            tier_advanced = tier > prev_tier
            repeat_ok     = (tier == prev_tier) and cooldown_ok

            if not (tier_advanced or repeat_ok):
                continue

            self._obj_tier[label]     = tier
            self._obj_spoken_at[label] = now

            dist_m = z / 1000
            if tier == 2:
                msg = f"Stop. {label} ahead."
            else:
                msg = f"{label} ahead, {dist_m:.0f} meters."

            # Include this object if it's the first message or at a different tier
            if not messages or tier != last_announced_tier:
                messages.append(msg)
                last_announced_tier = tier

            if len(messages) == 2:
                break

        combined = " Also ".join(messages) if messages else None

        # named_in_cone is True whenever any valid object is visible, even if no new msg
        named_in_cone = bool(self._obj_tier)
        return combined, named_in_cone

    def _tier_for_z(self, z: float) -> int:
        """Returns tier index (0=far/8m, 1=mid/5m, 2=stop/2m) or -1 if beyond all tiers."""
        for i, threshold in enumerate(OBJ_TIERS):
            if z <= threshold:
                return i
        return -1

    def _detect_stairs(self, frame: np.ndarray) -> Optional[str]:
        H, W = frame.shape
        c0, c1 = int(0.30 * W), int(0.70 * W)
        r0, r1 = int(0.60 * H), int(0.92 * H)
        strip  = frame[r0:r1, c0:c1]
        n_rows = strip.shape[0]

        row_med = np.zeros(n_rows)
        row_ok  = np.zeros(n_rows, dtype=bool)
        min_valid = max(3, strip.shape[1] // 5)
        for i, row in enumerate(strip):
            v = row[row > 0]
            if len(v) >= min_valid:
                row_med[i] = np.median(v)
                row_ok[i]  = True

        if row_ok.sum() < n_rows // 2:
            return None

        xs     = np.where(row_ok)[0]
        filled = np.interp(np.arange(n_rows), xs, row_med[xs])
        k      = max(3, n_rows // 8)
        smoothed = np.convolve(filled, np.ones(k) / k, mode="valid")
        diffs    = np.diff(smoothed)

        if diffs.max() > 600:
            return "stairs_up"

        neg_jumps = diffs[diffs < -250]
        if len(neg_jumps) >= 2 and abs(neg_jumps.sum()) > 500:
            return "stairs_down"

        return None

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
        print("Zone stats (15th pct / median / valid%):")
        for name, (r0, r1, c0, c1) in ZONES.items():
            roi = frame[int(r0*H):int(r1*H), int(c0*W):int(c1*W)]
            v = roi[roi > 0]
            if len(v):
                print(f"  {name:9s}: p15={int(np.percentile(v,15)):5d}mm  "
                      f"median={int(np.median(v)):5d}mm  valid={100*len(v)/roi.size:.0f}%")
            else:
                print(f"  {name:9s}: no valid pixels")
        print(f"{'='*60}\n")

    def _build_zone_message(
        self, state: str, cone_dist: float, dists: dict
    ) -> Optional[str]:
        if state == "clear":
            return None
        direction = self._escape_direction(dists["left"], dists["right"])
        dist_m = cone_dist / 1000
        if state == "danger":
            return f"Stop. Obstacle {dist_m:.1f} meters. {direction}."
        return f"Obstacle {dist_m:.1f} meters ahead. {direction}."

    def _escape_direction(self, left_dist: float, right_dist: float) -> str:
        margin      = 400
        left_clear  = left_dist  > WARN_MM
        right_clear = right_dist > WARN_MM
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
            self._tts_proc.terminate()
        try:
            self._tts_proc = subprocess.Popen(
                ["espeak-ng", "-s", "150", text],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            print("[WARN] espeak-ng not found. Install: sudo pacman -S espeak-ng")
