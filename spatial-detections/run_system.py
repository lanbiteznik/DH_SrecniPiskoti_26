#!/usr/bin/env python3
"""
Spatial Detection System Runner

This script provides an easy way to run the complete spatial detection system
with vocal instructions and data capture.
"""

import sys
import os
from pathlib import Path

# Add utils to path
sys.path.insert(0, str(Path(__file__).parent / "utils"))

def print_header():
    """Print the system header."""
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    SPATIAL DETECTION SYSTEM                                ║
║                    with Vocal Instructions                                ║
╚══════════════════════════════════════════════════════════════════════════════╝
    """)

def check_dependencies():
    """Check if required dependencies are installed."""
    print("🔍 Checking dependencies...")

    missing = []

    try:
        import depthai
        print("✓ depthai available")
    except ImportError:
        missing.append("depthai")

    try:
        import depthai_nodes
        print("✓ depthai-nodes available")
    except ImportError:
        missing.append("depthai-nodes")

    try:
        import pyttsx3
        print("✓ pyttsx3 available")
    except ImportError:
        missing.append("pyttsx3")

    if missing:
        print(f"\n❌ Missing dependencies: {', '.join(missing)}")
        print("Install with: pip install -r requirements.txt")
        return False

    print("✅ All dependencies available")
    return True

def run_main_system():
    """Run the main camera pipeline with vocal instructions."""
    print("\n🚀 Starting Main Camera Pipeline with Vocal Instructions")
    print("=" * 60)

    print("This will:")
    print("• Start the camera pipeline")
    print("• Detect objects in real-time")
    print("• Provide vocal feedback for detected objects")
    print("• Save capture data to ./captures/")
    print("• Press 'q' to stop and export data")
    print()

    confirm = input("Start camera pipeline? (y/n): ").lower().strip()
    if confirm != 'y':
        return

    # Import and run main
    try:
        import main
        # The main.py will handle everything
    except KeyboardInterrupt:
        print("\n⏹️  Pipeline stopped by user")
    except Exception as e:
        print(f"\n❌ Error running pipeline: {e}")
        print("Make sure your OAK camera is connected")

def run_instruction_processor():
    """Run the standalone instruction processor."""
    print("\n📝 Instruction Processor Mode")
    print("=" * 40)

    captures_dir = Path("./captures")
    if not captures_dir.exists():
        print("❌ No captures directory found. Run the main system first.")
        return

    # List available capture files
    json_files = list(captures_dir.glob("*.json"))
    if not json_files:
        print("❌ No capture files found in ./captures/")
        return

    print("Available capture files:")
    for i, file in enumerate(json_files, 1):
        print(f"  {i}. {file.name}")

    try:
        choice = int(input("\nSelect file number (or 0 to cancel): "))
        if choice == 0:
            return
        if 1 <= choice <= len(json_files):
            selected_file = json_files[choice - 1]
            print(f"\nProcessing: {selected_file}")

            # Run instruction processor
            os.system(f"python3 instruction_service.py {selected_file}")
        else:
            print("Invalid choice")
    except ValueError:
        print("Invalid input")

def show_menu():
    """Show the main menu."""
    while True:
        print_header()
        print("Choose an option:")
        print("1. 🚀 Run Camera Pipeline (with vocal instructions)")
        print("2. 📝 Process Saved Captures (generate instructions)")
        print("3. 📚 Show System Architecture")
        print("4. ❌ Exit")
        print()

        try:
            choice = input("Enter choice (1-4): ").strip()

            if choice == "1":
                run_main_system()
            elif choice == "2":
                run_instruction_processor()
            elif choice == "3":
                show_architecture()
            elif choice == "4":
                print("Goodbye! 👋")
                break
            else:
                print("Invalid choice. Please enter 1-4.")

        except KeyboardInterrupt:
            print("\nGoodbye! 👋")
            break

        print("\n" + "="*60)

def show_architecture():
    """Show system architecture information."""
    print("\n🏗️  System Architecture")
    print("=" * 40)

    print("""
SYSTEM COMPONENTS:
──────────────────
1. main.py - Camera pipeline with DepthAI
   • Captures RGB + stereo depth
   • Runs spatial object detection
   • Feeds data to CaptureService

2. CaptureService (utils/capture_service.py)
   • Buffers detection data in memory
   • Exports to JSON/JSONL formats
   • Provides real-time callbacks

3. VocalInstructionService (utils/vocal_instruction_service.py)
   • Converts detections to speech
   • Provides audio feedback
   • Uses pyttsx3 for text-to-speech

4. InstructionGenerator (utils/instruction_generator.py)
   • Creates natural language descriptions
   • Analyzes spatial relationships

DATA FLOW:
──────────
Camera → Detection → CaptureService → VocalInstructions
                              ↓
                           JSON Export → InstructionService

VOCAL OUTPUT EXAMPLES:
─────────────────────
• "person at middle center close by"
• "car at top left very close"
• "traffic light at bottom right far away"

EXPORT FORMATS:
───────────────
• captures_TIMESTAMP.json - Complete structured data
• captures_TIMESTAMP.jsonl - Line-delimited format
• instructions_TIMESTAMP.json - Generated instructions
    """)

    input("\nPress Enter to return to menu...")

def main():
    """Main entry point."""
    if not check_dependencies():
        sys.exit(1)

    show_menu()

if __name__ == "__main__":
    main()