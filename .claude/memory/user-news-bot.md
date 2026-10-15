---
name: user-news-bot
description: "Planned feature (2026-10-09) — user sends own news text+photo via bot (TG first, MAX later), Claude makes Ostap-style post, preview+approve"
metadata:
  node_type: memory
  type: project
  originSessionId: 756abef3-8f94-4f45-9712-04005cfd6869
  modified: 2026-10-09T05:50:38.682Z
---

Planned 2026-10-09: «своя новость» — the user sends text (+ optional photo) to a bot, Claude turns it into a post in Ostap's style.

Decisions by the user:
- Telegram bot first to debug the logic, MAX second. User is an ИП with a MAX partner profile verified via Gosuslugi, so a MAX bot is possible (MAX bots require org/ИП/самозанятый + moderation).
- Always send a preview with buttons; nothing is published without the user's «Опубликовать».
- Publish time per post: now / into the next cron slot (8/14/20) / a specific time (schedule via Postmypost).
- Images: if a photo is attached, use the photo itself; style word in the text picks the look: «сепия» (default, sepia_tone.py), «карандаш» / «акварель» (scripts/photo_sketch.py, from the vintage-pencil-sketch skill; user approved this look 2026-10-09); without a photo, FLUX from a prompt; the user may write their own image prompt in the message.

**Why:** the user wants to add their own city news, not only items scraped from sites; MAX preferred because it works more reliably on mobile outdoors.

**How to apply:** bot = long-polling script on the VPS ([[vps-autopost]]), whitelist only the user's account, token in ~/.config/gorodn.env, never in the project. Publishing goes through Postmypost ([[vk-no-photo-workarounds]]).

Status 2026-10-09: TG bot live (incl. photo styles). MAX bot «ГородН - редакция» enabled 16:13: API host is platform-api.max.ru (platform-api2 fails SSL on the VPS), user MAX id 303404961 whitelisted. Next: user tests MAX flow end to end.
