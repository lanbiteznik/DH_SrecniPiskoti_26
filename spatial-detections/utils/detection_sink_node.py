from typing import Callable, Optional

import depthai as dai


class DetectionSinkNode(dai.node.HostNode):
    def __init__(self) -> None:
        super().__init__()
        self.input_detections = self.createInput()
        self.on_detections: Optional[Callable] = None

    def build(
        self,
        detections: dai.Node.Output,
        on_detections: Optional[Callable] = None,
    ) -> "DetectionSinkNode":
        self.on_detections = on_detections
        self.link_args(detections)
        return self

    def process(self, detections_msg) -> None:
        if self.on_detections is None:
            return
        try:
            self.on_detections(detections_msg.detections)
        except Exception as e:
            print(f"[DetectionSink] Error: {e}")
