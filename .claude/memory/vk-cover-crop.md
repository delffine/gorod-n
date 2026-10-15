---
name: vk-cover-crop
description: "VK group cover is 1920x768; desktop view crops ~16% off the top, so keep the main figure low"
metadata:
  node_type: memory
  type: project
  originSessionId: b9a183f5-5049-4c83-9c69-07dd5a01f3e0
  modified: 2026-10-06T17:35:35.208Z
---

VK group cover for "В городе Н сегодня произошло" is 1920×768. The user showed (2026-10-06) that the desktop view crops roughly the top 16% (~125 px); the phone view shows the full height. Bender's cap had been cut off in a centered composition.

**Why:** the user pointed this out from VK's cover editor.
**How to apply:** in cover prompts keep the top fifth as empty sky and place Bender and the landmarks low; if a result still sits too high, shift it down by padding a sky band on top. Covers live in `cover/`, generated with `scripts/gen_cover.py` (FLUX.2 dev with up to 4 refs <512px). Related: [[vk-no-photo-workarounds]]

Final cover: `cover/-=bender_cover_syzran_final=-.jpg` (2026-10-12 all variants ver01/ver02 and Bender refs were deleted at the user's request). Earlier pick (2026-10-07, deleted): vk_cover_v4_s22_sky.jpg — FLUX.2 dev with refs, buildings recolored into the sky palette by `scripts/recolor_to_sky.py`. The user accepted that Bender's cap top (~25px) gets cropped on desktop. For later image edits, change one thing per pass by feeding the previous image as image 0 — new seeds break the layout.
