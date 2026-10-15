---
name: vintage-pencil-sketch
description: Turn a user's photo (town, buildings, landscape) into a rough pencil drawing in the style of old book illustrations, optionally tinted with a warm vintage watercolor palette, via Cloudflare Workers AI.
---

# Vintage pencil sketch from a photo

Two passes: (1) photo -> rough graphite sketch, (2) sketch -> light warm watercolor tint (sepia/ochre, faded brick red, grey-green roofs, dull gold). Uses image-to-image FLUX.2 models on Cloudflare Workers AI.

## 0. What to get from the user

- The photo (attachment). Ask what must stay recognizable (main buildings, reflection in water, etc.) and what to drop.
- Cloudflare keys: do NOT ask the user. They are environment variables `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` (Windows user variables; on the VPS `~/.config/gorodn.env`; fallback — `.env` at the project root), permanent project token, also used by `scripts/gen_image.py` and `scripts/gen_cover.py`. Never print the token or copy it into other files.
- Network: `api.cloudflare.com` must be reachable. If curl gets `CONNECT tunnel failed, 403`, ask the user to add `api.cloudflare.com` to allowed domains (Settings -> Capabilities) and retry.

Load keys and check the token (user token):
```bash
[ -z "${CLOUDFLARE_API_TOKEN:-}" ] && [ -f .env ] && { set -a; . ./.env; set +a; }; A=$CLOUDFLARE_ACCOUNT_ID; T=$CLOUDFLARE_API_TOKEN
curl -sS -H "Authorization: Bearer $T" "https://api.cloudflare.com/client/v4/user/tokens/verify"
```
The free daily Workers AI allocation is shared with the post illustrations (resets 04:00 local). If the answer says "daily free allocation", tell the user and stop; don't burn retries.

## 1. Prepare input

Resize the photo so the long side is 768 px (bigger inputs/outputs caused internal errors). Output size: keep the photo's aspect, multiples of 16, long side 1024 (e.g. 1024x768 for 4:3).
```python
from PIL import Image
im=Image.open(PHOTO).convert('RGB'); s=768/max(im.size)
im.resize((int(im.width*s),int(im.height*s)),Image.LANCZOS).save('in.png')
```

## 2. Models and API call

- `@cf/black-forest-labs/flux-2-dev` - best quality, but was intermittently down (error 3043 "Internal server error"). Try it first with one quick call.
- `@cf/black-forest-labs/flux-2-klein-9b` - reliable fallback, results were good. Do not send `steps` to klein.

FLUX.2 takes multipart/form-data: `prompt`, `input_image_0` (optional `input_image_1`...), `width`, `height`, `seed` (+ `steps` for dev). Response JSON `result.image` is base64 JPEG.
```bash
curl -sS -X POST -H "Authorization: Bearer $T" \
  -F "prompt=$P" -F "input_image_0=@in.png" -F "width=1024" -F "height=768" -F "seed=$SEED" \
  "https://api.cloudflare.com/client/v4/accounts/$A/ai/run/@cf/black-forest-labs/flux-2-klein-9b" -o r.json
python3 -c "import json,base64;d=json.load(open('r.json'));assert d['success'],d['errors'];open('out.png','wb').write(base64.b64decode(d['result']['image']))"
```
Run 3 seeds in parallel, stitch a contact sheet, look at it, show the user the best 2-3.

## 3. Pass 1 - rough pencil prompt

Adapt the bracketed part to the photo's landmarks (name each main building by shape and position):

```
Turn this photo into a rough graphite pencil drawing in the style of an old Russian book illustration from the early 20th century. Rough, bold, quick sketch with a soft thick 6B pencil: heavy expressive strokes, coarse zigzag hatching, smudged graphite, uneven pressure, on off-white textured paper, monochrome grey graphite only, minimum of detail, lots of empty paper. Keep the composition: [on the high riverbank a church with a golden onion dome and a tall bell tower on the left, a large two-storey merchant brick building in the center, and a white tent-roofed bell tower on the right, low houses between them; below, a calm river with the buildings clearly reflected in the water, drawn with horizontal pencil strokes]. Buildings must stay recognizable by their silhouettes. Omit power lines, poles, cars, fences, ducks and small clutter. Sky mostly blank paper with a few light strokes. No color, no text, no signature.
```
Neater version: replace the "Rough, bold..." sentence with "Loose confident hand-drawn pencil strokes and hatching on off-white paper".

## 4. Pass 2 - color tint

Input 0 = chosen sketch. Optional input 1 = palette reference image. Adapt colors to the scene:

```
Take the pencil drawing from the first image and add light, sparse watercolor tinting, using a warm vintage palette: yellowed cream paper, warm ochre and sepia sky wash fading to cream near the horizon, faded brick red for the big merchant building, grey-green roofs, dull gold for the onion dome, mint-grey bell tower, white tower left as paper, olive and ochre for the bushes on the riverbank, and the same muted colors softly repeated in the water reflection with a pale ochre-grey water. Keep every pencil line, the composition and the rough sketch character of the first image unchanged; color only lightly, transparent and a bit uneven, leaving much of the paper showing, like a tinted illustration in an old Soviet book. No text.
```
The model sometimes recolors white buildings - point it out and offer a fix. The user preferred this direct, bright output.

## 5. Optional post-processing

- Keep original pencil lines with paler color: median-blur(7)+Gaussian(2.5) the colored image, multiply by `clip(gray/percentile(gray,92),0,1)**1.15` of the sketch.
- Make an object white: soft elliptical mask; inside `paper_rgb*(0.25+0.75*clip((gray-55)/60,0,1))`.

## 6. Delivery

Save JPEG quality 95, send with one line per variant, offer tweaks (more/less color, remove clutter, upscale). Work files go to the scratchpad; final images next to the post they belong to.
