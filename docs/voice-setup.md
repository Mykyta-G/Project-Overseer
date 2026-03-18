# Voice Interface Setup

Talk to Overseer with your voice. No Telegram, no typing.

## How It Works

```
Hold SPACE → Mac mic records → Groq Whisper (free STT) → Overseer on Pi → macOS TTS speaks response
```

## Prerequisites

- macOS (for `say` TTS and mic access)
- Python 3.9+
- Groq API key (free: https://console.groq.com)
- SSH access to Pi via Tailscale (no password)
- Clawdbot gateway token

## Install

### 1. Get a Groq API Key

1. Go to [console.groq.com](https://console.groq.com)
2. Sign up (free)
3. Create an API key
4. Save it

### 2. Install Python Dependencies

```bash
cd Project-Overseer/scripts
pip3 install -r requirements.txt
```

> **Note:** The `keyboard` library needs sudo on macOS for global hotkey monitoring.

### 3. Set Up Environment

```bash
cp scripts/overseer-env.example ~/.overseer-env
nano ~/.overseer-env
# Fill in: GROQ_API_KEY, GATEWAY_TOKEN
```

### 4. Run

```bash
source ~/.overseer-env
sudo python3 scripts/voice-interface.py
```

> `sudo` is required for the `keyboard` library on macOS. Alternatively, grant Terminal/iTerm accessibility permissions in System Preferences → Privacy → Accessibility.

## Usage

| Action | What happens |
|--------|-------------|
| Hold SPACE | Start recording |
| Release SPACE | Stop recording → transcribe → send to Overseer → speak response |
| ESC | Quit |
| Ctrl+C | Quit |

## Configuration

### Change TTS Voice

List available macOS voices:
```bash
say -v ?
```

Set your preferred voice:
```bash
export TTS_VOICE="Daniel"  # British English
```

Good voices: Samantha (default), Daniel (British), Karen (Australian), Alex (American)

### Change Hotkey

Edit `voice-interface.py` and change:
```python
HOTKEY = "space"  # Change to any key
```

## Troubleshooting

### "Permission denied" on keyboard
macOS requires accessibility permissions for keyboard monitoring.
Fix: System Preferences → Privacy & Security → Accessibility → add Terminal/iTerm.

### SSH timeout
Make sure Tailscale is running on both Mac and Pi:
```bash
tailscale status
ssh raspberrypi "echo ok"
```

### No sound output
Check macOS volume. Test TTS:
```bash
say "Hello from Overseer"
```

## Roadmap

1. **v1 (now):** Hold-to-talk, macOS `say` TTS
2. **v2:** Push-to-talk menubar app (no terminal needed)
3. **v3:** Wake word "Overseer" (Picovoice Porcupine, always listening)
4. **v4:** Tabbie integration — voice through desk robot speaker
