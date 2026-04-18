#!/usr/bin/env python3
"""
Example service for consuming exported capture data and generating instructions.

This demonstrates how to use the CaptureService exports in a separate service
without needing to run the camera pipeline.
"""

import json
import sys
from pathlib import Path
from typing import List
from utils.instruction_generator import InstructionGenerator, Instruction
from utils.capture_service import CaptureFrame, Detection, BoundingBox, SpatialCoordinates


def deserialize_capture_frame(frame_data: dict) -> CaptureFrame:
    """Deserialize a capture frame from JSON data."""
    detections = []
    for det_data in frame_data.get("detections", []):
        detection = Detection(
            label=det_data["label"],
            label_name=det_data["label_name"],
            confidence=det_data["confidence"],
            bounding_box=BoundingBox(
                xmin=det_data["bounding_box"]["xmin"],
                ymin=det_data["bounding_box"]["ymin"],
                xmax=det_data["bounding_box"]["xmax"],
                ymax=det_data["bounding_box"]["ymax"],
            ),
            spatial_coordinates=SpatialCoordinates(
                x=det_data["spatial_coordinates"]["x"],
                y=det_data["spatial_coordinates"]["y"],
                z=det_data["spatial_coordinates"]["z"],
            ),
            timestamp=det_data["timestamp"],
        )
        detections.append(detection)

    return CaptureFrame(
        frame_id=frame_data["frame_id"],
        timestamp=frame_data["timestamp"],
        detections=detections,
        frame_width=frame_data["frame_width"],
        frame_height=frame_data["frame_height"],
    )


def process_captures(capture_file: str) -> List[Instruction]:
    """
    Process exported capture file and generate instructions.

    Args:
        capture_file: Path to exported captures JSON file

    Returns:
        List of generated instructions
    """
    print(f"Loading capture data from {capture_file}...")

    with open(capture_file) as f:
        data = json.load(f)

    print(f"Found {data['total_frames']} frames in capture data")

    # Initialize instruction generator
    generator = InstructionGenerator()

    # Process each frame
    for frame_data in data["frames"]:
        frame = deserialize_capture_frame(frame_data)
        instructions = generator.generate_from_frame(frame)
        
        if instructions:
            for instr in instructions:
                print(
                    f"  Frame {instr.frame_id}: {instr.instruction} "
                    f"({instr.confidence:.0%})"
                )

    return generator.instructions


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python3 instruction_service.py <capture_file.json>")
        print(f"\nExample: python3 instruction_service.py captures/captures_20260419_120000.json")
        sys.exit(1)

    capture_file = sys.argv[1]

    if not Path(capture_file).exists():
        print(f"Error: Capture file not found: {capture_file}")
        sys.exit(1)

    instructions = process_captures(capture_file)
    
    # Generate summary
    print(f"\n{'='*60}")
    print(f"Generated {len(instructions)} instructions from capture data")
    print(f"{'='*60}\n")

    # Show statistics
    if instructions:
        labels = {}
        for instr in instructions:
            labels[instr.target_label] = labels.get(instr.target_label, 0) + 1

        print("Objects detected:")
        for label, count in sorted(labels.items(), key=lambda x: x[1], reverse=True):
            print(f"  - {label}: {count} times")

    # Export instructions
    generator = InstructionGenerator()
    generator.instructions = instructions
    export_file = generator.export_instructions_json()
    print(f"\nInstructions exported to: {export_file}")


if __name__ == "__main__":
    main()
