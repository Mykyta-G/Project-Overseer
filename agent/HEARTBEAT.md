# HEARTBEAT.md — Periodic Checks

## On each heartbeat:
1. Check `sessions_list` for any agent errors or completed tasks
2. If 🔴 Critical items found → message human immediately
3. If 🟡 Attention items found → note for next summary
4. Update `memory/heartbeat-state.json` with last check times

## Rotate through (2-4x daily):
- [ ] Agent status scan
- [ ] Weather check (morning only)

## Quiet hours: 23:00-08:00
- Only forward 🔴 Critical during quiet hours
- Everything else waits for morning brief
