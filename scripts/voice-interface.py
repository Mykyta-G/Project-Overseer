#!/usr/bin/env python3
"""
Overseer Voice Interface v2
===========================
Wake word → listen → Groq STT → Haiku streaming → Edge TTS → interrupt support

Optimizations:
    1. Direct Anthropic API (no SSH overhead)
    2. Streaming responses (speak first sentence while generating rest)
    3. Edge TTS neural voices (free, human-quality)
    4. Interrupt support (speak over Overseer to stop it)

Usage:
    python3 voice-interface.py                    # Wake word mode
    python3 voice-interface.py --push-to-talk     # Fallback: hold SPACE
    python3 voice-interface.py --no-tabbie        # Disable Tabbie face
"""

import os
import sys
import json
import time
import wave
import tempfile
import subprocess
import threading
import argparse
import asyncio
import re
import signal

import requests
import numpy as np
import sounddevice as sd

# ── Config ──────────────────────────────────────────────────────────────────

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
PICOVOICE_API_KEY = os.environ.get("PICOVOICE_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
HAIKU_MODEL = os.environ.get("HAIKU_MODEL", "claude-haiku-4-5-20250414")

# Wake word
WAKE_WORD_PATH = os.environ.get("WAKE_WORD_PATH", "")
WAKE_WORD_BUILTIN = os.environ.get("WAKE_WORD_BUILTIN", "jarvis")

# Audio
SAMPLE_RATE = 16000
CHANNELS = 1
SILENCE_THRESHOLD = 500
SILENCE_DURATION = 1.2    # faster cutoff for natural feel
MAX_RECORD_SECONDS = 30
INTERRUPT_THRESHOLD = 600  # amplitude to trigger interrupt during playback

# Edge TTS
TTS_VOICE = os.environ.get("TTS_VOICE", "en-US-GuyNeural")

# Tabbie
TABBIE_HOST = os.environ.get("TABBIE_HOST", "tabbie.local")
TABBIE_ENABLED = os.environ.get("TABBIE_ENABLED", "true").lower() == "true"

# Conversation history (for context)
MAX_HISTORY = 10
conversation_history = []

# Overseer system prompt
OVERSEER_SYSTEM = """You are Overseer — mission control for an AI agent fleet. You speak out loud via voice.

Personality: Terse, calm, sharp. JARVIS meets senior ops engineer.
- Keep responses SHORT — you're speaking, not writing an essay
- 1-3 sentences for simple queries
- Use natural speech patterns, not bullet points (this is voice, not text)
- Be warm when it counts, brief always
- If you don't know something, say so in one sentence

You coordinate these agents:
- Wizard (Opus) — heavy builds, Simple Schedules project
- Saul (Opus) — research, legal, LegalBuddy
- Killer (Sonnet) — fast ops, quick code
- Gunnar (Haiku) — general tasks
- Forge (Qwen 3 local) — offline, free

Your human is Mykyta, based in Skåne, Sweden. He's building AI infrastructure on a Raspberry Pi.

Important: You're responding via VOICE. Keep it conversational and natural. No markdown, no bullet points, no code blocks. Just talk like a person."""

# ── Logging ─────────────────────────────────────────────────────────────────

class C:
    CYAN = "\033[96m"; GREEN = "\033[92m"; YELLOW = "\033[93m"
    RED = "\033[91m"; MAGENTA = "\033[95m"; DIM = "\033[2m"
    BOLD = "\033[1m"; RESET = "\033[0m"

def log(icon, msg, color=C.RESET):
    print(f"{color}{icon} {msg}{C.RESET}")

# ── Tabbie ──────────────────────────────────────────────────────────────────

def tabbie(animation: str, task: str = ""):
    if not TABBIE_ENABLED:
        return
    try:
        requests.post(f"http://{TABBIE_HOST}/api/animation",
                      json={"animation": animation, "task": task}, timeout=1)
    except Exception:
        pass

# ── 1. Groq Whisper STT ────────────────────────────────────────────────────

def transcribe(audio_path: str) -> str:
    """Groq Whisper — ~300ms, free."""
    log("🧠", "Transcribing...", C.YELLOW)
    tabbie("focus", "Thinking...")

    try:
        with open(audio_path, "rb") as f:
            resp = requests.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                files={"file": ("audio.wav", f, "audio/wav")},
                data={"model": "whisper-large-v3", "response_format": "json"},
                timeout=15,
            )
        if resp.status_code == 200:
            text = resp.json().get("text", "").strip()
            log("📝", f'"{text}"', C.CYAN)
            return text
        else:
            log("❌", f"Groq: {resp.status_code}", C.RED)
    except Exception as e:
        log("❌", f"STT error: {e}", C.RED)
    return ""

# ── 2. Haiku Streaming LLM ─────────────────────────────────────────────────

def stream_haiku(text: str):
    """Stream response from Haiku. Yields text chunks as they arrive."""
    global conversation_history

    conversation_history.append({"role": "user", "content": text})

    # Trim history
    if len(conversation_history) > MAX_HISTORY * 2:
        conversation_history = conversation_history[-(MAX_HISTORY * 2):]

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": HAIKU_MODEL,
                "max_tokens": 300,  # Short for voice
                "system": OVERSEER_SYSTEM,
                "messages": conversation_history,
                "stream": True,
            },
            stream=True,
            timeout=30,
        )

        if resp.status_code != 200:
            log("❌", f"Haiku: {resp.status_code} {resp.text[:200]}", C.RED)
            yield "Sorry, I couldn't process that."
            return

        full_response = ""

        for line in resp.iter_lines():
            if not line:
                continue
            line = line.decode("utf-8")
            if not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break

            try:
                event = json.loads(data)
                if event.get("type") == "content_block_delta":
                    chunk = event.get("delta", {}).get("text", "")
                    if chunk:
                        full_response += chunk
                        yield chunk
            except json.JSONDecodeError:
                continue

        # Save assistant response to history
        if full_response:
            conversation_history.append({"role": "assistant", "content": full_response})

    except Exception as e:
        log("❌", f"LLM error: {e}", C.RED)
        yield "Connection error. Try again."

# ── 3. Edge TTS with Streaming ──────────────────────────────────────────────

class EdgeTTSPlayer:
    """Streams Edge TTS audio with interrupt support."""

    def __init__(self):
        self.playing = False
        self.interrupted = False
        self.process = None
        self._monitor_thread = None

    def speak_sentence(self, text: str) -> bool:
        """Generate and play one sentence. Returns False if interrupted."""
        if self.interrupted or not text.strip():
            return not self.interrupted

        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp_path = tmp.name
        tmp.close()

        try:
            # Generate audio with edge-tts CLI
            result = subprocess.run(
                ["edge-tts", "--voice", TTS_VOICE, "--text", text, "--write-media", tmp_path],
                capture_output=True, timeout=10,
            )

            if result.returncode != 0 or not os.path.exists(tmp_path):
                # Fallback to macOS say
                subprocess.run(["say", "-r", "180", text], timeout=15)
                return not self.interrupted

            if self.interrupted:
                return False

            # Play audio
            self.playing = True
            # Use afplay on macOS, mpv/ffplay on Linux
            try:
                self.process = subprocess.Popen(
                    ["afplay", tmp_path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except FileNotFoundError:
                self.process = subprocess.Popen(
                    ["mpv", "--no-terminal", "--no-video", tmp_path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )

            self.process.wait()
            self.playing = False

            return not self.interrupted

        except Exception as e:
            log("⚠️", f"TTS error: {e}", C.YELLOW)
            return not self.interrupted
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def stop(self):
        """Stop playback immediately."""
        self.interrupted = True
        self.playing = False
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def reset(self):
        """Reset interrupt state for new conversation turn."""
        self.interrupted = False
        self.playing = False
        self.process = None

# ── 4. Interrupt Monitor ────────────────────────────────────────────────────

class InterruptMonitor:
    """Monitors mic while TTS plays. Triggers interrupt on loud audio."""

    def __init__(self, tts_player: EdgeTTSPlayer):
        self.tts = tts_player
        self.triggered = False
        self.running = False
        self._thread = None

    def start(self):
        """Start monitoring mic for interrupts."""
        self.triggered = False
        self.running = True
        self._thread = threading.Thread(target=self._monitor, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop monitoring."""
        self.running = False
        if self._thread:
            self._thread.join(timeout=2)

    def _monitor(self):
        """Background thread: listen for loud audio = interrupt."""
        try:
            stream = sd.InputStream(
                samplerate=SAMPLE_RATE, channels=CHANNELS,
                dtype="int16", blocksize=2048,
            )
            with stream:
                # Wait a moment for TTS to start playing
                time.sleep(0.5)

                while self.running and self.tts.playing:
                    data, _ = stream.read(2048)
                    amplitude = np.abs(data).mean()

                    if amplitude > INTERRUPT_THRESHOLD:
                        log("🤚", "Interrupt detected!", C.MAGENTA)
                        self.triggered = True
                        self.tts.stop()
                        self.running = False
                        return

                    time.sleep(0.05)
        except Exception:
            pass

# ── Audio Recording ─────────────────────────────────────────────────────────

def record_with_silence() -> str | None:
    """Record until silence. Returns path to WAV file."""
    frames = []
    silence_start = None
    has_speech = False
    start_time = time.time()
    recording = True

    log("🎙️", "Listening...", C.RED)
    tabbie("focus", "Listening...")

    def callback(indata, frame_count, time_info, status):
        nonlocal silence_start, has_speech
        if not recording:
            return
        frames.append(indata.copy())
        amplitude = np.abs(indata).mean()

        if amplitude > SILENCE_THRESHOLD:
            has_speech = True
            silence_start = None
        elif has_speech and silence_start is None:
            silence_start = time.time()

    stream = sd.InputStream(
        samplerate=SAMPLE_RATE, channels=CHANNELS,
        dtype="int16", callback=callback, blocksize=1024,
    )

    with stream:
        while recording:
            time.sleep(0.05)
            if time.time() - start_time > MAX_RECORD_SECONDS:
                break
            if has_speech and silence_start and (time.time() - silence_start) > SILENCE_DURATION:
                break
            if not has_speech and (time.time() - start_time) > 5.0:
                log("🤷", "No speech detected", C.DIM)
                tabbie("idle")
                return None

    recording = False

    if not frames or not has_speech:
        return None

    audio = np.concatenate(frames, axis=0)
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    with wave.open(tmp.name, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())

    duration = len(audio) / SAMPLE_RATE
    log("⏹️", f"{duration:.1f}s captured", C.DIM)
    return tmp.name

# ── Wake Word ───────────────────────────────────────────────────────────────

class WakeWordDetector:
    def __init__(self):
        self.porcupine = None
        self.recorder = None

    def initialize(self) -> bool:
        try:
            import pvporcupine
            from pvrecorder import PvRecorder
        except ImportError:
            log("❌", "pip3 install pvporcupine pvrecorder", C.RED)
            return False

        if not PICOVOICE_API_KEY:
            log("❌", "Set PICOVOICE_API_KEY", C.RED)
            return False

        try:
            if WAKE_WORD_PATH and os.path.exists(WAKE_WORD_PATH):
                self.porcupine = pvporcupine.create(
                    access_key=PICOVOICE_API_KEY,
                    keyword_paths=[WAKE_WORD_PATH],
                )
            else:
                self.porcupine = pvporcupine.create(
                    access_key=PICOVOICE_API_KEY,
                    keywords=[WAKE_WORD_BUILTIN],
                )
            self.recorder = PvRecorder(
                frame_length=self.porcupine.frame_length, device_index=-1,
            )
            return True
        except Exception as e:
            log("❌", f"Porcupine: {e}", C.RED)
            return False

    def listen(self) -> bool:
        if not self.porcupine or not self.recorder:
            return False
        self.recorder.start()
        try:
            while True:
                pcm = self.recorder.read()
                if self.porcupine.process(pcm) >= 0:
                    self.recorder.stop()
                    return True
        except KeyboardInterrupt:
            self.recorder.stop()
            return False

    def cleanup(self):
        if self.recorder:
            try: self.recorder.stop()
            except: pass
            self.recorder.delete()
        if self.porcupine:
            self.porcupine.delete()

# ── Sentence Splitter ───────────────────────────────────────────────────────

def split_sentences(text_stream):
    """Buffer streaming text and yield complete sentences."""
    buffer = ""
    # Match sentence endings: . ! ? followed by space or end
    sentence_end = re.compile(r'[.!?]+[\s]|[.!?]+$')

    for chunk in text_stream:
        buffer += chunk

        while True:
            match = sentence_end.search(buffer)
            if match:
                end = match.end()
                sentence = buffer[:end].strip()
                buffer = buffer[end:]
                if sentence:
                    yield sentence
            else:
                break

    # Flush remaining
    if buffer.strip():
        yield buffer.strip()

# ── Main Conversation Loop ──────────────────────────────────────────────────

def conversation_turn(tts: EdgeTTSPlayer):
    """One full conversation turn: record → transcribe → stream response → speak."""

    # Record
    audio_path = record_with_silence()
    if not audio_path:
        return False  # No speech, no interrupt

    try:
        text = transcribe(audio_path)
    finally:
        try: os.unlink(audio_path)
        except: pass

    if not text:
        tabbie("idle")
        return False

    # Stream LLM response + speak sentences as they arrive
    log("🛰️", "Overseer thinking...", C.YELLOW)
    tts.reset()

    # Start interrupt monitor
    monitor = InterruptMonitor(tts)

    full_response = ""
    for sentence in split_sentences(stream_haiku(text)):
        full_response += sentence + " "
        log("🗣️", sentence, C.GREEN)

        # Start monitoring for interrupts once TTS starts
        monitor.start()

        if not tts.speak_sentence(sentence):
            # Interrupted!
            monitor.stop()
            log("🤚", "Stopped. Listening to you...", C.MAGENTA)
            tabbie("idle")
            return True  # Signal: user wants to speak again

        monitor.stop()

    if full_response:
        log("🛰️", f"[{len(full_response.split())} words]", C.DIM)

    tabbie("idle")
    return False  # Normal completion


# ── Push to Talk Mode ───────────────────────────────────────────────────────

def record_push_to_talk() -> str | None:
    """Hold SPACE to record. Release to stop."""
    try:
        import keyboard
    except ImportError:
        log("❌", "pip3 install keyboard", C.RED)
        return None

    frames = []
    recording = True

    log("🎙️", "Recording... (release SPACE to stop)", C.RED)
    tabbie("focus", "Listening...")

    def callback(indata, frame_count, time_info, status):
        if recording:
            frames.append(indata.copy())

    stream = sd.InputStream(
        samplerate=SAMPLE_RATE, channels=CHANNELS,
        dtype="int16", callback=callback, blocksize=1024,
    )

    with stream:
        keyboard.wait("space", suppress=True, trigger_on_release=True)

    recording = False

    if not frames:
        return None

    audio = np.concatenate(frames, axis=0)
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    with wave.open(tmp.name, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())

    return tmp.name

# ── Entry Points ────────────────────────────────────────────────────────────

def run_wake_word():
    detector = WakeWordDetector()
    if not detector.initialize():
        log("💡", "Falling back to push-to-talk", C.YELLOW)
        run_push_to_talk()
        return

    tts = EdgeTTSPlayer()

    wake_name = os.path.basename(WAKE_WORD_PATH).replace(".ppn", "") if WAKE_WORD_PATH else WAKE_WORD_BUILTIN
    log("✅", f'Listening for "{wake_name}". Ctrl+C to quit.\n', C.GREEN)
    tabbie("idle")

    try:
        while True:
            detected = detector.listen()
            if not detected:
                break

            log("👂", "Wake word!", C.MAGENTA)
            tabbie("startup")
            time.sleep(0.2)

            # Conversation turn — may loop if interrupted
            wants_more = True
            while wants_more:
                wants_more = conversation_turn(tts)

            print()
            log("👂", f'Listening for "{wake_name}"...\n', C.DIM)

    except KeyboardInterrupt:
        pass
    finally:
        detector.cleanup()
        tabbie("idle")
        log("👋", "Stopped.", C.DIM)


def run_push_to_talk():
    try:
        import keyboard
    except ImportError:
        log("❌", "pip3 install keyboard", C.RED)
        return

    tts = EdgeTTSPlayer()
    log("✅", "Hold SPACE to talk. ESC to quit.\n", C.GREEN)
    tabbie("idle")

    def on_press(event):
        if event.name != "space":
            return

        audio_path = record_push_to_talk()
        if not audio_path:
            return

        try:
            text = transcribe(audio_path)
        finally:
            try: os.unlink(audio_path)
            except: pass

        if not text:
            tabbie("idle")
            return

        log("🛰️", "Overseer...", C.YELLOW)
        tts.reset()
        monitor = InterruptMonitor(tts)

        for sentence in split_sentences(stream_haiku(text)):
            log("🗣️", sentence, C.GREEN)
            monitor.start()
            if not tts.speak_sentence(sentence):
                monitor.stop()
                break
            monitor.stop()

        tabbie("idle")
        print()
        log("✅", "Hold SPACE to talk.\n", C.GREEN)

    keyboard.on_press(on_press)

    try:
        keyboard.wait("esc")
    except KeyboardInterrupt:
        pass

    tabbie("idle")
    log("👋", "Stopped.", C.DIM)


# ── Dependency Check ────────────────────────────────────────────────────────

def check_deps(mode: str) -> bool:
    missing = []

    if not GROQ_API_KEY:
        missing.append("GROQ_API_KEY (free: console.groq.com)")
    if not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY (for Haiku streaming)")
    if mode == "wake-word" and not PICOVOICE_API_KEY:
        missing.append("PICOVOICE_API_KEY (free: console.picovoice.ai)")

    # Check edge-tts CLI
    try:
        subprocess.run(["edge-tts", "--version"], capture_output=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        missing.append("edge-tts not installed (pip3 install edge-tts)")

    if mode == "push-to-talk":
        try:
            import keyboard
        except ImportError:
            missing.append("pip3 install keyboard")

    if mode == "wake-word":
        try:
            import pvporcupine
        except ImportError:
            missing.append("pip3 install pvporcupine pvrecorder")

    if missing:
        log("❌", "Missing:", C.RED)
        for m in missing:
            print(f"   → {m}")
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="Overseer Voice Interface v2")
    parser.add_argument("--push-to-talk", action="store_true")
    parser.add_argument("--no-tabbie", action="store_true")
    args = parser.parse_args()

    global TABBIE_ENABLED
    if args.no_tabbie:
        TABBIE_ENABLED = False

    mode = "push-to-talk" if args.push_to_talk else "wake-word"

    print(f"""
{C.BOLD}🛰️  Overseer Voice Interface v2{C.RESET}
{C.DIM}Mode: {"Wake Word" if mode == "wake-word" else "Push-to-Talk"} | STT: Groq | LLM: Haiku (streaming) | TTS: Edge ({TTS_VOICE}){C.RESET}
{C.DIM}Tabbie: {"on" if TABBIE_ENABLED else "off"} | Interrupts: on{C.RESET}
""")

    if not check_deps(mode):
        print(f"\n{C.YELLOW}Quick fix:{C.RESET}")
        print("   pip3 install requests sounddevice numpy edge-tts pvporcupine pvrecorder")
        print("   export GROQ_API_KEY=... ANTHROPIC_API_KEY=... PICOVOICE_API_KEY=...")
        sys.exit(1)

    if mode == "wake-word":
        run_wake_word()
    else:
        run_push_to_talk()


if __name__ == "__main__":
    main()
