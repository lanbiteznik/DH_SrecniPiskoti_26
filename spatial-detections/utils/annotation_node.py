import depthai as dai
from depthai_nodes import PRIMARY_COLOR, SECONDARY_COLOR, TRANSPARENT_PRIMARY_COLOR
from depthai_nodes.utils import AnnotationHelper
from typing import List
import cv2

from .zones import (
    ZONES, CONE_TL, CONE_TR, CONE_BR, CONE_BL,
    DANGER_MM, WARN_MM, zone_dist, classify,
)

# Colors: (R, G, B, A)
CONE_OUTLINE     = (1.0, 1.0, 0.0, 0.9)
CONE_FILL        = (1.0, 1.0, 0.0, 0.06)
DANGER_OUTLINE   = (1.0, 0.0, 0.0, 1.0)
DANGER_FILL      = (1.0, 0.0, 0.0, 0.20)
WARN_OUTLINE     = (1.0, 0.55, 0.0, 1.0)
WARN_FILL        = (1.0, 0.55, 0.0, 0.14)
CLEAR_OUTLINE    = (0.0, 1.0, 0.3, 0.7)
CLEAR_FILL       = (0.0, 1.0, 0.3, 0.05)

STATE_COLORS = {
    "danger": (DANGER_OUTLINE, DANGER_FILL),
    "warn":   (WARN_OUTLINE,   WARN_FILL),
    "clear":  (CLEAR_OUTLINE,  CLEAR_FILL),
}

# Only show zone overlays for the cone bands (not escape corridors — too cluttered)
CONE_ZONES = ("cone_top", "cone_mid", "cone_bot")


def _in_cone(cx: float, cy: float) -> bool:
    r0, r1 = CONE_TL[1], CONE_BL[1]
    if not (r0 <= cy <= r1):
        return False
    t = (cy - r0) / (r1 - r0)
    left  = CONE_TL[0] + t * (CONE_BL[0] - CONE_TL[0])
    right = CONE_TR[0] + t * (CONE_BR[0] - CONE_TR[0])
    return left <= cx <= right


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
        self.labels = []

    def build(
        self,
        input_detections: dai.Node.Output,
        depth: dai.Node.Output,
        labels: List[str],
    ) -> "AnnotationNode":
        self.labels = labels
        self.link_args(input_detections, depth)
        return self

    def process(
        self, detections_message: dai.Buffer, depth_message: dai.ImgFrame
    ) -> None:
        assert isinstance(detections_message, dai.SpatialImgDetections)

        depth_frame = depth_message.getCvFrame()
        dists = {name: zone_dist(depth_frame, *fracs) for name, fracs in ZONES.items()}

        annotation_helper = AnnotationHelper()

        # Draw cone zone bands, colored by their danger state
        for name in CONE_ZONES:
            r0, r1, c0, c1 = ZONES[name]
            d = dists[name]
            state = classify(d)
            outline, fill = STATE_COLORS[state]
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

        # Draw the overall cone trapezoid outline (yellow) on top
        annotation_helper.draw_polyline(
            points=[CONE_TL, CONE_TR, CONE_BR, CONE_BL],
            outline_color=CONE_OUTLINE,
            fill_color=CONE_FILL,
            thickness=2.0,
            closed=True,
        )

        # Draw escape corridor states
        for side in ("left", "right"):
            r0, r1, c0, c1 = ZONES[side]
            d = dists[side]
            state = classify(d)
            outline, fill = STATE_COLORS[state]
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

        # Draw detections — red if inside the cone, default color otherwise
        detections_list: List[dai.SpatialImgDetection] = detections_message.detections
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
            annotation_helper.draw_text(
                text=f"{self.labels[detection.label]} {int(detection.confidence * 100)}% \nx: {detection.spatialCoordinates.x:.2f}mm \ny: {detection.spatialCoordinates.y:.2f}mm \nz:{detection.spatialCoordinates.z:.2f}mm",
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
