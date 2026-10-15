---
name: factcheck-agent
description: Since 2026-10-08 every post passes subagent gorodn-factcheck before publishing; 3-agent pipeline archived to backup/pipeline-3agents_2026-10-08.zip
metadata:
  type: project
---

On 2026-10-08 the user agreed that the 3-subagent pipeline (editor/artist/SMM, skill `city-n-pipeline`) was overkill for a linear one-post-per-run flow. It is archived in `backup/pipeline-3agents_2026-10-08.zip` (agents, skill, PIPELINE.md, scripts/pipeline.py, old rollback script and pre-pipeline zip) and removed from the project. Main path is the single skill `city-n-news-to-soc`.

Kept from the idea: one read-only subagent `.claude/agents/gorodn-factcheck.md` (model sonnet), run in step 5 before every publication, also in cron (`auto/run.sh` got `Agent` in --tools/--allowedTools). Verdicts OK / ПРАВИТЬ / СТОП.

**Why:** a fresh-context reviewer catches invented facts the author misses; separate producer agents only added cost and failure points.

**How to apply:** don't revive the 3-agent pipeline unless the user asks; restore it from the zip if they do. Related: [[vps-autopost]].
