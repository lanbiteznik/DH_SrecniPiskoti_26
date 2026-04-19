<div align="center">

# VISIONARY

### *See the World. Even Without Sight.*

**Dragon Hack 2026 — Best Accessibility Project**

[![Flutter](https://img.shields.io/badge/Flutter-3.0+-02569B?style=for-the-badge&logo=flutter&logoColor=white)](https://flutter.dev)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![DepthAI](https://img.shields.io/badge/DepthAI-3.0.0-FF6B35?style=for-the-badge)](https://docs.luxonis.com)
[![ElevenLabs](https://img.shields.io/badge/ElevenLabs-TTS%20%2B%20STT-6C63FF?style=for-the-badge)](https://elevenlabs.io)
[![WebSocket](https://img.shields.io/badge/WebSocket-Real--Time-00C896?style=for-the-badge)](https://websockets.readthedocs.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

---

> **"We didn't build an app. We built a pair of eyes."**

VISIONARY is an AI-powered, real-time spatial navigation system for visually impaired individuals. Powered by stereo depth vision, edge-grade neural inference, and neurally synthesized human voice — it turns the surrounding world into a rich, intelligible soundscape of safety and direction. Every millisecond, it watches. Every obstacle, it announces. Every path, it reveals.

</div>

---

## Table of Contents

- [Why VISIONARY?](#why-visionary)
- [How It Works](#how-it-works)
- [Architecture](#architecture)
- [Feature Showcase](#feature-showcase)
- [Technology Stack](#technology-stack)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Project Structure](#project-structure)
- [Team](#team)

---

## Why VISIONARY?

The world was not designed for the blind. Curbs kill, obstacles maim, staircases disorient. Existing solutions — white canes, guide dogs, basic sonar beepers — have changed little in decades. We wanted to do something radical: give visually impaired individuals the full spatial awareness of someone who can see.

VISIONARY fuses a stereo depth camera (OAK-D), a YOLO neural network running at real-time framerates, a multi-zone hazard reasoning engine, and a professional-quality neural voice into a single, wearable system that speaks the world to you — before the world hurts you.

---

## How It Works

```
┌──────────────────────────────────────────────────────────────────┐
│                          OAK-D Camera                           │
│          RGB + Left Stereo + Right Stereo @ 20-30 FPS           │
└───────────────────────────┬──────────────────────────────────────┘
                            │ DepthAI Pipeline
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│                   Neural Inference (YOLO)                        │
│         YOLOv6n / YOLOv10n — 80+ COCO object classes           │
│                  + Stereo Depth Map Generation                   │
└──────────┬──────────────────────────────────────┬───────────────┘
           │ Detections + Depth                   │ Annotations
           ▼                                      ▼
┌──────────────────────────┐        ┌─────────────────────────────┐
│   AssistiveAudioNode     │        │      AnnotationNode          │
│  5-Zone Hazard Analysis  │        │  Visual Debug Overlay        │
│  Closing Speed / TTC     │        └─────────────────────────────┘
│  Hysteresis State Machine│
│  Priority Command Engine │
│  Staircase Detection     │
└────────┬─────────────────┘
         │ Navigation Commands
         ├──────────────────────────────────────┐
         ▼                                      ▼
┌─────────────────────────┐       ┌─────────────────────────────┐
│   ElevenLabs TTS        │       │     WebSocket Server        │
│  Neural Voice Synthesis │       │       Port 8001             │
│  Priority Audio Queue   │       │  Broadcast to all clients   │
│  Interrupt on urgency   │       └──────────┬──────────────────┘
└─────────────────────────┘                  │
                                             ▼
                                ┌─────────────────────────────┐
                                │       Flutter App           │
                                │  iOS / Android / Web / Mac  │
                                │  Cross-platform TTS Client  │
                                │  Voice Search (STT→intent)  │
                                │  Auto-Reconnect WebSocket   │
                                └─────────────────────────────┘
```

---

## Architecture

VISIONARY is a three-tier, real-time system of surgical precision:

### Tier 1 — Perception (`spatial-detections/`)
The OAK-D camera feeds stereo frames into a DepthAI pipeline. A YOLO model performs frame-by-frame object detection across 80+ classes while the stereo pair computes a dense depth map aligned to the RGB view. The depth is temporally smoothed with an exponential moving average to eliminate noise jitter. The result: a live, high-confidence 3D map of everything in front of you.

### Tier 2 — Reasoning (`AssistiveAudioNode`)
The most sophisticated component. Five independent analysis zones are maintained simultaneously:
- **Top, Mid, Bottom cone zones** — trapezoid-shaped bands projecting forward from the camera
- **Left and Right side zones** — for detecting escape corridors

Each zone independently tracks:
- **Occupancy ratio** — how much of the zone is blocked
- **Percentile-based distance** (15th percentile) — ignores sparse outliers, reacts to solid obstacles
- **Closing speed** — derivated from frame-to-frame depth deltas
- **Time-to-Collision (TTC)** — safety buffer that dynamically expands thresholds

A **hysteresis state machine** prevents flickering — an obstacle must clearly recede before the system declares it safe. A **staircase detector** recognizes depth discontinuities consistent with ascending or descending stairs. **Direction stickiness** prevents the system from rapidly alternating left/right commands — a 400mm margin is required to flip direction. Commands are prioritized: `STOP` always plays. `STEP_LEFT`/`STEP_RIGHT` debounce intelligently. `FORWARD` (all clear) plays on refractory schedule.

### Tier 3 — Communication
Two parallel output channels:
1. **Local ElevenLabs TTS** — a priority-based audio queue that can interrupt lower-urgency messages mid-playback. Powered by a threaded subprocess model for zero-latency interruption.
2. **WebSocket Broadcast** — a Python `asyncio` server on port 8001 that pushes structured JSON events to all connected Flutter clients in real time.

---

## Feature Showcase

### Spatial Hazard Detection
- **5-zone simultaneous analysis** — top, mid, bottom cone + left/right side corridors
- **15th-percentile depth sampling** — cuts through noise, responds to real obstacles
- **Stereo depth with temporal smoothing** — eliminates flickering false positives
- **Configurable presets** — `HIGH_DETAIL` depth mode for maximum fidelity

### Intelligent Navigation Commands
| Command | Priority | Trigger Condition |
|---|---|---|
| `STOP` | 100 | Bottom zone blocked < 700mm |
| `STEP_LEFT` | 80 | Forward blocked, left safer |
| `STEP_RIGHT` | 80 | Forward blocked, right safer |
| `WAIT` | 60 | Both sides blocked, object approaching |
| `FORWARD` | 20 | All zones clear |

- **Dynamic thresholds** — TTC calculation expands safety margins for fast-approaching objects
- **Bottom-band priority** — stricter threshold (700mm vs 800mm) to protect against foot-level hazards
- **Confidence scoring** — `HIGH` / `MED` / `LOW` based on zone occupancy and side gap quality
- **Dual behavioral modes** — `safe` (conservative, longer cooldowns) and `confident` (faster response)

### Neural Voice — ElevenLabs TTS
- **Three ElevenLabs APIs in one project** — TTS streaming, STT transcription, voice management
- **Priority-based audio queue** — high-urgency commands interrupt playback of lower-urgency messages
- **Refractory periods** — prevents auditory spam by enforcing inter-command cooldowns
- **Platform-aware TTS abstraction** — single interface, three implementations (mobile, web, stub)
- **Configurable voice** — voice ID, stability, similarity boost all configurable via `.env`

### Voice Search — "Where is the door?"
1. User holds the microphone button in the Flutter app
2. Audio captured from browser/device microphone
3. Sent to **ElevenLabs Scribe STT API** (`scribe_v1` model)
4. **Intent extraction** strips filler words ("where is", "find me the", articles) to isolate the object name
5. Query sent over WebSocket to the Python backend
6. Backend scans live detections — if found, returns **exact distance and direction**
7. ElevenLabs TTS speaks the result: *"Door found. 1.8 meters ahead, slightly left."*

### Cross-Platform Flutter App
| Platform | Status |
|---|---|
| Android | Supported |
| iOS | Supported |
| Web | Supported |
| macOS | Supported |
| Linux | Supported |

- **Auto-reconnecting WebSocket** — 2-second retry with graceful degradation
- **Accessibility-first UI** — high-contrast, large touch targets, minimal visual clutter
- **Color-coded status** — Red (STOP), Orange (caution), Blue (searching), Green (all clear)
- **Animated microphone button** — visual state machine: idle → listening → transcribing → result

### Staircase Detection
- Pattern-match against depth map to identify ascending/descending stairs
- Announces "Stairs ahead — going up" or "Stairs ahead — going down" before user reaches them
- Independent detection path, not reliant on YOLO labels

---

## Technology Stack

### Backend
| Technology | Version | Purpose |
|---|---|---|
| **Python** | 3.10+ | Core backend language |
| **DepthAI** | 3.0.0 | OAK-D camera SDK + neural inference |
| **YOLO** | v6n / v10n | Real-time object detection |
| **websockets** | latest | Async WebSocket server |
| **numpy** | latest | Depth map processing |
| **OpenCV** | latest | Frame processing & annotation |
| **ElevenLabs** | REST API | Neural TTS + STT |

### Frontend
| Technology | Version | Purpose |
|---|---|---|
| **Flutter** | 3.0+ | Cross-platform UI framework |
| **Dart** | 3.0+ | Application language |
| **web_socket_channel** | latest | WebSocket client |
| **elevenlabs_flutter** | latest | Native ElevenLabs SDK |
| **speech_to_text** | latest | Device STT fallback |
| **just_audio** | latest | Cross-platform audio playback |
| **flutter_dotenv** | latest | `.env` configuration loading |
| **http** | latest | HTTP client for ElevenLabs REST |

### Hardware
| Component | Role |
|---|---|
| **OAK-D (Luxonis)** | Stereo depth + RGB vision |
| **RVC2 / RVC4** | On-device neural processing |
| **Any modern smartphone** | Flutter client |

---

## Getting Started

### Prerequisites

- Python 3.10+
- Flutter 3.0+
- An OAK-D camera (OAK-D Lite, OAK-D Pro, or any stereo-capable Luxonis device)
- An [ElevenLabs](https://elevenlabs.io) API key (free tier: 10,000 chars/month)
- `ffplay` installed (for backend TTS playback)

---

### Backend Setup

```bash
# Clone the repo
git clone https://github.com/lanbiteznik/DH_SrecniPiskoti_26.git
cd DH_SrecniPiskoti_26/spatial-detections

# Install Python dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Set your ELEVENLABS_API_KEY in .env

# Run with OAK-D connected
python main.py

# Optional flags
python main.py --mode rvc4          # RVC4 device
python main.py --standalone         # Deploy to device (RVC4 only)
python main.py --safe               # Conservative mode
python main.py --confident          # Fast-response mode
```

The WebSocket server starts automatically on `ws://localhost:8001`.

---

### Flutter App Setup

```bash
cd front_vision_assistant

# Install Flutter dependencies
flutter pub get

# Create .env file
cp .env.example .env
# Set ELEVENLABS_API_KEY and WS_HOST (IP of backend machine)

# Run on device or browser
flutter run                         # Default device
flutter run -d chrome               # Web
flutter run -d android              # Android
```

---

## Configuration

### `.env` (shared pattern)

```dotenv
ELEVENLABS_API_KEY=your_api_key_here
ELEVENLABS_VOICE_ID=EXAVITQu4EsNXjluf0k5   # Bella (default)
WS_HOST=192.168.1.100                        # Backend IP for Flutter
WS_PORT=8001
```

### Key Tunable Parameters

| Parameter | Default | Description |
|---|---|---|
| `DANGER_MM` | `800` | Obstacle distance to trigger warning (mm) |
| `STOP_MM` | `700` | Bottom-zone stop threshold (mm) |
| `TTC_FACTOR` | `1.5` | Time-to-collision threshold multiplier |
| `DIRECTION_HYSTERESIS_MM` | `400` | Margin required to flip left/right command |
| `SAFE_COOLDOWN_S` | `3.0` | Inter-command cooldown in safe mode |
| `CONFIDENT_COOLDOWN_S` | `1.5` | Inter-command cooldown in confident mode |
| `SMOOTHING_ALPHA` | `0.4` | Exponential moving average weight for depth |
| `OCCUPANCY_THRESHOLD` | `0.25` | Min zone occupancy to count as blocked |

---

## Project Structure

```
DH_SrecniPiskoti_26/
│
├── spatial-detections/               # Python perception + reasoning backend
│   ├── main.py                       # DepthAI pipeline orchestration
│   ├── websocket_server.py           # Async WebSocket broadcast server
│   ├── tts_elevenlabs.py             # Backend neural TTS with priority queue
│   ├── requirements.txt
│   ├── depthai_models/
│   │   ├── rvc2/                     # YOLOv6n configs for OAK-D RVC2
│   │   └── rvc4/                     # YOLOv10n configs for OAK-D RVC4
│   └── utils/
│       ├── arguments.py              # CLI argument parser
│       ├── zones.py                  # Zone geometry + depth analysis algorithms
│       ├── assistive_audio_node.py   # Core reasoning engine (the brain)
│       └── annotation_node.py        # Real-time visual debug overlay
│
├── front_vision_assistant/           # Flutter cross-platform client
│   ├── pubspec.yaml
│   └── lib/
│       ├── main.dart                 # App entry point + WebSocket UI
│       ├── config.dart               # Centralized configuration
│       ├── stt_service.dart          # ElevenLabs STT + intent extraction
│       └── tts/
│           ├── tts_interface.dart    # Shared TTS contract
│           ├── tts_factory.dart      # Platform detection + dispatch
│           ├── tts_mobile.dart       # iOS/Android ElevenLabs native SDK
│           ├── tts_web.dart          # Web blob-audio implementation
│           └── tts_stub.dart         # Unsupported platform graceful stub
│
├── app/                              # Navigation service models
│   ├── models.py                     # Detection3D, SectorState, NavigationCommand
│   └── navigation_service.py
│
├── ELEVENLABS_SETUP.md               # ElevenLabs API configuration guide
└── README.md                         # You are here
```

---

## The Team — Srečni Piškoti

> *"Lucky Cookies"* — because when inspiration strikes at 2am, you go with it.

Five developers. One weekend. Zero sleep. Infinite determination.

Built with love for Dragon Hack 2026.

---

<div align="center">

**VISIONARY** — *Because everyone deserves to navigate the world safely.*

*Made with obsession at Dragon Hack 2026*

</div>
