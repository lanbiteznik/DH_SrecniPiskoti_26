"""
Instruction Generation Service - Consumes capture data and generates instructions.

This service reads detection data from the capture service and can be used
to generate instructions based on detected objects and their spatial locations.
"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from utils.capture_service import CaptureFrame, Detection, CaptureService


@dataclass
class Instruction:
    """A generated instruction based on detections."""
    frame_id: int
    instruction: str
    target_label: str
    confidence: float
    spatial_info: Dict[str, Any]


class InstructionGenerator:
    """Generate instructions based on captured detection data."""

    def __init__(self, capture_service: Optional[CaptureService] = None):
        """
        Initialize the instruction generator.

        Args:
            capture_service: Optional CaptureService instance to subscribe to
        """
        self.capture_service = capture_service
        self.instructions: List[Instruction] = []

        if capture_service:
            # Subscribe to new frames from capture service
            capture_service.subscribe(self._on_new_frame)

    def _on_new_frame(self, frame: CaptureFrame):
        """Called when a new frame is captured."""
        instructions = self.generate_from_frame(frame)
        self.instructions.extend(instructions)
        
        for instr in instructions:
            print(f"[Frame {instr.frame_id}] {instr.instruction}")

    def generate_from_frame(self, frame: CaptureFrame) -> List[Instruction]:
        """
        Generate instructions from a single capture frame.

        Args:
            frame: CaptureFrame with detections

        Returns:
            List of Instruction objects
        """
        instructions = []

        for detection in frame.detections:
            instruction = self._generate_detection_instruction(frame, detection)
            if instruction:
                instructions.append(instruction)

        return instructions

    def _generate_detection_instruction(self, frame: CaptureFrame, detection: Detection) -> Optional[Instruction]:
        """Generate an instruction for a single detection."""
        # Calculate relative position
        bbox_center_x = (detection.bounding_box.xmin + detection.bounding_box.xmax) / 2
        bbox_center_y = (detection.bounding_box.ymin + detection.bounding_box.ymax) / 2
        
        # Determine position in frame
        if bbox_center_x < 0.33:
            horizontal = "left"
        elif bbox_center_x < 0.67:
            horizontal = "center"
        else:
            horizontal = "right"

        if bbox_center_y < 0.33:
            vertical = "top"
        elif bbox_center_y < 0.67:
            vertical = "middle"
        else:
            vertical = "bottom"

        # Determine distance based on Z coordinate
        z_distance = detection.spatial_coordinates.z / 1000  # Convert to meters
        if z_distance < 1.0:
            distance = "very close"
        elif z_distance < 2.0:
            distance = "close"
        elif z_distance < 5.0:
            distance = "medium distance"
        else:
            distance = "far"

        # Generate instruction text
        instruction_text = (
            f"Detected {detection.label_name} at {vertical} {horizontal} "
            f"({distance}, {z_distance:.2f}m away) "
            f"with {detection.confidence:.0%} confidence"
        )

        return Instruction(
            frame_id=frame.frame_id,
            instruction=instruction_text,
            target_label=detection.label_name,
            confidence=detection.confidence,
            spatial_info={
                "horizontal": horizontal,
                "vertical": vertical,
                "distance_meters": z_distance,
                "distance_category": distance,
                "x_mm": detection.spatial_coordinates.x,
                "y_mm": detection.spatial_coordinates.y,
                "z_mm": detection.spatial_coordinates.z,
            },
        )

    def generate_from_export(self, json_file: str) -> List[Instruction]:
        """
        Generate instructions from exported capture JSON file.

        Args:
            json_file: Path to exported capture JSON file

        Returns:
            List of Instruction objects
        """
        with open(json_file) as f:
            data = json.load(f)

        instructions = []
        # This is a simplified version - you'd need to reconstruct CaptureFrame objects
        for frame_data in data.get("frames", []):
            # Reconstruct frame and detections (simplified)
            # In a real implementation, you'd have proper deserialization
            pass

        return instructions

    def export_instructions_json(self, filename: Optional[str] = None) -> str:
        """
        Export generated instructions to JSON.

        Args:
            filename: Output filename

        Returns:
            Path to exported file
        """
        if filename is None:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"instructions_{timestamp}.json"

        filepath = Path("./captures") / filename
        Path("./captures").mkdir(exist_ok=True)

        data = {
            "total_instructions": len(self.instructions),
            "instructions": [
                {
                    "frame_id": instr.frame_id,
                    "instruction": instr.instruction,
                    "target_label": instr.target_label,
                    "confidence": instr.confidence,
                    "spatial_info": instr.spatial_info,
                }
                for instr in self.instructions
            ],
        }

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

        print(f"Exported {len(self.instructions)} instructions to {filepath}")
        return str(filepath)
