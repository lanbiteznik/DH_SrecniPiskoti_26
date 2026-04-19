import json
import threading
from typing import List

import depthai as dai
from flask import Flask, request, jsonify


class SearchNode(dai.node.HostNode):
    def __init__(self) -> None:
        super().__init__()
        self.input_detections = self.createInput()
        self._labels: List[str] = []
        self._latest_detections: List[dai.SpatialImgDetection] = []
        self._lock = threading.Lock()

    def build(self, input_detections: dai.Node.Output, labels: List[str]) -> "SearchNode":
        self._labels = labels
        self.link_args(input_detections)
        t = threading.Thread(target=self._run_server, daemon=True)
        t.start()
        return self

    def process(self, detections_msg: dai.Buffer) -> None:
        assert isinstance(detections_msg, dai.SpatialImgDetections)
        with self._lock:
            self._latest_detections = list(detections_msg.detections)

    def _run_server(self) -> None:
        app = Flask(__name__)
        node = self

        @app.route("/search", methods=["GET"])
        def search():
            query = request.args.get("q", "").strip()
            if not query:
                return jsonify({"error": "missing query parameter 'q'"}), 400
            result = node._handle_search(query)
            return jsonify(result)

        print("[SearchNode] REST API listening on http://0.0.0.0:8080")
        app.run(host="0.0.0.0", port=8080, debug=False, use_reloader=False)

    def _handle_search(self, query: str) -> dict:
        with self._lock:
            detections = list(self._latest_detections)

        matches = []
        for det in detections:
            if det.label < len(self._labels):
                label = self._labels[det.label]
                if query.lower() in label.lower():
                    matches.append((det, label))

        if not matches:
            return {"found": False, "query": query}

        det, label = min(matches, key=lambda t: t[0].spatialCoordinates.z)
        z_mm = det.spatialCoordinates.z
        x_mm = det.spatialCoordinates.x

        if x_mm < -150:
            direction = "left"
        elif x_mm > 150:
            direction = "right"
        else:
            direction = "ahead"

        distance_m = round(z_mm / 1000.0, 1)
        print(f"[SearchNode] Found '{label}' at {distance_m}m {direction} (query='{query}')")

        return {
            "found": True,
            "query": query,
            "label": label,
            "distance": distance_m,
            "direction": direction,
        }
