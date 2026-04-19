import depthai as dai
from depthai_nodes import PRIMARY_COLOR, SECONDARY_COLOR, TRANSPARENT_PRIMARY_COLOR
from depthai_nodes.utils import AnnotationHelper
from typing import List, Optional, Tuple
import cv2

from .zones import (
    ZONES,
    CONE_TL,
    CONE_TR,
    CONE_BR,
    CONE_BL,
    get_zone_metrics,
    classify,
    decide_command,
    command_confidence,
)

# Colors: (R, G, B, A)
CONE_OUTLINE = (1.0, 1.0, 0.0, 0.9)
CONE_FILL = (1.0, 1.0, 0.0, 0.06)
DANGER_OUTLINE = (1.0, 0.0, 0.0, 1.0)
DANGER_FILL = (1.0, 0.0, 0.0, 0.20)
WARN_OUTLINE = (1.0, 0.55, 0.0, 1.0)
WARN_FILL = (1.0, 0.55, 0.0, 0.14)
CLEAR_OUTLINE = (0.0, 1.0, 0.3, 0.7)
CLEAR_FILL = (0.0, 1.0, 0.3, 0.05)

STATE_COLORS = {
    "danger": (DANGER_OUTLINE, DANGER_FILL),
    "warn": (WARN_OUTLINE, WARN_FILL),
    "clear": (CLEAR_OUTLINE, CLEAR_FILL),
}

COMMAND_TEXT = {
    "STOP": "STOP",
    "STEP_LEFT": "STEP LEFT",
    "STEP_RIGHT": "STEP RIGHT",
    "WAIT": "WAIT",
    "FORWARD": "FORWARD",
}

CONFIDENCE_COLORS = {
    "HIGH": (0.0, 1.0, 0.3, 1.0),
    "MED": (1.0, 0.85, 0.0, 1.0),
    "LOW": (1.0, 0.35, 0.0, 1.0),
}

# Only show zone overlays for the cone bands (not escape corridors — too cluttered)
CONE_ZONES = ("cone_top", "cone_mid", "cone_bot")


def _in_cone(cx: float, cy: float) -> bool:
    r0, r1 = CONE_TL[1], CONE_BL[1]
    if not (r0 <= cy <= r1):
        return False
    t = (cy - r0) / (r1 - r0)
    left = CONE_TL[0] + t * (CONE_BL[0] - CONE_TL[0])
    right = CONE_TR[0] + t * (CONE_BR[0] - CONE_TR[0])
    return left <= cx <= right


def _clean_label(label: str) -> str:
    mapping = {
        "dining table": "table",
        "potted plant": "plant",
        "tvmonitor": "screen",
        "cell phone": "phone",
    }
    return mapping.get(label.lower(), label.lower())


class AnnotationNode(dai.node.HostNode):
    def __init__(self) -> None:
        super().__init__()
        self.input_detections = self.createInput()
        self.out_annotations = self.createOutput(
            possibleDatatypes=[
                dai.Node.DatatypeHierarchy(dai.DatatypeEnum.ImgAnnotations, True)
            ]
        )
        self.out_depth = self.createOutput(
            possibleDatatypes=[
                dai.Node.DatatypeHierarchy(dai.DatatypeEnum.ImgFrame, True)
            ]
        )
        self.labels: List[str] = []
        self._last_state = "clear"
        self._last_command: Optional[str] = None

    def build(
        self,
        input_detections: dai.Node.Output,
        depth: dai.Node.Output,
        labels: List[str],
    ) -> "AnnotationNode":
        self.labels = labels
        self.link_args(input_detections, depth)
        return self

    def _closest_detection_label(
        self, detections_list: List[dai.SpatialImgDetection]
    ) -> Optional[Tuple[str, float]]:
        closest = None
        closest_z = float("inf")

        for d in detections_list:
            z = d.spatialCoordinates.z
            if z <= 0:
                continue
            if z < closest_z:
                closest_z = z
                closest = d

        if closest is None:
            return None

        label = self.labels[closest.label] if 0 <= closest.label < len(self.labels) else "obstacle"
        return _clean_label(label), closest_z

    def process(
        self, detections_message: dai.Buffer, depth_message: dai.ImgFrame
    ) -> None:
        assert isinstance(detections_message, dai.SpatialImgDetections)

        depth_frame = depth_message.getCvFrame()
        zone_metrics_map = get_zone_metrics(depth_frame)
        command, state = decide_command(zone_metrics_map, self._last_state)
        self._last_state = state
        if command:
            self._last_command = command

        confidence = command_confidence(zone_metrics_map, command)

        annotation_helper = AnnotationHelper()

        # Draw cone zone bands
        for name in CONE_ZONES:
            r0, r1, c0, c1 = ZONES[name]
            d = zone_metrics_map[name].dist_mm
            zone_state = classify(d)
            outline, fill = STATE_COLORS[zone_state]
            annotation_helper.draw_rectangle(
                top_left=(c0, r0),
                bottom_right=(c1, r1),
                outline_color=outline,
                fill_color=fill,
                thickness=1.5,
            )
            annotation_helper.draw_text(
                text=f"{d/1000:.1f}m",
                position=(c0 + 0.01, r0 + 0.04),
                size=11,
                color=outline,
            )

        # Draw overall cone
        annotation_helper.draw_polyline(
            points=[CONE_TL, CONE_TR, CONE_BR, CONE_BL],
            outline_color=CONE_OUTLINE,
            fill_color=CONE_FILL,
            thickness=2.0,
            closed=True,
        )

        # Draw escape corridors
        for side in ("left", "right"):
            r0, r1, c0, c1 = ZONES[side]
            d = zone_metrics_map[side].dist_mm
            zone_state = classify(d)
            outline, fill = STATE_COLORS[zone_state]
            annotation_helper.draw_rectangle(
                top_left=(c0, r0),
                bottom_right=(c1, r1),
                outline_color=outline,
                fill_color=fill,
                thickness=1.5,
            )
            annotation_helper.draw_text(
                text=f"{d/1000:.1f}m",
                position=(c0 + 0.01, r0 + 0.04),
                size=11,
                color=outline,
            )

        # Command/status banner
        annotation_helper.draw_text(
            text=f"STATE: {state.upper()}",
            position=(0.03, 0.04),
            size=16,
            color=SECONDARY_COLOR,
        )

        if command:
            annotation_helper.draw_text(
                text=f"CMD: {COMMAND_TEXT.get(command, command)}",
                position=(0.03, 0.09),
                size=18,
                color=SECONDARY_COLOR,
            )

        annotation_helper.draw_text(
            text=f"CONFIDENCE: {confidence}",
            position=(0.03, 0.14),
            size=15,
            color=CONFIDENCE_COLORS[confidence],
        )

        annotation_helper.draw_text(
            text=f"LAST CMD: {COMMAND_TEXT.get(self._last_command, self._last_command or '-')}",
            position=(0.03, 0.19),
            size=14,
            color=SECONDARY_COLOR,
        )

        detections_list: List[dai.SpatialImgDetection] = detections_message.detections
        closest_info = self._closest_detection_label(detections_list)
        if closest_info:
            label, z = closest_info
            annotation_helper.draw_text(
                text=f"HAZARD: {label.upper()} ({z/1000:.1f}m)",
                position=(0.03, 0.24),
                size=14,
                color=SECONDARY_COLOR,
            )

        # Draw detections
        for detection in detections_list:
            xmin, ymin, xmax, ymax = (
                detection.xmin,
                detection.ymin,
                detection.xmax,
                detection.ymax,
            )
            in_cone = _in_cone((xmin + xmax) / 2, (ymin + ymax) / 2)

            annotation_helper.draw_rectangle(
                top_left=(xmin, ymin),
                bottom_right=(xmax, ymax),
                outline_color=DANGER_OUTLINE if in_cone else PRIMARY_COLOR,
                fill_color=DANGER_FILL if in_cone else TRANSPARENT_PRIMARY_COLOR,
                thickness=2.0,
            )
            label = self.labels[detection.label] if 0 <= detection.label < len(self.labels) else "object"
            annotation_helper.draw_text(
                text=(
                    f"{label} {int(detection.confidence * 100)}%\n"
                    f"x: {detection.spatialCoordinates.x:.0f}mm\n"
                    f"y: {detection.spatialCoordinates.y:.0f}mm\n"
                    f"z: {detection.spatialCoordinates.z:.0f}mm"
                ),
                position=(xmin + 0.01, ymin + 0.2),
                size=12,
                color=SECONDARY_COLOR,
            )

        annotations = annotation_helper.build(
            timestamp=detections_message.getTimestamp(),
            sequence_num=detections_message.getSequenceNum(),
        )

        depth_map = depth_message.getCvFrame()
        depth_map = cv2.applyColorMap(
            cv2.convertScaleAbs(depth_map, alpha=0.3), cv2.COLORMAP_JET
        )

        out_frame = dai.ImgFrame()
        out_frame.setCvFrame(depth_map, dai.ImgFrame.Type.BGR888i)
        out_frame.setTimestamp(depth_message.getTimestamp())
        out_frame.setSequenceNum(depth_message.getSequenceNum())

        self.out_annotations.send(annotations)
        self.out_depth.send(out_frame)