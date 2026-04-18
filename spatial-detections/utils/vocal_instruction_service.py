"""
Vocal Instruction Service - Converts text instructions to speech.

This service subscribes to capture frames and provides audio feedback
for detected objects and their spatial locations.
"""

import threading
import time
from typing import Optional, Callable
from utils.capture_service import CaptureService, CaptureFrame
from utils.instruction_generator import InstructionGenerator, Instruction


class VocalInstructionService:
    """Service for converting detection instructions to speech."""

    def __init__(self, capture_service: Optional[CaptureService] = None, voice_rate: int = 180):
        """
        Initialize the vocal instruction service.

        Args:
            capture_service: Optional CaptureService to subscribe to
            voice_rate: Speech rate (words per minute)
        """
        self.voice_rate = voice_rate
        self.tts_engine = None
        self.is_speaking = False
        self.speech_queue = []
        self.lock = threading.Lock()

        # Initialize TTS engine
        self._init_tts()

        if capture_service:
            # Subscribe to capture service
            capture_service.subscribe(self._on_new_frame)

    def _init_tts(self):
        """Initialize the text-to-speech engine."""
        try:
            import pyttsx3
            self.tts_engine = pyttsx3.init()

            # Configure voice settings
            self.tts_engine.setProperty('rate', self.voice_rate)

            # Try to set a clear voice
            voices = self.tts_engine.getProperty('voices')
            if voices:
                # Prefer female voice if available
                for voice in voices:
                    if 'female' in voice.name.lower() or 'karen' in voice.name.lower():
                        self.tts_engine.setProperty('voice', voice.id)
                        break

            print("✓ Vocal instruction service initialized with TTS")
        except ImportError:
            print("⚠️  pyttsx3 not installed. Install with: pip install pyttsx3")
            print("   Falling back to print-only mode")
            self.tts_engine = None

    def _on_new_frame(self, frame: CaptureFrame):
        """Called when a new frame is captured."""
        # Generate instructions for this frame
        generator = InstructionGenerator()
        instructions = generator.generate_from_frame(frame)

        # Convert to vocal instructions
        for instruction in instructions:
            self.speak_instruction(instruction)

    def speak_instruction(self, instruction: Instruction):
        """
        Convert an instruction to speech.

        Args:
            instruction: Instruction object to speak
        """
        # Create a more natural vocal instruction
        vocal_text = self._format_vocal_instruction(instruction)

        print(f"🗣️  Speaking: {vocal_text}")

        if self.tts_engine:
            # Add to speech queue
            with self.lock:
                self.speech_queue.append(vocal_text)

            # Start speech thread if not already running
            if not self.is_speaking:
                threading.Thread(target=self._speech_worker, daemon=True).start()
        else:
            # Fallback to print only
            print(f"   (TTS not available - would speak: {vocal_text})")

    def _format_vocal_instruction(self, instruction: Instruction) -> str:
        """
        Format an instruction for natural speech.

        Args:
            instruction: Instruction object

        Returns:
            Formatted text for speech
        """
        spatial_info = instruction.spatial_info

        # Create natural language description
        parts = []

        # Object identification
        parts.append(f"{instruction.target_label}")

        # Position
        position = f"{spatial_info['vertical']} {spatial_info['horizontal']}"
        if position.strip():
            parts.append(f"at {position}")

        # Distance
        distance_desc = spatial_info['distance_category']
        distance_m = spatial_info['distance_meters']

        if distance_desc == "very close":
            parts.append("very close")
        elif distance_desc == "close":
            parts.append("close by")
        elif distance_desc == "medium distance":
            parts.append("at medium distance")
        elif distance_desc == "far":
            parts.append("far away")

        # Confidence (only mention if low)
        if instruction.confidence < 0.8:
            confidence_pct = int(instruction.confidence * 100)
            parts.append(f"with {confidence_pct} percent confidence")

        return " ".join(parts)

    def _speech_worker(self):
        """Background worker for processing speech queue."""
        self.is_speaking = True

        while True:
            vocal_text = None
            with self.lock:
                if self.speech_queue:
                    vocal_text = self.speech_queue.pop(0)

            if vocal_text:
                try:
                    self.tts_engine.say(vocal_text)
                    self.tts_engine.runAndWait()
                    # Small pause between instructions
                    time.sleep(0.5)
                except Exception as e:
                    print(f"Speech error: {e}")
            else:
                # No more items, check again in a moment
                time.sleep(0.1)

                # If queue has been empty for a while, exit
                with self.lock:
                    if not self.speech_queue:
                        break

        self.is_speaking = False

    def speak_text(self, text: str):
        """
        Speak arbitrary text.

        Args:
            text: Text to speak
        """
        print(f"🗣️  Speaking: {text}")

        if self.tts_engine:
            with self.lock:
                self.speech_queue.append(text)

            if not self.is_speaking:
                threading.Thread(target=self._speech_worker, daemon=True).start()
        else:
            print(f"   (TTS not available - would speak: {text})")

    def stop_speech(self):
        """Stop any ongoing speech."""
        if self.tts_engine:
            self.tts_engine.stop()
        with self.lock:
            self.speech_queue.clear()

    def set_voice_rate(self, rate: int):
        """
        Set the speech rate.

        Args:
            rate: Words per minute
        """
        self.voice_rate = rate
        if self.tts_engine:
            self.tts_engine.setProperty('rate', rate)


# Global instance for easy access
_vocal_service = None

def get_vocal_service(capture_service: Optional[CaptureService] = None) -> VocalInstructionService:
    """Get or create the global vocal service instance."""
    global _vocal_service
    if _vocal_service is None:
        _vocal_service = VocalInstructionService(capture_service)
    return _vocal_service