"""Генерация картинки через Cloudflare Workers AI (FLUX.1 schnell).

Использование:
    python scripts/gen_image.py <пост.json> [--steps 8] [--seed N]
        промт берётся из image.prompt, картинка сохраняется рядом с JSON
        (posts/YYYYMMDD_HHMM-name.jpg), в JSON записываются image.file, model, steps
    python scripts/gen_image.py <файл_с_промтом.txt> <выходной.jpg> [--steps 4] [--seed N]

Ключи CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN — из переменных окружения
(Windows — переменные пользователя, VPS — ~/.config/gorodn.env), запасной вариант — .env в корне проекта.
"""
import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL = "@cf/black-forest-labs/flux-1-schnell"


def load_env(path: Path) -> dict:
    """Ключи из файла (если есть), поверх — переменные окружения."""
    env = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip().strip('"').strip("'")
    env.update({k: v.strip() for k, v in os.environ.items() if v.strip()})
    return env


def generate(prompt: str, steps: int, seed: int | None) -> bytes:
    env = load_env(ROOT / ".env")
    account_id = env.get("CLOUDFLARE_ACCOUNT_ID")
    token = env.get("CLOUDFLARE_API_TOKEN")
    if not account_id or not token:
        sys.exit("Не заданы CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN (переменные окружения или .env)")

    body = {"prompt": prompt, "steps": steps}
    if seed is not None:  # FLUX schnell на Cloudflare отвечает 400 на seed; каждый запуск и так случайный
        print("--seed не поддерживается моделью и пропущен", file=sys.stderr)
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{MODEL}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        sys.exit(f"Ошибка Cloudflare {e.code}: {e.read().decode('utf-8', 'replace')[:500]}")

    if not data.get("success", True) or "image" not in data.get("result", {}):
        sys.exit(f"Неожиданный ответ: {json.dumps(data, ensure_ascii=False)[:500]}")
    return base64.b64decode(data["result"]["image"])


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt_file", help="пост .json или текстовый файл с промтом")
    parser.add_argument("output", nargs="?", help="только для .txt: куда сохранить картинку")
    parser.add_argument("--steps", type=int, default=None, help="1-8, больше — качественнее и дороже")
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()

    source = Path(args.prompt_file)
    if source.suffix == ".json":
        from post_json import image_path, load, save

        post = load(source)
        steps = args.steps or post.get("image", {}).get("steps") or 8
        image = generate(post["image"]["prompt"], steps, args.seed)
        out = image_path(source, post)
        out.write_bytes(image)
        post["image"].update(file=out.name, model=MODEL, steps=steps)
        post["image"].pop("url", None)  # старая ссылка указывает на прежнюю картинку
        save(source, post)
        print(f"Сохранено: {out} ({len(image) // 1024} КБ), JSON обновлён")
        return

    if not args.output:
        parser.error("для текстового промта нужен путь к картинке")
    prompt = source.read_text(encoding="utf-8").strip()
    image = generate(prompt, args.steps or 4, args.seed)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(image)
    print(f"Сохранено: {out} ({len(image) // 1024} КБ)")


if __name__ == "__main__":
    main()
