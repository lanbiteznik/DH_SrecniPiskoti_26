from typing import Any, Dict, List

from app.models import Detection3D


_URGENCY = {
    "STOP": "high",
    "STEP_LEFT": "medium",
    "STEP_RIGHT": "medium",
    "WAIT": "medium",
    "FORWARD": "low",
}

_DIRECTION = {
    "STOP": "ahead",
    "STEP_LEFT": "left",
    "STEP_RIGHT": "right",
    "WAIT": "ahead",
    "FORWARD": "ahead",
}


class NavigationService:
    def __init__(self) -> None:
        self._detections: List[Detection3D] = []

    def update_detections(self, detections: List[Detection3D]) -> None:
        self._detections = detections

    def format_obstacle_message(
        self,
        command: str,
        zone_metrics_map: dict,
        label: str = "obstacle",
    ) -> Dict[str, Any]:
        dist_mm: float = 9_999_000
        for zone in ("cone_bot", "cone_mid", "cone_top"):
            m = zone_metrics_map.get(zone)
            if m is not None and m.dist_mm > 0:
                dist_mm = min(dist_mm, m.dist_mm)

        return {
            "type": "obstacle",
            "label": label,
            "distance": round(dist_mm / 1000.0, 2),
            "direction": _DIRECTION.get(command, "ahead"),
            "urgency": _URGENCY.get(command, "medium"),
        }

    def search(self, query: str) -> Dict[str, Any]:
        query_lower = query.lower().strip()
        if not query_lower:
            return {"type": "search_result", "found": False, "query": query,
                    "distance": None, "direction": None}

        for det in self._detections:
            if query_lower in det.label.lower():
                if det.x_mm < -150:
                    direction = "left"
                elif det.x_mm > 150:
                    direction = "right"
                else:
                    direction = "ahead"
                return {
                    "type": "search_result",
                    "found": True,
                    "query": query,
                    "distance": round(det.z_mm / 1000.0, 2),
                    "direction": direction,
                }

        return {
            "type": "search_result",
            "found": False,
            "query": query,
            "distance": None,
            "direction": None,
        }
