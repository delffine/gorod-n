"""Обложка по образцам через Cloudflare Workers AI (FLUX.2 [dev], до 4 образцов меньше 512×512).

Использование:
    python scripts/gen_cover.py <промт.txt> <выход.jpg> <образец0> [образец1 ...] [--width 1920 --height 768 --steps 25 --seed N]
В промте образцы называются image 0, image 1, ... в порядке перечисления.
"""
import argparse
import base64
import json
import subprocess
import sys

from gen_image import ROOT, load_env

MODEL = "@cf/black-forest-labs/flux-2-dev"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("prompt_file")
    parser.add_argument("output")
    parser.add_argument("refs", nargs="+")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=768)
    parser.add_argument("--steps", type=int, default=25)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()
    if len(args.refs) > 4:
        parser.error("не больше 4 образцов")

    env = load_env(ROOT / ".env")
    prompt = open(args.prompt_file, encoding="utf-8").read().strip()
    cmd = ["curl", "-s", "-X", "POST",
           f"https://api.cloudflare.com/client/v4/accounts/{env['CLOUDFLARE_ACCOUNT_ID']}/ai/run/{MODEL}",
           "-H", f"Authorization: Bearer {env['CLOUDFLARE_API_TOKEN']}",
           "--form-string", f"prompt={prompt}", "-F", f"width={args.width}", "-F", f"height={args.height}",
           "-F", f"steps={args.steps}"]
    if args.seed is not None:
        cmd += ["-F", f"seed={args.seed}"]
    for i, ref in enumerate(args.refs):
        cmd += ["-F", f"input_image_{i}=@{ref}"]
    result = subprocess.run(cmd, capture_output=True, timeout=300)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        sys.exit(f"Неожиданный ответ: {result.stdout[:500]!r} {result.stderr[:300]!r}")
    if not data.get("success") or "image" not in data.get("result", {}):
        sys.exit(f"Ошибка Cloudflare: {json.dumps(data.get('errors'), ensure_ascii=False)[:500]}")
    image = base64.b64decode(data["result"]["image"])
    open(args.output, "wb").write(image)
    print(f"Сохранено: {args.output} ({len(image) // 1024} КБ)")


if __name__ == "__main__":
    main()
