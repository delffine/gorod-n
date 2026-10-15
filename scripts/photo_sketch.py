"""Фото пользователя → рисунок под старую книжную иллюстрацию (Cloudflare Workers AI, FLUX.2 klein).

Использование:
    python scripts/photo_sketch.py <фото> <выходной.jpg> --style pencil|watercolor
        [--scene "<композиция по-английски>"] [--colors "<палитра по-английски>"]
        [--omit "<что убрать>"] [--seed N]

pencil     — грубый графитный набросок (один запрос);
watercolor — тот же набросок, потом лёгкая тёплая акварель поверх (два запроса).
--scene    — что на фото и где, по силуэтам: «on the high riverbank a church with a golden
             onion dome on the left, ...». Без неё модель просто держит композицию фото.
Сепия — не здесь, это scripts/sepia_tone.py.

Ключи берутся из .env в корне проекта: CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN.
Подробности и подбор промтов — скилл vintage-pencil-sketch.
"""
import argparse
import base64
import io
import json
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
MODEL = "@cf/black-forest-labs/flux-2-klein-9b"  # flux-2-dev лучше, но часто падает с 3043

DEFAULT_SCENE = ("the main buildings, trees, people and objects of the photo in their places, "
                 "with any water reflections drawn with horizontal pencil strokes")
DEFAULT_OMIT = "power lines, poles, wires, road signs and small clutter"
DEFAULT_COLORS = ("warm ochre and sepia sky wash fading to cream near the horizon, faded brick red "
                  "for brick buildings, grey-green roofs, dull gold for golden domes, white buildings "
                  "left as white paper, olive and ochre for trees and bushes, and the same muted colors "
                  "softly repeated in any water reflections")

PENCIL = ("Turn this photo into a rough graphite pencil drawing in the style of an old Russian book "
          "illustration from the early 20th century. Rough, bold, quick sketch with a soft thick 6B "
          "pencil: heavy expressive strokes, coarse zigzag hatching, smudged graphite, uneven pressure, "
          "on off-white textured paper, monochrome grey graphite only, minimum of detail, lots of empty "
          "paper. Keep the composition: {scene}. Buildings must stay recognizable by their silhouettes. "
          "Omit {omit}. Sky mostly blank paper with a few light strokes. No color, no text, no signature.")

TINT = ("Take the pencil drawing from the first image and add light, sparse watercolor tinting, using a "
        "warm vintage palette: yellowed cream paper, {colors}. Keep every pencil line, the composition "
        "and the rough sketch character of the first image unchanged; color only lightly, transparent "
        "and a bit uneven, leaving much of the paper showing, like a tinted illustration in an old "
        "Soviet book. No text.")


def load_env(path: Path) -> dict:
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return buf.getvalue()


def run(prompt: str, image: bytes, size: tuple[int, int], seed: int) -> Image.Image:
    env = load_env(ROOT / ".env")
    account_id, token = env.get("CLOUDFLARE_ACCOUNT_ID"), env.get("CLOUDFLARE_API_TOKEN")
    if not account_id or not token:
        sys.exit("В .env не заполнены CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN")

    boundary = uuid.uuid4().hex
    fields = {"prompt": prompt, "width": size[0], "height": size[1], "seed": seed}
    body = b"".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                    for k, v in fields.items())
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="input_image_0"; filename="in.png"\r\n'
             f"Content-Type: image/png\r\n\r\n").encode() + image + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{MODEL}", data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        sys.exit(f"Ошибка Cloudflare {e.code}: {e.read().decode('utf-8', 'replace')[:500]}")
    if not data.get("success") or "image" not in (data.get("result") or {}):
        sys.exit(f"Ошибка Cloudflare: {json.dumps(data.get('errors'), ensure_ascii=False)[:500]}")
    return Image.open(io.BytesIO(base64.b64decode(data["result"]["image"]))).convert("RGB")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("photo")
    parser.add_argument("output")
    parser.add_argument("--style", choices=["pencil", "watercolor"], required=True)
    parser.add_argument("--scene", default=DEFAULT_SCENE)
    parser.add_argument("--colors", default=DEFAULT_COLORS)
    parser.add_argument("--omit", default=DEFAULT_OMIT)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    photo = Image.open(args.photo).convert("RGB")
    # вход — 768 по длинной стороне (крупнее — внутренние ошибки), выход — 1024, кратно 16
    scale = 768 / max(photo.size)
    photo = photo.resize((round(photo.width * scale), round(photo.height * scale)), Image.LANCZOS)
    scale = 1024 / max(photo.size)
    size = (round(photo.width * scale / 16) * 16, round(photo.height * scale / 16) * 16)

    result = run(PENCIL.format(scene=args.scene, omit=args.omit), png_bytes(photo), size, args.seed)
    if args.style == "watercolor":
        result = run(TINT.format(colors=args.colors), png_bytes(result), size, args.seed)
    result.save(args.output, "JPEG", quality=95)
    print(f"{args.output}: {args.style}, {size[0]}x{size[1]}, seed {args.seed}")


if __name__ == "__main__":
    main()
