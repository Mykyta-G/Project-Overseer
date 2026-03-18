#!/usr/bin/env python3
"""
Overseer Voice Interface
========================
Wake word "Overseer" or hold SPACE to talk. Voice in, voice out.

Modes:
    --wake-word    Always listening for wake word (default)
    --push-to-talk Hold SPACE to record

Requirements (Mac):
    pip3 install requests sounddevice numpy keyboard pvporcupine pvrecorder

Usage:
    python3 voice-interface.py                    # Wake word mode
    python3 voice-interface.py --push-to-talk     # Fallback: hold SPACE
"""

import os
import sys
import json
import time
import wave
import struct
import tempfile
import subprocess
import threading
import argparse
import requests

# ── Config ──────────────────────────────────────────────────────────────────

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
PICOVOICE_API_KEY = os.environ.get("PICOVOICE_API_KEY", "")
PI_HOST = os.environ.get("PI_HOST", "raspberrypi")
PI_USER = os.environ.get("PI_USER", "mykyta-g")
GATEWAY_PORT = 18789
GATEWAY_TOKEN = os.environ.get("GATEWAY_TOKEN", "")
OVERSEER_AGENT = "overseer"
HOTKEY = "space"
SAMPLE_RATE = 16000
CHANNELS = 1

# Wake word config
# Use a custom .ppn file trained at console.picovoice.ai, or a built-in keyword
WAKE_WORD_PATH = os.environ.get("WAKE_WORD_PATH", "")  # path to custom .ppn file
WAKE_WORD_BUILTIN = os.environ.get("WAKE_WORD_BUILTIN", "jarvis")  # fallback built-in

# Silence detection: stop recording after this many seconds of silence
SILENCE_THRESHOLD = 500  # amplitude threshold for "silence"
SILENCE_DURATION = 1.5   # seconds of silence before stopping
MAX_RECORD_SECONDS = 30  # safety cap

# Tabbie integration
TABBIE_HOST = os.environ.get("TABBIE_HOST", "tabbie.local")
TABBIE_ENABLED = os.environ.get("TABBIE_ENABLED", "true").lower() == "true"

# TTS
TTS_VOICE = os.environ.get("TTS_VOICE", "Samantha")

# ── Colors ──────────────────────────────────────────────────────────────────

class C:
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    MAGENTA = "\033[95m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

def log(icon, msg, color=C.RESET):
    print(f"{color}{icon} {msg}{C.RESET}")

# ── Tabbie Integration ──────────────────────────────────────────────────────

def tabbie_animation(animation: str, task: str = ""):
    """Send animation command to Tabbie."""
    if not TABBIE_ENABLED:
        return
    try:
        payload = {"animation": animation, "task": task}
        requests.post(
            f"http://{TABBIE_HOST}/api/animation",
            json=payload,
            timeout=2,
        )
    except Exception:
        pass  # Tabbie offline is fine — it's optional

def tabbie_status() -> bool:
    """Check if Tabbie is reachable."""
    if not TABBIE_ENABLED:
        return False
    try:
        r = requests.get(f"http://{TABBIE_HOST}/api/status", timeout=2)
        return r.ok
    except Exception:
        return False

# ── Audio Recording ─────────────────────────────────────────────────────────

class AudioRecorder:
    """Records audio with silence detection."""

    def __init__(self):
        self.frames = []
        self.recording = False
        self.stream = None

    def start(self):
        import sounddevice as sd

        self.frames = []
        self.recording = True
        log("🎙️", "Listening... (speak now)", C.RED)
        tabbie_animation("focus", "Listening...")

        def callback(indata, frame_count, time_info, status):
            if self.recording:
                self.frames.append(indata.copy())

        self.stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            callback=callback,
            blocksize=1024,
        )
        self.stream.start()

    def stop(self):
        self.recording = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        if not self.frames:
            return None

        import numpy as np
        audio_data = np.concatenate(self.frames, axis=0)

        # Save to WAV
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        with wave.open(tmp.name, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio_data.tobytes())

        duration = len(audio_data) / SAMPLE_RATE
        log("⏹️", f"Captured {duration:.1f}s audio", C.DIM)
        return tmp.name

    def record_with_silence_detection(self) -> str | None:
        """Record until silence is detected."""
        import sounddevice as sd
        import numpy as np

        self.frames = []
        self.recording = True
        silence_start = None
        has_speech = False
        start_time = time.time()

        log("🎙️", "Listening... (I'll stop when you stop talking)", C.RED)
        tabbie_animation("focus", "Listening...")

        def callback(indata, frame_count, time_info, status):
            nonlocal silence_start, has_speech
            if not self.recording:
                return

            self.frames.append(indata.copy())
            amplitude = np.abs(indata).mean()

            if amplitude > SILENCE_THRESHOLD:
                has_speech = True
                silence_start = None
            elif has_speech and silence_start is None:
                silence_start = time.time()

        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            callback=callback,
            blocksize=1024,
        )

        with stream:
            while self.recording:
                time.sleep(0.05)

                # Safety timeout
                if time.time() - start_time > MAX_RECORD_SECONDS:
                    log("⏰", "Max recording time reached", C.YELLOW)
                    break

                # Silence detection: stop after SILENCE_DURATION of quiet
                if has_speech and silence_start and (time.time() - silence_start) > SILENCE_DURATION:
                    log("🤫", "Silence detected, processing...", C.DIM)
                    break

                # No speech after 5 seconds = probably false trigger
                if not has_speech and (time.time() - start_time) > 5.0:
                    log("🤷", "No speech detected, going back to listening", C.DIM)
                    tabbie_animation("idle")
                    return None

        self.recording = False

        if not self.frames or not has_speech:
            return None

        audio_data = np.concatenate(self.frames, axis=0)
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        with wave.open(tmp.name, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio_data.tobytes())

        duration = len(audio_data) / SAMPLE_RATE
        log("⏹️", f"Captured {duration:.1f}s audio", C.DIM)
        return tmp.name

# ── Wake Word Detection ─────────────────────────────────────────────────────

class WakeWordDetector:
    """Listens for wake word using Picovoice Porcupine."""

    def __init__(self):
        self.porcupine = None
        self.recorder = None

    def initialize(self):
        try:
            import pvporcupine
            from pvrecorder import PvRecorder
        except ImportError:
            log("❌", "Install: pip3 install pvporcupine pvrecorder", C.RED)
            return False

        if not PICOVOICE_API_KEY:
            log("❌", "Set PICOVOICE_API_KEY (free at console.picovoice.ai)", C.RED)
            return False

        try:
            # Try custom wake word file first, then built-in
            if WAKE_WORD_PATH and os.path.exists(WAKE_WORD_PATH):
                log("🎯", f"Loading custom wake word: {WAKE_WORD_PATH}", C.MAGENTA)
                self.porcupine = pvporcupine.create(
                    access_key=PICOVOICE_API_KEY,
                    keyword_paths=[WAKE_WORD_PATH],
                )
            else:
                log("🎯", f"Using built-in wake word: '{WAKE_WORD_BUILTIN}'", C.MAGENTA)
                log("💡", "Train 'Overseer' at console.picovoice.ai for a custom wake word", C.DIM)
                self.porcupine = pvporcupine.create(
                    access_key=PICOVOICE_API_KEY,
                    keywords=[WAKE_WORD_BUILTIN],
                )

            self.recorder = PvRecorder(
                frame_length=self.porcupine.frame_length,
                device_index=-1,  # default mic
            )
            return True

        except Exception as e:
            log("❌", f"Porcupine init failed: {e}", C.RED)
            return False

    def listen(self) -> bool:
        """Block until wake word is detected. Returns True on detection."""
        if not self.porcupine or not self.recorder:
            return False

        self.recorder.start()

        try:
            while True:
                pcm = self.recorder.read()
                keyword_index = self.porcupine.process(pcm)

                if keyword_index >= 0:
                    self.recorder.stop()
                    return True

        except KeyboardInterrupt:
            self.recorder.stop()
            return False

    def cleanup(self):
        if self.recorder:
            try:
                self.recorder.stop()
            except Exception:
                pass
            self.recorder.delete()
        if self.porcupine:
            self.porcupine.delete()

# ── Groq Whisper STT ────────────────────────────────────────────────────────

def transcribe_groq(audio_path: str) -> str:
    """Send audio to Groq Whisper API for transcription."""
    if not GROQ_API_KEY:
        log("❌", "Set GROQ_API_KEY environment variable", C.RED)
        return ""

    log("🧠", "Transcribing via Groq Whisper...", C.YELLOW)
    tabbie_animation("focus", "Thinking...")

    url = "https://api.groq.com/openai/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}

    with open(audio_path, "rb") as f:
        resp = requests.post(
            url,
            headers=headers,
            files={"file": ("audio.wav", f, "audio/wav")},
            data={"model": "whisper-large-v3", "response_format": "json"},
            timeout=30,
        )

    if resp.status_code != 200:
        log("❌", f"Groq error: {resp.status_code} {resp.text}", C.RED)
        tabbie_animation("angry")
        return ""

    text = resp.json().get("text", "").strip()
    log("📝", f"You said: \"{text}\"", C.CYAN)
    return text

# ── Overseer Communication ──────────────────────────────────────────────────

def send_to_overseer(text: str) -> str:
    """Send message to Overseer via SSH to Pi gateway."""
    log("🛰️", "Sending to Overseer...", C.YELLOW)

    curl_cmd = (
        f"curl -s -X POST http://127.0.0.1:{GATEWAY_PORT}/api/sessions/send "
        f"-H 'Content-Type: application/json' "
        f"-H 'Authorization: Bearer {GATEWAY_TOKEN}' "
        f"-d '{json.dumps({\"agentId\": OVERSEER_AGENT, \"message\": text, \"wait\": True, \"timeoutSeconds\": 60})}'"
    )

    ssh_cmd = [
        "ssh", "-o", "ConnectTimeout=5",
        "-o", "StrictHostKeyChecking=no",
        f"{PI_USER}@{PI_HOST}",
        curl_cmd,
    ]

    try:
        result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=90)
        if result.returncode != 0:
            log("❌", f"SSH error: {result.stderr.strip()}", C.RED)
            tabbie_animation("angry")
            return "Connection to Overseer failed."

        response = result.stdout.strip()
        try:
            data = json.loads(response)
            reply = data.get("reply", data.get("message", data.get("text", response)))
        except json.JSONDecodeError:
            reply = response

        log("🛰️", f"Overseer: {reply}", C.GREEN)
        return reply

    except subprocess.TimeoutExpired:
        log("⏰", "Timeout waiting for Overseer", C.RED)
        tabbie_animation("angry")
        return "Overseer didn't respond in time."
    except Exception as e:
        log("❌", f"Error: {e}", C.RED)
        tabbie_animation("angry")
        return f"Error: {e}"

# ── TTS ─────────────────────────────────────────────────────────────────────

def speak(text: str):
    """Speak text using macOS TTS."""
    if not text:
        return

    log("🔊", "Speaking...", C.GREEN)
    tabbie_animation("love", "Speaking")  # happy face while talking

    clean = text.replace("'", "'\\''").replace('"', '\\"')

    try:
        subprocess.run(["say", "-v", TTS_VOICE, "-r", "180", clean], timeout=60)
    except FileNotFoundError:
        try:
            subprocess.run(["espeak", clean], timeout=60)
        except FileNotFoundError:
            log("⚠️", "No TTS engine found", C.YELLOW)

    tabbie_animation("idle")  # back to idle after speaking

# ── Conversation Loop ───────────────────────────────────────────────────────

def process_voice_input(recorder: AudioRecorder, use_silence_detection: bool = True):
    """Record → Transcribe → Overseer → Speak. Full conversation turn."""
    if use_silence_detection:
        audio_path = recorder.record_with_silence_detection()
    else:
        # Push-to-talk: already started, just stop
        audio_path = recorder.stop()

    if not audio_path:
        return

    try:
        # Transcribe
        text = transcribe_groq(audio_path)
    finally:
        try:
            os.unlink(audio_path)
        except OSError:
            pass

    if not text:
        tabbie_animation("idle")
        return

    # Send to Overseer
    response = send_to_overseer(text)

    # Speak response
    speak(response)

# ── Main ────────────────────────────────────────────────────────────────────

def check_deps(mode: str):
    """Check dependencies for the selected mode."""
    missing = []

    if not GROQ_API_KEY:
        missing.append("GROQ_API_KEY (free at https://console.groq.com)")

    if not GATEWAY_TOKEN:
        missing.append("GATEWAY_TOKEN (from clawdbot gateway config)")

    if mode == "wake-word" and not PICOVOICE_API_KEY:
        missing.append("PICOVOICE_API_KEY (free at https://console.picovoice.ai)")

    try:
        import sounddevice
    except ImportError:
        missing.append("pip3 install sounddevice")

    try:
        import numpy
    except ImportError:
        missing.append("pip3 install numpy")

    if mode == "wake-word":
        try:
            import pvporcupine
            from pvrecorder import PvRecorder
        except ImportError:
            missing.append("pip3 install pvporcupine pvrecorder")

    if mode == "push-to-talk":
        try:
            import keyboard
        except ImportError:
            missing.append("pip3 install keyboard (requires sudo on macOS)")

    if missing:
        log("❌", "Missing:", C.RED)
        for m in missing:
            print(f"   → {m}")
        print()
        return False
    return True


def run_wake_word_mode():
    """Main loop: wake word → record with silence detection → process."""
    detector = WakeWordDetector()
    if not detector.initialize():
        log("💡", "Falling back to push-to-talk mode", C.YELLOW)
        run_push_to_talk_mode()
        return

    recorder = AudioRecorder()

    # Check Tabbie connection
    if TABBIE_ENABLED:
        if tabbie_status():
            log("🤖", f"Tabbie connected at {TABBIE_HOST}", C.GREEN)
            tabbie_animation("idle")
        else:
            log("⚠️", f"Tabbie not found at {TABBIE_HOST} (continuing without)", C.YELLOW)

    wake_name = os.path.basename(WAKE_WORD_PATH).replace(".ppn", "") if WAKE_WORD_PATH else WAKE_WORD_BUILTIN
    log("✅", f"Listening for wake word: \"{wake_name}\"", C.GREEN)
    log("💡", "Say the wake word, then speak your message. ESC or Ctrl+C to quit.\n", C.DIM)

    try:
        while True:
            # Wait for wake word
            detected = detector.listen()
            if not detected:
                break

            log("👂", "Wake word detected!", C.MAGENTA)

            # Chime / visual feedback
            tabbie_animation("startup", "Listening...")

            # Small delay for the wake word audio to clear
            time.sleep(0.3)

            # Record with silence detection
            process_voice_input(recorder, use_silence_detection=True)

            print()
            log("👂", f"Listening for \"{wake_name}\"...\n", C.DIM)

    except KeyboardInterrupt:
        pass
    finally:
        detector.cleanup()
        tabbie_animation("idle")
        log("👋", "Voice interface stopped.", C.DIM)


def run_push_to_talk_mode():
    """Fallback: hold SPACE to talk."""
    try:
        import keyboard
    except ImportError:
        log("❌", "pip3 install keyboard", C.RED)
        return

    recorder = AudioRecorder()

    if TABBIE_ENABLED and tabbie_status():
        log("🤖", f"Tabbie connected at {TABBIE_HOST}", C.GREEN)
        tabbie_animation("idle")

    log("✅", f"Push-to-talk mode. Hold {HOTKEY.upper()} to talk. ESC to quit.\n", C.GREEN)

    def on_press(event):
        if event.name == HOTKEY and not recorder.recording:
            recorder.start()

    def on_release(event):
        if event.name == HOTKEY and recorder.recording:
            process_voice_input(recorder, use_silence_detection=False)
            print()
            log("✅", f"Hold {HOTKEY.upper()} to talk.\n", C.GREEN)

    keyboard.on_press(on_press)
    keyboard.on_release(on_release)

    try:
        keyboard.wait("esc")
    except KeyboardInterrupt:
        pass

    tabbie_animation("idle")
    log("👋", "Voice interface stopped.", C.DIM)


def main():
    parser = argparse.ArgumentParser(description="Overseer Voice Interface")
    parser.add_argument("--push-to-talk", action="store_true", help="Hold SPACE to talk (instead of wake word)")
    parser.add_argument("--no-tabbie", action="store_true", help="Disable Tabbie integration")
    args = parser.parse_args()

    global TABBIE_ENABLED
    if args.no_tabbie:
        TABBIE_ENABLED = False

    mode = "push-to-talk" if args.push_to_talk else "wake-word"

    print(f"""
{C.BOLD}🛰️  Overseer Voice Interface{C.RESET}
{C.DIM}Mode: {"Wake Word" if mode == "wake-word" else "Push-to-Talk"}{C.RESET}
{C.DIM}STT: Groq Whisper | Agent: Overseer | TTS: macOS | Tabbie: {"on" if TABBIE_ENABLED else "off"}{C.RESET}
""")

    if not check_deps(mode):
        sys.exit(1)

    if mode == "wake-word":
        run_wake_word_mode()
    else:
        run_push_to_talk_mode()


if __name__ == "__main__":
    main()
