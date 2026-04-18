# Capture Service & Instruction Generation Architecture

This system is designed to separate the camera pipeline from instruction generation, allowing you to capture data and process it separately.

## Components

### 1. **CaptureService** (`utils/capture_service.py`)
The core service that consumes detection data from the camera pipeline.

**Features:**
- Collects spatial detection data in real-time
- Maintains an in-memory buffer (configurable size)
- Supports export to JSON and JSONL formats
- Provides a callback subscription system for real-time data consumption
- Thread-safe operations

**Data Model:**
- `Detection`: Individual detection with label, confidence, bounding box, and spatial coordinates
- `CaptureFrame`: Container for all detections in a single frame
- `SpatialCoordinates`: 3D coordinates (x, y, z) in millimeters
- `BoundingBox`: Normalized 2D coordinates (0-1) of the detection

**Usage in main.py:**
```python
capture_service = CaptureService(export_dir="./captures")
# In the main loop:
detections = detection_queue.tryGet()
if detections is not None:
    capture_service.add_detection(detections, classes, nn_size[0], nn_size[1])
# On exit:
capture_service.export_json()
capture_service.export_jsonl()
```

### 2. **InstructionGenerator** (`utils/instruction_generator.py`)
A service that consumes capture data and generates human-readable instructions.

**Features:**
- Can subscribe to live capture updates
- Generates instructions based on spatial relationships and confidence
- Exports instructions to JSON
- Extensible for custom instruction logic

**Spatial Analysis:**
- Divides frame into 3x3 grid (left/center/right × top/middle/bottom)
- Categorizes depth distance (very close, close, medium, far)
- Generates natural language descriptions

**Example Output:**
```
Detected person at top center (close, 1.23m away) with 94% confidence
Detected cup at bottom left (very close, 0.45m away) with 87% confidence
```

### 3. **InstructionService** (`instruction_service.py`)
A standalone script that processes exported capture files.

**Usage:**
```bash
python3 instruction_service.py captures/captures_20260419_120000.json
```

This allows you to:
- Process captures separately from the pipeline
- Run analysis on historical data
- Generate instructions offline
- Avoid blocking the real-time pipeline

## Workflow

### Real-time Workflow
```
Camera Pipeline
    ↓
SpatialDetectionNetwork (nn.out)
    ↓
CaptureService.add_detection()
    ├→ Buffers data in memory
    ├→ Invokes callbacks
    └→ Queues for consumers
    ↓
Export on Exit
    ├→ JSON file (captures_TIMESTAMP.json)
    └→ JSONL file (captures_TIMESTAMP.jsonl)
```

### Separate Service Workflow
```
Exported Capture File
    ↓
InstructionService (instruction_service.py)
    ↓
InstructionGenerator
    ↓
Output: instructions_TIMESTAMP.json
```

## File Locations

Captures are exported to the `./captures/` directory:
- `captures_YYYYMMDD_HHMMSS.json` - Complete capture data in JSON format
- `captures_YYYYMMDD_HHMMSS.jsonl` - Line-delimited JSON format
- `instructions_YYYYMMDD_HHMMSS.json` - Generated instructions

## Data Format

### JSON Export
```json
{
  "exported_at": "2026-04-19T12:00:00.123456",
  "total_frames": 42,
  "frames": [
    {
      "frame_id": 0,
      "timestamp": 1234567890.123,
      "frame_width": 416,
      "frame_height": 416,
      "detections": [
        {
          "label": 0,
          "label_name": "person",
          "confidence": 0.94,
          "bounding_box": {
            "xmin": 0.2,
            "ymin": 0.1,
            "xmax": 0.8,
            "ymax": 0.9
          },
          "spatial_coordinates": {
            "x": 50.5,
            "y": -23.12,
            "z": 1234.56
          },
          "timestamp": 1234567890.123
        }
      ]
    }
  ]
}
```

## Extending the System

### Custom Instruction Logic
Subclass `InstructionGenerator`:
```python
class CustomInstructionGenerator(InstructionGenerator):
    def _generate_detection_instruction(self, frame, detection):
        # Custom logic here
        pass
```

### Real-time Subscribers
Use callback mechanism:
```python
def on_new_capture(frame):
    print(f"New frame: {frame.frame_id} with {len(frame.detections)} detections")

capture_service.subscribe(on_new_capture)
```

### Custom Export Formats
Add new export methods to `CaptureService`:
```python
def export_csv(self, filename=None):
    # Custom CSV export
    pass
```

## Integration with Other Services

The separated architecture allows you to:

1. **Real-time Instruction Generation**
   - Subscribe to `CaptureService` directly in main pipeline
   - Process instructions on-the-fly

2. **Offline Analysis**
   - Export captures from pipeline
   - Run `InstructionService` on exported data
   - Generate reports or analytics

3. **Machine Learning**
   - Use exported data for model training
   - Analyze detection patterns
   - Improve detection thresholds

4. **UI/Visualization**
   - Feed capture data to dashboard
   - Display real-time statistics
   - Historical analysis of detections

## Performance Considerations

- **Buffer Size**: Default 100 frames; adjust based on memory constraints
- **Export**: Automatic on pipeline exit; can also export manually
- **Callbacks**: Keep callback functions fast to avoid blocking
- **Thread Safety**: All buffer operations are thread-safe
