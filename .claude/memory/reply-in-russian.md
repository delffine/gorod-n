---
name: reply-in-russian
description: "Always reply to the user in Russian, including summaries and explanations"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 8bb1ed3f-a20b-44fa-9b1f-d1a0d761d1aa
  modified: 2026-10-07T15:52:40.149Z
---

Always reply to the user in Russian (text, summaries, questions).

**Why:** on 2026-10-07 the user noticed answers in English and asked to fix it — they are used to Russian.

**How to apply:** write all user-facing text in Russian; code, prompts for image models and identifiers may stay in English. The global setting `"language": "russian"` in `~/.claude/settings.json` was also added.
