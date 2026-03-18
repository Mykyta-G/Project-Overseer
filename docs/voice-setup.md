# Voice Interface Setup

Talk to Overseer with your voice. No Telegram, no typing.

## How It Works

```
"Jarvis" (or "Overseer") → Mac mic records → silence detected → 
Groq Whisper transcribes → Overseer on Pi responds → 
macOS TTS speaks → Tabbie shows face reactions
```

## Two Modes

| Mode | How | Best for |
|------|-----|----------|
| **Wake Word** (default) | Say "Jarvis" / "Overseer", then talk | Hands-free, always listening |
| **Push-to-Talk** | Hold SPACE, talk, release | Fallback, no wake word setup |

## Prerequisites

- macOS with mic
- Python 3.9+
- Free API keys:
  - **Groq** — STT (https://console.groq.com)
  - **Picovoice** — wake word (https://console.picovoice.ai)
- SSH to Pi via Tailscale (no password)
- Clawdbot gateway token

## Install

### 1. Get API Keys (all free)

| Service | URL | What for |
|---------|-----|----------|
| Groq | [console.groq.com](https://console.groq.com) | Speech-to-text (14,400 sec/day free) |
| Picovoice | [console.picovoice.ai](https://console.picovoice.ai) | Wake word detection |

### 2. Install Dependencies

```bash
cd Project-Overseer/scripts
pip3 install -r requirements.txt
```

### 3. Configure

```bash
cp scripts/overseer-env.example ~/.overseer-env
nano ~/.overseer-env
# Fill in: GROQ_API_KEY, PICOVOICE_API_KEY, GATEWAY_TOKEN
```

### 4. (Optional) Train Custom Wake Word

1. Go to [console.picovoice.ai](https://console.picovoice.ai)
2. Create a new Porcupine wake word
3. Type: "Overseer"
4. Download the `.ppn` file for macOS
5. Set `WAKE_WORD_PATH=/path/to/overseer_mac.ppn` in your env

Until then, "Jarvis" works as a built-in fallback.

### 5. Run

```bash
source ~/.overseer-env

# Wake word mode (default):
python3 scripts/voice-interface.py

# Push-to-talk fallback:
python3 scripts/voice-interface.py --push-to-talk

# Without Tabbie:
python3 scripts/voice-interface.py --no-tabbie
```

## Usage

### Wake Word Mode
| Action | What happens |
|--------|-------------|
| Say "Jarvis" / "Overseer" | Wake word detected → starts listening |
| Speak your message | Records until you stop talking (silence detection) |
| Wait | Groq transcribes → Overseer responds → Mac speaks → Tabbie reacts |

### Push-to-Talk Mode
| Action | What happens |
|--------|-------------|
| Hold SPACE | Start recording |
| Release SPACE | Transcribe → Overseer → speak response |
| ESC / Ctrl+C | Quit |

## Tabbie Integration

When Tabbie is connected on the same WiFi:
- **Idle** → default face (waiting)
- **Listening** → focus face (you're speaking)
- **Thinking** → focus face (processing)
- **Speaking** → love/happy face (Overseer responding)
- **Error** → angry face

Set `TABBIE_ENABLED=false` to disable.

## Configuration

### TTS Voice
```bash
say -v ?                    # List available voices
export TTS_VOICE="Daniel"   # British English
```

Good voices: Samantha (default), Daniel (British), Karen (Australian)

### Silence Detection
In `voice-interface.py`:
```python
SILENCE_THRESHOLD = 500   # Lower = more sensitive
SILENCE_DURATION = 1.5    # Seconds of silence before stopping
MAX_RECORD_SECONDS = 30   # Safety cap
```

## Troubleshooting

### Wake word not detecting
- Check mic permissions: System Preferences → Privacy → Microphone
- Try a quieter environment
- Lower sensitivity in Picovoice console when training custom word

### SSH timeout
```bash
tailscale status              # Both devices online?
ssh raspberrypi "echo ok"     # Works without password?
```

### No sound output
```bash
say "Hello from Overseer"     # Test macOS TTS directly
```
