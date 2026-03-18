#!/bin/bash
# Overseer Mac Login Trigger
# Triggers a login brief when you log into your Mac
# Connects to Pi via Tailscale SSH and fires the cron job

PI_HOST="raspberrypi"  # Tailscale hostname
JOB_ID="login-brief"

# Debounce: don't fire if already triggered in last 5 minutes
LOCK_FILE="/tmp/overseer-login-brief.lock"
if [ -f "$LOCK_FILE" ]; then
    LOCK_AGE=$(( $(date +%s) - $(stat -f %m "$LOCK_FILE" 2>/dev/null || echo 0) ))
    if [ "$LOCK_AGE" -lt 300 ]; then
        exit 0  # Already triggered recently
    fi
fi
touch "$LOCK_FILE"

# Trigger the login-brief cron job on the Pi
ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$PI_HOST" \
    "clawdbot cron run --name $JOB_ID" 2>/dev/null &

exit 0
