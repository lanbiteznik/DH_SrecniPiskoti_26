# Spatial Detection System with Vocal Instructions

A complete computer vision system that detects objects in 3D space and provides vocal feedback using an OAK camera.

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the System
```bash
python3 run_system.py
```

Choose option 1 to start the camera pipeline with vocal instructions.

## 🎯 What It Does

- **Real-time Object Detection**: Detects objects using YOLOv6 on OAK camera
- **3D Spatial Tracking**: Provides X, Y, Z coordinates in millimeters
- **Vocal Feedback**: Speaks detected objects and their positions
- **Data Capture**: Saves all detection data for later analysis
- **Offline Processing**: Process saved captures without camera

## 📁 System Components

- `main.py` - Camera pipeline with vocal instructions
- `run_system.py` - Easy system launcher
- `instruction_service.py` - Offline instruction processor
- `utils/capture_service.py` - Data capture and export
- `utils/vocal_instruction_service.py` - Text-to-speech conversion
- `utils/instruction_generator.py` - Natural language generation

## 🎤 Vocal Output Examples

The system speaks natural descriptions like:
- *"person at middle center close by"*
- *"car at top left very close"*
- *"traffic light at bottom right far away"*

## 💾 Data Export

Captures are automatically saved to `./captures/`:
- `captures_TIMESTAMP.json` - Complete detection data
- `captures_TIMESTAMP.jsonl` - Line-delimited format
- `instructions_TIMESTAMP.json` - Generated instructions

## 🏃 How to Run

### Option 1: Full System (Camera + Voice)
```bash
python3 run_system.py
# Choose option 1
```

### Option 2: Process Saved Data
```bash
python3 run_system.py
# Choose option 2, then select a capture file
```

### Option 3: Direct Commands
```bash
# Run camera pipeline
python3 main.py

# Process specific capture file
python3 instruction_service.py captures/captures_20260419_120000.json
```

## 🔧 Requirements

- OAK camera (OAK-D, OAK-D Lite, etc.)
- Python 3.7+
- Dependencies: depthai, depthai-nodes, pyttsx3

## 🎚️ Configuration

- Voice rate: Configurable in VocalInstructionService
- Buffer size: Adjustable in CaptureService
- Detection model: Change in main.py (currently yolov6-nano-r2-coco)

## 🛠️ Troubleshooting

### No Audio Output
- Install pyttsx3: `pip install pyttsx3`
- Check system TTS settings

### Camera Not Found
- Ensure OAK camera is connected
- Check USB connection
- Try different USB port

### Import Errors
- Install all requirements: `pip install -r requirements.txt`
- Check Python path includes utils directory

## 📊 Architecture

```
Camera Pipeline (main.py)
    ↓
SpatialDetectionNetwork
    ↓
CaptureService ← VocalInstructionService
    ↓
JSON/JSONL Export → InstructionService
```

See `CAPTURE_SERVICE_ARCHITECTURE.md` for detailed documentation.

This will run the example with the default YOLOv6-Nano model.

```bash
python3 main.py --model luxonis/yolov6-large:r2-coco-640x352
```

This will run the example with the specified YOLOv6-Large model.

## Standalone Mode (RVC4 only)

Running the example in the standalone mode, app runs entirely on the device.
To run the example in this mode, first install the `oakctl` tool using the installation instructions [here](https://docs.luxonis.com/software-v3/oak-apps/oakctl).

The app can then be run with:

```bash
oakctl connect <DEVICE_IP>
oakctl app run .
```

This will run the example with default argument values. If you want to change these values you need to edit the `oakapp.toml` file (refer [here](https://docs.luxonis.com/software-v3/oak-apps/configuration/) for more information about this configuration file).
