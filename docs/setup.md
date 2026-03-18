# Setup Guide

## Prerequisites

1. **Always-on Linux machine** (Raspberry Pi recommended)
2. **Node.js 18+**
3. **Clawdbot** installed globally: `npm install -g clawdbot`
4. **Telegram bot token** — talk to [@BotFather](https://t.me/BotFather)
5. **Anthropic API key** — [console.anthropic.com](https://console.anthropic.com)

## Step 1: Create the Agent

```bash
clawdbot agents add overseer
```

Follow the prompts:
- Workspace: `~/overseer-workspace`
- Model: `anthropic/claude-haiku-4-5` (cheap, fast — Overseer is a router, not a thinker)
- Add your Anthropic API key when prompted

## Step 2: Install Personality Files

```bash
# From Project-Overseer repo root
cp agent/SOUL.md ~/overseer-workspace/
cp agent/IDENTITY.md ~/overseer-workspace/
cp agent/AGENTS.md ~/overseer-workspace/
cp agent/TOOLS.md ~/overseer-workspace/
cp agent/HEARTBEAT.md ~/overseer-workspace/
cp agent/USER.md.example ~/overseer-workspace/USER.md
```

Edit `USER.md` with your actual details.

## Step 3: Configure Telegram

In your Clawdbot config, add the Overseer Telegram account and routing:

```yaml
channels:
  telegram:
    accounts:
      overseer:
        token: YOUR_BOT_TOKEN

agents:
  list:
    overseer:
      model: anthropic/claude-haiku-4-5
      workspace: ~/overseer-workspace
      routing:
        - channel: telegram
          accountId: overseer
          peer: "dm:YOUR_TELEGRAM_ID"
```

## Step 4: Add More Agents (Optional)

Overseer works best with a fleet. Add agents for different specialties:

```bash
clawdbot agents add wizard   # heavy lifting (Opus)
clawdbot agents add killer   # fast ops (Sonnet)
clawdbot agents add gunnar   # general (Haiku)
```

## Step 5: Start

```bash
clawdbot gateway start

# Or enable as a system service:
clawdbot gateway install
```

## Step 6: Test

Send "hey" to your Overseer bot on Telegram. If it responds, you're live.

Then try: "status" — it should report on your agent fleet.

## Step 7: Set Up Morning Brief (Optional)

Overseer can send you a daily briefing via cron. Configure in Clawdbot:

```yaml
agents:
  list:
    overseer:
      heartbeat:
        intervalMinutes: 60
```

Or use the `cron` tool to schedule specific briefs.

## Updating

Pull the latest agent files and re-copy:

```bash
cd Project-Overseer && git pull
cp agent/*.md ~/overseer-workspace/
```

Don't overwrite `USER.md` or `MEMORY.md` — those are yours.
