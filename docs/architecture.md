# Architecture

## Overview

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  You         │────▶│  Overseer        │────▶│  Agent Fleet     │
│  (Telegram)  │◀────│  (Haiku 4.5)     │◀────│                  │
└─────────────┘     └──────────────────┘     │  Wizard (Opus)   │
                           │                  │  Saul (Opus)     │
                     ┌─────┴──────┐          │  Killer (Sonnet) │
                     │ Clawdbot   │          │  Gunnar (Haiku)  │
                     │ Gateway    │          │  Forge (local)   │
                     └────────────┘          └─────────────────┘
                           │
                    ┌──────┴──────┐
                    │ Raspberry Pi │
                    │ (always-on)  │
                    └─────────────┘
```

## How It Works

### Clawdbot Gateway
Single process managing all agents. Routes Telegram messages to the right agent based on rules. Handles sessions, tools, memory, cron jobs.

### Overseer Agent
Runs on Haiku 4.5 — the cheapest Claude model. Its job is:
1. **Route** — send complex work to the right specialist agent
2. **Filter** — classify information by priority (🔴🟡🟢⚪)
3. **Summarize** — morning briefs, evening wraps, status checks
4. **Monitor** — heartbeat checks on agent health

Overseer never does heavy thinking. It coordinates.

### Agent Fleet
Each agent has:
- Its own Telegram bot (separate chat)
- Its own workspace and memory
- Its own model (matched to workload)
- Routing rules (who can talk to it)

### Model Fallback Chain
```
Request → Haiku 4.5 (primary, ~$0.001/call)
            ↓ (if fails)
          Gemini Flash (free, 1500/day)
            ↓ (if fails)  
          Forge/Qwen 3 (local, free, offline)
```

### Cost Model
| What | Model | Cost |
|------|-------|------|
| Routing, filtering, briefs | Haiku 4.5 | ~$0.10/day |
| Cloud fallback | Gemini Flash | Free |
| Local processing | Qwen 3 (Forge) | Free |
| Complex work | Sonnet/Opus | claude.ai subscription |

**Key insight:** Background automation uses API keys (pay-as-you-go). Your claude.ai subscription is only for direct conversations. They never compete.

### Network
```
Tailscale mesh:
  raspberrypi ←→ macbook-pro (direct LAN)
  raspberrypi ←→ gaming-pc (relay/direct)
  raspberrypi ←→ iphone (for location triggers)
```

All inter-device communication over Tailscale. No port forwarding. No public exposure.
