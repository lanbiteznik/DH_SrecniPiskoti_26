import subprocess
import threading
import os
import requests


def _load_env(path: str) -> dict:
    env = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return env


_ENV_PATH = os.path.join(os.path.dirname(__file__), "../front_vision_assistant/.env")
_env = _load_env(_ENV_PATH)

API_KEY = _env.get("ELEVENLABS_API_KEY", "")
VOICE_ID = _env.get("ELEVENLABS_VOICE_ID", "l4Coq6695JDX9xtLqXDE")


class ElevenLabsTTS:
    def __init__(self, api_key: str = API_KEY, voice_id: str = VOICE_ID):
        self._api_key = api_key
        self._voice_id = voice_id
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._priority = 0

    def speak(self, text: str, priority: int = 0) -> None:
        with self._lock:
            if self._proc and self._proc.poll() is None:
                if priority > self._priority:
                    self._proc.terminate()
                else:
                    return
            self._priority = priority

        t = threading.Thread(target=self._fetch_and_play, args=(text,), daemon=True)
        t.start()

    def terminate(self) -> None:
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()

    def _fetch_and_play(self, text: str) -> None:
        try:
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{self._voice_id}/stream"
            headers = {
                "xi-api-key": self._api_key,
                "Content-Type": "application/json",
            }
            body = {
                "text": text,
                "model_id": "eleven_turbo_v2",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            }
            resp = requests.post(url, json=body, headers=headers, stream=True, timeout=10)
            resp.raise_for_status()

            proc = subprocess.Popen(
                ["ffplay", "-nodisp", "-autoexit", "-i", "pipe:0"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            with self._lock:
                self._proc = proc

            for chunk in resp.iter_content(chunk_size=4096):
                if proc.poll() is not None:
                    break
                try:
                    proc.stdin.write(chunk)
                except BrokenPipeError:
                    break
            try:
                proc.stdin.close()
            except Exception:
                pass
            proc.wait()

        except Exception as e:
            print(f"[TTS] ElevenLabs error: {e}")
