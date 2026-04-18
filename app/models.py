from dataclasses import dataclass
from typing import Optional, List
import time

@dataclass
class Detection3D:
    track_id: Optional[int]
    label: str #class label
    confidence: float # Confidence score from the detection model (0.0–1.0)
    
    # Bounding box coordinates in image space (pixels)
    # Top-left corner (x1, y1), bottom-right corner (x2, y2)
    x1: int
    y1: int
    x2: int
    y2: int

    # 3D spatial coordinates relative to the camera (in millimetres)
    # - z_mm: forward distance from camera (depth)
    # - x_mm: horizontal offset (negative = left, positive = right)
    # - y_mm: vertical offset (negative = down, positive = up)
    x_mm: float
    y_mm: float
    z_mm: float
    timestamp: float

    # Optional tracking status (e.g. "NEW", "TRACKED", "LOST")
    status: Optional[str] = None

@dataclass
class SectorState:
    name: str
    nearest_mm: float
    obstacle_count: int
    occupied: bool

@dataclass
class NavigationCommand:
    code: str         # STOP, LEFT, RIGHT, FORWARD_CLEAR, WARN
    text: str         # "Stop", "Step left", ...
    priority: int
    timestamp: float