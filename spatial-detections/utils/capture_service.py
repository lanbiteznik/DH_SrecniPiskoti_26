"""
Capture Service - Consumes detection data from the pipeline and exports it.

This service collects spatial detection data and makes it available for
other services like instruction generation.
"""

import json
import threading
from dataclasses import dataclass, asdict
from typing import List, Optional, Callable
from pathlib import Path
from datetime import datetime
from queue import Queue


@dataclass
class SpatialCoordinates:
    """3D spatial coordinates in millimeters."""
    x: float
    y: float
    z: float


@dataclass
class BoundingBox:
    """Normalized bounding box coordinates (0-1)."""
    xmin: float
    ymin: float
    xmax: float
    ymax: float


@dataclass
class Detection:
    """A single detection from the spatial detection network."""
    label: int
    label_name: str
    confidence: float
    bounding_box: BoundingBox
    spatial_coordinates: SpatialCoordinates
    timestamp: float


@dataclass
class CaptureFrame:
    """A single frame capture with all its detections."""
    frame_id: int
    timestamp: float
    detections: List[Detection]
    frame_width: int
    frame_height: int


class CaptureService:
    """Service to consume and export detection data from the camera pipeline."""

    def __init__(self, export_dir: Optional[str] = None, max_buffer_size: int = 100):
        """
        Initialize the capture service.

        Args:
            export_dir: Directory to save captures. If None, uses './captures'
            max_buffer_size: Maximum number of frames to keep in memory
        """
        self.export_dir = Path(export_dir or "./captures")
        self.export_dir.mkdir(exist_ok=True)
        
        self.max_buffer_size = max_buffer_size
        self.buffer: List[CaptureFrame] = []
        self.frame_id = 0
        self.data_queue = Queue()  # For consumers
        self.callbacks: List[Callable[[CaptureFrame], None]] = []
        self.lock = threading.Lock()

    def add_detection(self, detections_msg, classes: List[str], frame_width: int, frame_height: int):
        """
        Add detections from the SpatialDetectionNetwork output.

        Args:
            detections_msg: SpatialImgDetections message from the node
            classes: List of class names
            frame_width: Frame width in pixels
            frame_height: Frame height in pixels
        """
        timestamp = datetime.now().timestamp()
        
        detections = []
        for det in detections_msg.detections:
            detection = Detection(
                label=det.label,
                label_name=classes[det.label] if det.label < len(classes) else f"class_{det.label}",
                confidence=det.confidence,
                bounding_box=BoundingBox(
                    xmin=det.boundingBox.xmin,
                    ymin=det.boundingBox.ymin,
                    xmax=det.boundingBox.xmax,
                    ymax=det.boundingBox.ymax,
                ),
                spatial_coordinates=SpatialCoordinates(
                    x=det.spatialCoordinates.x,
                    y=det.spatialCoordinates.y,
                    z=det.spatialCoordinates.z,
                ),
                timestamp=timestamp,
            )
            detections.append(detection)

        capture_frame = CaptureFrame(
            frame_id=self.frame_id,
            timestamp=timestamp,
            detections=detections,
            frame_width=frame_width,
            frame_height=frame_height,
        )

        with self.lock:
            self.buffer.append(capture_frame)
            if len(self.buffer) > self.max_buffer_size:
                self.buffer.pop(0)
            self.frame_id += 1

        # Push to queue and notify callbacks
        self.data_queue.put(capture_frame)
        for callback in self.callbacks:
            callback(capture_frame)

    def subscribe(self, callback: Callable[[CaptureFrame], None]):
        """
        Subscribe to capture frames.

        Args:
            callback: Function to call with each CaptureFrame
        """
        self.callbacks.append(callback)

    def get_latest_frame(self) -> Optional[CaptureFrame]:
        """Get the most recent capture frame."""
        with self.lock:
            return self.buffer[-1] if self.buffer else None

    def get_frames(self, start_id: int = 0, end_id: Optional[int] = None) -> List[CaptureFrame]:
        """
        Get frames by ID range.

        Args:
            start_id: Starting frame ID (inclusive)
            end_id: Ending frame ID (inclusive), None for latest

        Returns:
            List of CaptureFrame objects
        """
        with self.lock:
            if not self.buffer:
                return []
            
            # Map frame_id to buffer index
            min_frame_id = self.buffer[0].frame_id
            max_frame_id = self.buffer[-1].frame_id
            
            if start_id > max_frame_id or (end_id and end_id < min_frame_id):
                return []
            
            start_idx = max(0, start_id - min_frame_id)
            end_idx = len(self.buffer) if end_id is None else min(len(self.buffer), end_id - min_frame_id + 1)
            
            return self.buffer[start_idx:end_idx]

    def export_json(self, filename: Optional[str] = None) -> str:
        """
        Export buffered frames to JSON.

        Args:
            filename: Output filename. If None, uses timestamp-based name.

        Returns:
            Path to the exported file
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"captures_{timestamp}.json"
        
        filepath = self.export_dir / filename
        
        with self.lock:
            data = {
                "exported_at": datetime.now().isoformat(),
                "total_frames": len(self.buffer),
                "frames": [asdict(frame) for frame in self.buffer],
            }
        
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        
        print(f"Exported {len(self.buffer)} frames to {filepath}")
        return str(filepath)

    def export_jsonl(self, filename: Optional[str] = None) -> str:
        """
        Export buffered frames to JSONL (one JSON object per line).

        Args:
            filename: Output filename. If None, uses timestamp-based name.

        Returns:
            Path to the exported file
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"captures_{timestamp}.jsonl"
        
        filepath = self.export_dir / filename
        
        with self.lock:
            frames = list(self.buffer)
        
        with open(filepath, "w") as f:
            for frame in frames:
                f.write(json.dumps(asdict(frame)) + "\n")
        
        print(f"Exported {len(frames)} frames to {filepath}")
        return str(filepath)

    def clear_buffer(self):
        """Clear the in-memory buffer."""
        with self.lock:
            self.buffer.clear()

    def get_buffer_size(self) -> int:
        """Get current buffer size."""
        with self.lock:
            return len(self.buffer)
