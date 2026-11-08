"""Голосовое → текст через Cloudflare Workers AI (Whisper large v3 turbo).

Использование:
    python scripts/transcribe.py <аудиофайл>      # печатает распознанный текст

Принимает то, что присылают мессенджеры: голосовые TG (ogg/opus), аудио MAX, mp3, m4a, wav.
Ключи CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN — как у gen_image.py (переменные окружения,
VPS — ~/.config/gorodn.env, запасной вариант — .env в корне проекта).
"""
import base64
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from gen_image import load_env  # noqa: E402

MODEL = "@cf/openai/whisper-large-v3-turbo"
# Подсказка Whisper: местные названия, которые иначе он пишет как слышит
HINT = ("Новости Сызрани. Сызрань, Сызранка, Кашпир, Монастырская гора, Засызранье, "
        "улица Советская, улица Ульяновская, проспект 50 лет Октября, Самарская область.")


def transcribe(path: Path) -> str:
    env = load_env(ROOT / ".env")
    account_id, token = env.get("CLOUDFLARE_ACCOUNT_ID"), env.get("CLOUDFLARE_API_TOKEN")
    if not account_id or not token:
        raise RuntimeError("не заданы CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN")
    body = json.dumps({"audio": base64.b64encode(Path(path).read_bytes()).decode(), "language": "ru",
                       "initial_prompt": HINT, "vad_filter": True}).encode()
    request = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{MODEL}", data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            data = json.load(response)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Cloudflare {e.code}: {e.read().decode('utf-8', 'replace')[:300]}") from None
    if not data.get("success"):
        raise RuntimeError(f"Cloudflare: {json.dumps(data.get('errors'), ensure_ascii=False)[:300]}")
    return (data["result"].get("text") or "").strip()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    print(transcribe(Path(sys.argv[1])))
