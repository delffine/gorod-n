---
name: vk-no-photo-workarounds
description: All posting (TG/VK/MAX/Instagram) goes through Postmypost — MCP or REST (scripts/pmp_api.py); Postiz cancelled 2026-10-12; user forbids VK token/OAuth hacks (fear of account ban)
metadata:
  node_type: memory
  type: feedback
  modified: 2026-10-11T16:47:57.853Z
  originSessionId: b9a183f5-5049-4c83-9c69-07dd5a01f3e0
---

Since 2026-10-06 VK posts (with the Bender illustration) go through the Postmypost MCP: project 365896, account 2334893 = group "В городе Н сегодня произошло" (-242062669). Image is uploaded by URL (init_upload url → status_upload → file_id); upload test passed. Steps are in the city-n-news-to-soc skill, section 7. Since 2026-10-07 there is also a MAX channel in the same project: account 2335160 (chanel_id 27), published together with TG+VK. Since 2026-10-12 also Instagram city_n_news: account 2344463 (chanel_id 1) — own text without the source link (`post_json.py --instagram`), photo ratio 4:5…1.91:1 (`--ig-image`); per-account `details` with `account_id` work.

2026-10-11: the trial ended over the weekend (10–11.10), VPS fell back to Postiz (TG only). The user bought a month, but REST API answers "Ваш тариф не поддерживает API" and mcp.postmypost.io times out. Still not published to VK/MAX: hleb, nalichniki (TG done via Postiz), kormushki, dresskod, pandus (none anywhere). Same evening the user upgraded to a tariff with API; REST API works (helper `temp/pmp_api.py`: upload/init {project_id,url}, upload/status?id=, POST publications, GET publications/<id>; token: since 2026-10-15 env var PMP_TOKEN — Windows user var, VPS ~/.config/gorodn.env; .mcp.json uses ${PMP_TOKEN}), but the MCP server still timed out. hleb and pandus are now out everywhere; nalichniki goes to VK+MAX at 21:45 (pub 32712035). Still pending: kormushki, dresskod. On 2026-10-12 morning retry the MCP.

Before that, direct VK API was a dead end: group key can't upload photos (error 27), VK ID app has no wall/photos scopes, official client_ids are blocked. The user said "хватит" and fears their VK account getting blocked again.

**Why:** the user was blocked by VK before and doesn't want risky auth tricks.
**How to apply:** use Postmypost for VK. Never propose third-party client_ids, implicit-flow tricks or other VK token hacks. Public image URLs for Postmypost: nginx on the VPS, or catbox.moe (user-approved; `curl -A "Mozilla/5.0" -F reqtype=fileupload ...`; litterbox returns 403; files.catbox.moe may be unreachable from the user's network). Telegram caption with photo is limited to 1024 chars. Postiz was cancelled by the user on 2026-10-12 (trial not renewed) — forget it, there is no second publishing service. Related: [[vps-autopost]]
