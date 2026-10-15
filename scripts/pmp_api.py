"""Публикация через REST API Postmypost — запасной путь, когда MCP Postmypost не подключается.

Тот же проект, аккаунты и поля, что у MCP (см. скилл, раздел 7). Токен — из переменной окружения PMP_TOKEN
(на VPS — ~/.config/gorodn.env, на Windows — переменная пользователя) или из PMP_TOKEN в .env.

Использование:
    python scripts/pmp_api.py publish posts/<пост>.json [--accounts tg,vk,max,ig] [--at 2026-10-12T11:00:00+04:00]
                                      [--image-url URL]
        # загрузить картинку, создать публикацию (по умолчанию через 2 мин) и записать её в JSON как scheduled.
        # Сети, где пост уже вышел или уже запланирован, пропускаются.
    python scripts/pmp_api.py check posts/<пост>.json
        # обновить записи scheduled по данным Postmypost (вышло — published со ссылками)
    python scripts/pmp_api.py get <id публикации>
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from post_json import POSTMYPOST_ACCOUNTS, add_publication, ig_image, image_path, load, render_text, save  # noqa: E402

API = "https://api.postmypost.io/v4.1"
PROJECT_ID = 365896
ROOT = Path(__file__).resolve().parent.parent
LOCAL_TZ = timezone(timedelta(hours=4))
# свой nginx на VPS (скилл, раздел 7, шаг 1)
NGINX_DIR = Path("/var/www/gorod-n/img")
NGINX_URL = "http://109.248.18.201:8808/gorod-n/img/"
ORDER = ["tg", "vk", "max", "ig"]
TG_CHANNEL = "City_N_news"


def token() -> str:
    if os.environ.get("PMP_TOKEN"):
        return os.environ["PMP_TOKEN"]
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, _, value = line.strip().partition("=")
            if key.strip() == "PMP_TOKEN" and value.strip():
                return value.strip().strip('"').strip("'")
    sys.exit("Нет токена Postmypost: задайте переменную окружения PMP_TOKEN (или PMP_TOKEN в .env)")


def call(method: str, path: str, body: dict | None = None, **params) -> dict:
    url = API + path
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token()}", "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"Postmypost {method} {path}: HTTP {e.code} {e.read().decode('utf-8', 'replace')[:500]}")
    return json.loads(raw) if raw else {}


def public_url(img: Path) -> str:
    """Публичная ссылка на картинку: nginx на VPS, иначе catbox."""
    if NGINX_DIR.is_dir():
        shutil.copy(img, NGINX_DIR / img.name)
        return NGINX_URL + img.name
    out = subprocess.run(["curl", "-s", "-A", "Mozilla/5.0", "-F", "reqtype=fileupload",
                          "-F", f"fileToUpload=@{img}", "https://catbox.moe/user/api.php"],
                         capture_output=True, text=True, timeout=120).stdout.strip()
    if not out.startswith("https://"):
        sys.exit(f"catbox не принял картинку: {out[:200]}")
    return out


def upload(url: str) -> int:
    """init_upload + status_upload -> file_id."""
    up = call("POST", "/upload/init", {"project_id": PROJECT_ID, "url": url})
    for _ in range(40):
        st = call("GET", "/upload/status", id=up["id"])
        if st.get("status") == 1 and st.get("file_id"):
            return st["file_id"]
        if st.get("status") not in (None, 0, 3, 5):  # 5 — принято, 3 — обрабатывается
            sys.exit(f"Загрузка {url} не удалась: {st}")
        time.sleep(3)
    sys.exit(f"Загрузка {url} не завершилась за 2 мин: {up}")


def taken(post: dict, key: str) -> str | None:
    """Вышел или запланирован ли пост в этой сети (Telegram — по любому из путей)."""
    platform = POSTMYPOST_ACCOUNTS[key]["platform"]
    for p in post.get("publications", []):
        if p["platform"] == platform and p["status"] in ("published", "scheduled"):
            return p["status"]
    return None


def publish(path: Path, accounts: list[str], at: str | None, image_url: str | None):
    post = load(path)
    todo = []
    for key in accounts:
        state = taken(post, key)
        if state:
            print(f"{key}: пропуск — уже {state}")
        else:
            todo.append(key)
    if not todo:
        print("Публиковать некуда.")
        return

    img = image_path(path, post)
    url = image_url or public_url(img)
    post.setdefault("image", {})["url"] = url
    file_id = upload(url)
    ig_file_id = file_id
    if "ig" in todo:
        ig = ig_image(path, post)
        if ig != img:
            ig_file_id = upload(public_url(ig))

    post_at = datetime.fromisoformat(at) if at else datetime.now(LOCAL_TZ) + timedelta(minutes=2)
    post_at = post_at.astimezone(LOCAL_TZ).replace(microsecond=0)
    details = []
    for key in todo:
        details.append({
            "account_id": POSTMYPOST_ACCOUNTS[key]["account_id"], "publication_type": 1,
            "content": render_text(post, instagram=(key == "ig")),
            "file_ids": [ig_file_id if key == "ig" else file_id],
        })
    pub = call("POST", "/publications", {
        "project_id": PROJECT_ID, "account_ids": [d["account_id"] for d in details],
        "publication_status": 5, "post_at": post_at.isoformat(), "details": details,
    })
    if not pub.get("id"):
        sys.exit(f"Postmypost не вернул id публикации: {pub}")
    for key in todo:
        acc = POSTMYPOST_ACCOUNTS[key]
        rec = add_publication(post, acc["platform"], acc["channel"], "scheduled", at=post_at.isoformat(),
                              via="postmypost", project_id=PROJECT_ID, account_id=acc["account_id"],
                              post_id=str(pub["id"]), file_id=str(ig_file_id if key == "ig" else file_id), url=None)
        rec["error"] = None
    save(path, post)
    print(f"Публикация {pub['id']} на {post_at.isoformat()}: {', '.join(todo)} — записано как scheduled")


def check(path: Path):
    post = load(path)
    ids = {p["post_id"] for p in post.get("publications", [])
           if p.get("via") == "postmypost" and p["status"] == "scheduled"}
    if not ids:
        print("Запланированных публикаций Postmypost нет.")
        return
    for pid in sorted(ids):
        pub = call("GET", f"/publications/{pid}")
        by_acc = {p.get("account_id"): p for p in pub.get("posts", [])}
        for rec in post["publications"]:
            if rec.get("post_id") != pid or rec["status"] != "scheduled":
                continue
            p = by_acc.get(rec["account_id"], {})
            if p.get("post_status") == 1:
                rec["status"] = "published"
                url = p.get("url")
                if rec["platform"] == "telegram" and p.get("external_id") and (not url or url.endswith("//")):
                    url = f"https://t.me/{TG_CHANNEL}/{p['external_id']}"  # Postmypost отдаёт https://t.me//
                rec["url"] = url or rec.get("url")
            elif pub.get("publication_status") == 3:
                rec["status"] = "error"
                rec["error"] = f"Postmypost: publication_status 3, post_status {p.get('post_status')}"
            print(f"{pid} {rec['platform']}: {rec['status']} {rec.get('url') or ''}")
    save(path, post)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("publish")
    p.add_argument("post")
    p.add_argument("--accounts", default=",".join(ORDER), help="tg,vk,max,ig")
    p.add_argument("--at", help="время публикации ISO с поясом; по умолчанию сейчас + 2 мин")
    p.add_argument("--image-url", help="готовая публичная ссылка на картинку")
    c = sub.add_parser("check")
    c.add_argument("post")
    g = sub.add_parser("get")
    g.add_argument("id")
    args = parser.parse_args()

    if args.cmd == "publish":
        accounts = [a.strip() for a in args.accounts.split(",") if a.strip()]
        bad = [a for a in accounts if a not in POSTMYPOST_ACCOUNTS]
        if bad:
            sys.exit(f"Неизвестные аккаунты: {bad}")
        publish(Path(args.post), accounts, args.at, args.image_url)
    elif args.cmd == "check":
        check(Path(args.post))
    else:
        print(json.dumps(call("GET", f"/publications/{args.id}"), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
