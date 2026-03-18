#!/usr/bin/env python3
"""
Overseer Voice Interface
========================
Press-and-hold to talk to Overseer. Voice in, voice out. No Telegram needed.

Requirements (Mac):
    pip3 install requests keyboard sounddevice numpy scipy

Usage:
    python3 voice-interface.py

Flow:
    Hold SPACE → record → release → Groq Whisper STT → Overseer → macOS TTS
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
import requests

# ── Config ──────────────────────────────────────────────────────────────────

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
PI_HOST = os.environ.get("PI_HOST", "raspberrypi")  # Tailscale hostname
PI_USER = os.environ.get("PI_USER", "mykyta-g")
GATEWAY_PORT = 18789
GATEWAY_TOKEN = os.environ.get("GATEWAY_TOKEN", "")  # Clawdbot gateway auth token
OVERSEER_AGENT = "overseer"
HOTKEY = "space"  # Hold to talk
SAMPLE_RATE = 16000
CHANNELS = 1

# macOS TTS voice (change to your preference)
TTS_VOICE = os.environ.get("TTS_VOICE", "Samantha")  # macOS built-in voices

# ── Colors ──────────────────────────────────────────────────────────────────

class C:
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

def log(icon, msg, color=C.RESET):
    print(f"{color}{icon} {msg}{C.RESET}")

# ── Audio Recording ─────────────────────────────────────────────────────────

class AudioRecorder:
    """Records audio while a key is held down."""

    def __init__(self):
        self.frames = []
        self.recording = False
        self.stream = None

    def start(self):
        try:
            import sounddevice as sd
        except ImportError:
            log("❌", "Install sounddevice: pip3 install sounddevice", C.RED)
            sys.exit(1)

        self.frames = []
        self.recording = True
        log("🎙️", "Recording... (release SPACE to stop)", C.RED)

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

        log("⏹️", "Recording stopped.", C.DIM)

        # Save to temp WAV file
        import numpy as np
        audio_data = np.concatenate(self.frames, axis=0)

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        with wave.open(tmp.name, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio_data.tobytes())

        duration = len(audio_data) / SAMPLE_RATE
        log("📁", f"Saved {duration:.1f}s audio → {tmp.name}", C.DIM)
        return tmp.name

# ── Groq Whisper STT ────────────────────────────────────────────────────────

def transcribe_groq(audio_path: str) -> str:
    """Send audio to Groq Whisper API for transcription."""
    if not GROQ_API_KEY:
        log("❌", "Set GROQ_API_KEY environment variable", C.RED)
        return ""

    log("🧠", "Transcribing via Groq Whisper...", C.YELLOW)

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
        return ""

    text = resp.json().get("text", "").strip()
    log("📝", f"You said: \"{text}\"", C.CYAN)
    return text

# ── Overseer Communication ──────────────────────────────────────────────────

def send_to_overseer(text: str) -> str:
    """Send message to Overseer via SSH tunnel to Pi gateway."""
    log("🛰️", "Sending to Overseer...", C.YELLOW)

    # Use SSH to run a curl command on the Pi (gateway is on loopback)
    # The gateway REST API endpoint for sending a message to an agent session
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
            # Fallback: try direct cron trigger approach
            return send_via_cron_wake(text)

        response = result.stdout.strip()
        try:
            data = json.loads(response)
            reply = data.get("reply", data.get("message", data.get("text", response)))
            log("🛰️", f"Overseer: {reply}", C.GREEN)
            return reply
        except json.JSONDecodeError:
            log("🛰️", f"Overseer: {response}", C.GREEN)
            return response

    except subprocess.TimeoutExpired:
        log("⏰", "Timeout waiting for Overseer", C.RED)
        return "Overseer didn't respond in time."
    except Exception as e:
        log("❌", f"Error: {e}", C.RED)
        return f"Connection error: {e}"


def send_via_cron_wake(text: str) -> str:
    """Fallback: send message by writing to a file and waking Overseer."""
    log("🔄", "Using fallback: cron wake method...", C.YELLOW)

    # Write the message to a temp file on Pi, then wake Overseer
    ssh_write = [
        "ssh", "-o", "ConnectTimeout=5",
        f"{PI_USER}@{PI_HOST}",
        f"echo '{text}' > /tmp/overseer-voice-input.txt && "
        f"clawdbot cron run --name login-brief 2>/dev/null; "
        f"echo 'Message queued for Overseer'",
    ]

    try:
        result = subprocess.run(ssh_write, capture_output=True, text=True, timeout=15)
        return "Message sent to Overseer. Check Telegram for response."
    except Exception as e:
        return f"Fallback failed: {e}"

# ── macOS TTS ───────────────────────────────────────────────────────────────

def speak(text: str):
    """Speak text using macOS built-in TTS."""
    if not text:
        return

    log("🔊", "Speaking...", C.GREEN)

    # Clean text for shell safety
    clean = text.replace("'", "'\\''").replace('"', '\\"')

    # Use macOS say command
    try:
        subprocess.run(
            ["say", "-v", TTS_VOICE, "-r", "180", clean],
            timeout=30,
        )
    except FileNotFoundError:
        # Not on macOS, try espeak as fallback
        try:
            subprocess.run(["espeak", clean], timeout=30)
        except FileNotFoundError:
            log("⚠️", "No TTS available. Install 'say' (macOS) or 'espeak'", C.YELLOW)

# ── Main Loop ───────────────────────────────────────────────────────────────

def check_deps():
    """Check all dependencies are available."""
    missing = []

    if not GROQ_API_KEY:
        missing.append("GROQ_API_KEY not set (export GROQ_API_KEY=your-key)")

    if not GATEWAY_TOKEN:
        missing.append("GATEWAY_TOKEN not set (export GATEWAY_TOKEN=your-token)")

    try:
        import sounddevice
    except ImportError:
        missing.append("sounddevice not installed (pip3 install sounddevice)")

    try:
        import numpy
    except ImportError:
        missing.append("numpy not installed (pip3 install numpy)")

    if missing:
        log("❌", "Missing dependencies:", C.RED)
        for m in missing:
            print(f"   → {m}")
        print()
        log("💡", "Quick fix:", C.YELLOW)
        print("   pip3 install requests sounddevice numpy")
        print("   export GROQ_API_KEY=your-groq-api-key")
        print("   export GATEWAY_TOKEN=your-clawdbot-gateway-token")
        print()
        return False
    return True


def main():
    print(f"""
{C.BOLD}🛰️  Overseer Voice Interface{C.RESET}
{C.DIM}Hold SPACE to talk. Release to send. Ctrl+C to quit.{C.RESET}
{C.DIM}STT: Groq Whisper | Agent: Overseer (Haiku) | TTS: macOS{C.RESET}
""")

    if not check_deps():
        sys.exit(1)

    try:
        import keyboard
    except ImportError:
        log("❌", "Install keyboard: pip3 install keyboard", C.RED)
        log("💡", "Note: requires sudo on macOS for keyboard monitoring", C.YELLOW)
        sys.exit(1)

    recorder = AudioRecorder()

    log("✅", f"Ready. Hold {HOTKEY.upper()} to talk to Overseer.\n", C.GREEN)

    def on_press(event):
        if event.name == HOTKEY and not recorder.recording:
            recorder.start()

    def on_release(event):
        if event.name == HOTKEY and recorder.recording:
            audio_path = recorder.stop()

            if audio_path:
                # Transcribe
                text = transcribe_groq(audio_path)

                # Clean up audio file
                try:
                    os.unlink(audio_path)
                except OSError:
                    pass

                if text:
                    # Send to Overseer
                    response = send_to_overseer(text)

                    # Speak response
                    speak(response)

                print()
                log("✅", f"Ready. Hold {HOTKEY.upper()} to talk.\n", C.GREEN)

    keyboard.on_press(on_press)
    keyboard.on_release(on_release)

    try:
        keyboard.wait("esc")  # ESC to quit
    except KeyboardInterrupt:
        pass

    log("👋", "Overseer Voice Interface stopped.", C.DIM)


if __name__ == "__main__":
    main()
