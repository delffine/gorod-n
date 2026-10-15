"""Получение ключа пользователя ВК через VK ID (OAuth 2.1 + PKCE).

Шаг 1:  python scripts/vk_auth.py url
        → печатает ссылку; открыть её в браузере, разрешить доступ.
        Браузер перейдёт на redirect URL (страница может не открыться — это нормально).
Шаг 2:  python scripts/vk_auth.py code "<полный адрес из адресной строки>"
        → обменивает код на ключи и сохраняет их в .env.

Дальше ключ обновляется автоматически (refresh_token) — см. get_user_token().
Нужно в .env: VK_CLIENT_ID, VK_REDIRECT_URI.
"""
import base64
import hashlib
import json
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_image import ROOT, load_env  # noqa: E402

ENV_FILE = ROOT / ".env"
STATE_FILE = ROOT / ".vk_auth_state.json"
AUTH_URL = "https://id.vk.com/authorize"
TOKEN_URL = "https://id.vk.com/oauth2/auth"
SCOPE = "wall photos groups"


def save_env(values: dict):
    """Обновляет/добавляет ключи в .env, не трогая остальные строки."""
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    rest = dict(values)
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and key in rest:
            lines[i] = f"{key}={rest.pop(key)}"
    lines += [f"{k}={v}" for k, v in rest.items()]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def post_token(params: dict) -> dict:
    data = urllib.parse.urlencode(params).encode("utf-8")
    try:
        with urllib.request.urlopen(TOKEN_URL, data=data, timeout=60) as resp:
            answer = json.load(resp)
    except urllib.error.HTTPError as e:
        answer = json.loads(e.read().decode("utf-8", "replace") or "{}")
    if "access_token" not in answer:
        sys.exit(f"VK ID не выдал ключ: {json.dumps(answer, ensure_ascii=False)}")
    return answer


def store_tokens(answer: dict, device_id: str):
    save_env({
        "VK_USER_TOKEN": answer["access_token"],
        "VK_REFRESH_TOKEN": answer["refresh_token"],
        "VK_DEVICE_ID": device_id,
        "VK_TOKEN_EXPIRES": str(int(time.time()) + int(answer.get("expires_in", 3600)) - 60),
    })


def make_url():
    env = load_env(ENV_FILE)
    client_id, redirect = env.get("VK_CLIENT_ID"), env.get("VK_REDIRECT_URI")
    if not client_id or not redirect:
        sys.exit("В .env не заполнены VK_CLIENT_ID / VK_REDIRECT_URI")
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    STATE_FILE.write_text(json.dumps({"verifier": verifier, "state": state}), encoding="utf-8")
    query = urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect,
        "scope": SCOPE, "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256",
    })
    print(f"{AUTH_URL}?{query}")


def exchange(redirected: str):
    env = load_env(ENV_FILE)
    saved = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(redirected).query))
    if "payload" in query:  # некоторые версии VK ID отдают всё в JSON-параметре payload
        query.update(json.loads(query["payload"]))
    if query.get("state") != saved["state"]:
        sys.exit("state не совпадает — запустите шаг 1 заново")
    answer = post_token({
        "grant_type": "authorization_code", "code": query["code"],
        "code_verifier": saved["verifier"], "client_id": env["VK_CLIENT_ID"],
        "device_id": query["device_id"], "redirect_uri": env["VK_REDIRECT_URI"],
        "state": saved["state"],
    })
    store_tokens(answer, query["device_id"])
    STATE_FILE.unlink()
    print(f"Готово: ключ пользователя сохранён в .env (права: {answer.get('scope', '?')})")


def get_user_token() -> str:
    """Возвращает действующий ключ пользователя, при необходимости обновляя его."""
    env = load_env(ENV_FILE)
    token = env.get("VK_USER_TOKEN")
    if not token or not env.get("VK_REFRESH_TOKEN"):
        sys.exit("Нет ключа пользователя ВК — выполните scripts/vk_auth.py url / code")
    if int(env.get("VK_TOKEN_EXPIRES") or 0) > time.time():
        return token
    answer = post_token({
        "grant_type": "refresh_token", "refresh_token": env["VK_REFRESH_TOKEN"],
        "client_id": env["VK_CLIENT_ID"], "device_id": env["VK_DEVICE_ID"],
        "state": secrets.token_urlsafe(24),
    })
    store_tokens(answer, env["VK_DEVICE_ID"])
    return answer["access_token"]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    if len(sys.argv) >= 2 and sys.argv[1] == "url":
        make_url()
    elif len(sys.argv) >= 3 and sys.argv[1] == "code":
        exchange(sys.argv[2])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
