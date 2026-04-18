import depthai as dai
from depthai_nodes import PRIMARY_COLOR, SECONDARY_COLOR, TRANSPARENT_PRIMARY_COLOR
from depthai_nodes.utils import AnnotationHelper
from typing import List
import cv2

# Cone trapezoid corners (col, row) — must match AssistiveAudioNode.ZONES geometry.
# Narrow at the top (far away), wide at the bottom (close to camera/feet level).
CONE_TL = (0.35, 0.10)  # top-left
CONE_TR = (0.65, 0.10)  # top-right
CONE_BR = (0.90, 0.90)  # bottom-right
CONE_BL = (0.10, 0.90)  # bottom-left

CONE_COLOR   = (1.0, 1.0, 0.0, 0.85)   # yellow outline
CONE_FILL    = (1.0, 1.0, 0.0, 0.07)   # faint yellow fill
DANGER_COLOR = (1.0, 0.0, 0.0, 1.0)    # red outline for obstacle in cone
DANGER_FILL  = (1.0, 0.0, 0.0, 0.18)   # faint red fill


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

        detections_list: List[dai.SpatialImgDetection] = detections_message.detections

        annotation_helper = AnnotationHelper()

        # Draw the forward-path cone (trapezoid outline + faint fill)
        annotation_helper.draw_polyline(
            points=[CONE_TL, CONE_TR, CONE_BR, CONE_BL],
            outline_color=CONE_COLOR,
            fill_color=CONE_FILL,
            thickness=2.0,
            closed=True,
        )

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
                outline_color=DANGER_COLOR if in_cone else PRIMARY_COLOR,
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

        depth_frame = dai.ImgFrame()
        depth_frame.setCvFrame(depth_map, dai.ImgFrame.Type.BGR888i)
        depth_frame.setTimestamp(depth_message.getTimestamp())
        depth_frame.setSequenceNum(depth_message.getSequenceNum())

        self.out_annotations.send(annotations)
        self.out_depth.send(depth_frame)
