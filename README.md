# 🛰️ Project Overseer

> Personal AI chief of staff — five specialized agents, one command center, zero noise.

Overseer is a personal AI infrastructure built on [Clawdbot](https://github.com/clawdbot/clawdbot) + Claude. It coordinates a fleet of specialized agents from a Raspberry Pi, filters signal from noise, and keeps you informed without being annoying.

## What It Does

- **One inbox** — routes messages from 5+ agents through a single Telegram bot
- **Priority filter** — classifies everything as 🔴 Critical / 🟡 Attention / ⚪ Info
- **Morning brief** — daily summary of agent activity, calendar, weather
- **Evening wrap** — what got done, what's open, what's tomorrow
- **Agent queries** — ask "status" and get a crew briefing
- **Go-home nudge** — knows when you've been working too long, checks your bus schedule
- **Cost: ~$2-5/month** — Haiku for routing, local models for grunt work

## Architecture

```
You (Telegram) → Overseer (Haiku) → Agent Fleet
                                      ├── Wizard (Opus) — heavy lifting
                                      ├── Saul (Opus) — legal/research
                                      ├── Killer (Sonnet) — fast ops
                                      ├── Gunnar (Haiku) — general
                                      └── Forge (Qwen local) — offline/free
```

Overseer runs on a Raspberry Pi via Clawdbot. All agents share one gateway. Tailscale connects everything.

## Fallback Chain

```
Haiku → Gemini Flash (free) → Forge/Qwen 3 (local)
```

Background automation never touches your claude.ai subscription.

## Setup

### Prerequisites

- Raspberry Pi (or any always-on Linux box)
- [Clawdbot](https://github.com/clawdbot/clawdbot) installed
- Telegram bot token (via @BotFather)
- Anthropic API key (pay-as-you-go)

### Quick Start

```bash
# 1. Install Clawdbot
npm install -g clawdbot

# 2. Create the Overseer agent
clawdbot agents add overseer

# 3. Copy agent personality files
cp agent/SOUL.md ~/overseer-workspace/SOUL.md
cp agent/IDENTITY.md ~/overseer-workspace/IDENTITY.md
cp agent/AGENTS.md ~/overseer-workspace/AGENTS.md
cp agent/TOOLS.md ~/overseer-workspace/TOOLS.md
cp agent/HEARTBEAT.md ~/overseer-workspace/HEARTBEAT.md
cp agent/USER.md.example ~/overseer-workspace/USER.md

# 4. Edit USER.md with your details
nano ~/overseer-workspace/USER.md

# 5. Set up auth
clawdbot agents add overseer  # follow prompts for API key

# 6. Configure Telegram routing
# Add your bot token and routing rules to clawdbot config

# 7. Start
clawdbot gateway start
```

See [docs/setup.md](docs/setup.md) for the full guide.

## Roadmap

| Phase | What | When |
|-------|------|------|
| 1. Foundation | Bot + status queries + priority filter | ✅ Now |
| 2. Daily Intel | Morning brief, evening summary, email/Discord triage | Week 1 |
| 3. Location | iPhone triggers, Skånetrafiken go-home nudges | Week 2 |
| 4. Knowledge | Notion integration, WhatsApp standup summaries | Week 2-3 |
| 5. Local AI | Route routine tasks to Forge (zero cost) | Week 3 |
| 6. Physical | Tabbie desk robot, wake word, voice profiles | When ready |
| 7. Vision | Screen awareness, live build narration | Month 2-3 |

See [docs/roadmap.md](docs/roadmap.md) for the full 21-step plan.

## Cost

| Layer | Model | Cost |
|-------|-------|------|
| Routing & briefs | Haiku 4.5 | ~$0.10/day |
| Fallback | Gemini Flash | Free (1500/day) |
| Local tasks | Forge/Qwen 3 | Free |
| Heavy work | Sonnet/Opus | Your claude.ai sub |

Realistic total: **$2-5/month** for full automation.

## Philosophy

- **Signal over noise** — if it's not worth your attention, you never see it
- **Build one thing at a time** — get it solid, then add the next
- **Cheap by default** — Haiku for everything, Opus only when it matters
- **Open source** — your AI, your rules, your data

## License

MIT — do whatever you want with it.

---

*Built on a Raspberry Pi somewhere in Sweden.* 🦞
