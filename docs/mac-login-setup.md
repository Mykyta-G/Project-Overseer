# Mac Login Brief Setup

Overseer greets you when you log into your Mac — agent status, weather, anything needing attention.

## How It Works

```
Mac login → launchd fires script → SSH to Pi → triggers Overseer cron job → Telegram brief
```

## Prerequisites

- Tailscale running on both Mac and Pi
- SSH key auth set up (Mac → Pi, no password prompt)
- Overseer `login-brief` cron job created

## Install

### 1. Copy the trigger script

```bash
sudo cp scripts/mac-login-trigger.sh /usr/local/bin/overseer-login-trigger.sh
sudo chmod +x /usr/local/bin/overseer-login-trigger.sh
```

### 2. Edit the script (if needed)

```bash
nano /usr/local/bin/overseer-login-trigger.sh
# Change PI_HOST if your Pi has a different Tailscale hostname
```

### 3. Install the LaunchAgent

```bash
cp scripts/com.overseer.login-brief.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.overseer.login-brief.plist
```

### 4. Test

```bash
# Manual test:
bash /usr/local/bin/overseer-login-trigger.sh

# Check logs:
cat /tmp/overseer-login.log
```

### 5. Verify SSH works without password

```bash
ssh raspberrypi "echo ok"
# Should print "ok" with no password prompt
# If not: ssh-copy-id raspberrypi
```

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.overseer.login-brief.plist
rm ~/Library/LaunchAgents/com.overseer.login-brief.plist
rm /usr/local/bin/overseer-login-trigger.sh
```

## Future: Tabbie Integration

When Tabbie is connected, the login trigger will also:
- Wake Tabbie's screen
- Show Overseer's face animation
- Speak the brief via Tabbie's speaker (after expansion PCB)
