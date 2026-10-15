---
name: vps-autopost
description: "Since 2026-10-07 autoposting runs on KZ VPS as user gorodn (cron 3×/day, ±30 min jitter); server copy of posts/ is the source of truth"
metadata:
  node_type: memory
  type: project
  originSessionId: b25ed986-7ffd-47d6-b851-17e7b40c1ffb
  modified: 2026-10-09T06:14:41.765Z
---

Autoposting "Город Н" runs on VPS 109.248.18.201 as user `gorodn` (no sudo; ssh `-i ~/.ssh/gorodn_deploy`). Project is in `/home/gorodn/gorod-n`, venv in `venv/`, Claude token in `~/.config/gorodn.env`. The cron job `auto/run.sh` starts at 7:30/13:30/19:30, sleeps randomly 0–60 min, so posts go out around 8/14/20 ±30 min. It waits for ai-editor's Claude (user deploy) because there is only one CPU. Logs: `temp/logs/auto_<date>.log`. Prompt: `auto/prompt.md`, rules in the skill's «Автономный режим» section. The user created the user `gorodn`; system changes need `delff` (sudo).

Was paused 2026-10-08 08:00–15:45 (Postmypost outage); restored by the user. If cron needs pausing again, comment the line with `# PAUSED <reason>: ` — changing crontab needs the user's explicit OK (auto mode blocks it).

Since 2026-10-09 a second cron line `*/5 * * * * auto/inbox_bot.sh` keeps the inbox bot (@city_n_addnews_bot) running (flock; exits if already up). Bot log: `temp/logs/inbox_bot.log`, drafts/publishing: `temp/logs/inbox_<date>.log`. Restarting the bot: don't `pkill -f` from a single ssh command line that contains the pattern — it kills the ssh shell itself. Kill by PID instead and let cron restart it (≤5 min); starting it by hand via `nohup … &` keeps the ssh session hanging. See [[user-news-bot]].

Since 2026-10-12: when the Postmypost MCP is down (it was 10/11–10/12: CONNECT_TIMEOUT, then 404 on mcp.postmypost.io/mcp while api.postmypost.io/v4.1 works with the same token), publish via `scripts/pmp_api.py` (publish/check/get); the skill and auto/prompt.md say so. Upload status 3 = processing, not error. Postiz is gone (cancelled 2026-10-12); on 10/11 its fallback caused duplicate TG posts (hleb, nalichniki).

**Why:** the user wants one news post every ~6 h in daytime with no review ("до первого косяка").

**How to apply:** the server `posts/` and `data/selected/` are the source of truth. Before making a post locally, pull state from the VPS so there are no duplicates. After changing the skill or prompts locally, copy them to the server. Related: [[vk-no-photo-workarounds]], [[no-edit-published-posts]].
