"""Пост в формате JSON: чтение, запись, сборка текста, учёт публикаций.

Каждый пост — файл posts/YYYYMMDD_HHMM-name.json, картинка рядом: posts/YYYYMMDD_HHMM-name.jpg.
Описание полей — в README.md, раздел «Формат поста».

Использование:
    python scripts/post_json.py <пост.json>              # текст поста, длина, статус публикаций
    python scripts/post_json.py <пост.json> --instagram  # текст для Instagram: без строки со ссылкой
    python scripts/post_json.py <пост.json> --ig-image   # картинка для Instagram (≠ основной, если пришлось обрезать)
    python scripts/post_json.py <пост.json> --rename HHMM
        # переименовать JSON и картинку под фактическое время публикации (дата из имени сохраняется)
    python scripts/post_json.py <пост.json> --record-postmypost PUBLICATION_ID --account vk|tg|max|ig --file-id FILE_ID
                                            [--url URL] [--at 2026-10-06T19:09:00+04:00] [--status published]
        # записать публикацию через Postmypost: vk — группа VK, tg — Telegram City_N_news, max — канал MAX,
        # ig — Instagram city_n_news
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path: Path, post: dict):
    Path(path).write_text(json.dumps(post, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def image_path(path: Path, post: dict) -> Path:
    """Картинка лежит рядом с JSON; по умолчанию — то же имя с расширением .jpg."""
    name = post.get("image", {}).get("file") or Path(path).with_suffix(".jpg").name
    return Path(path).with_name(name)


def short_url(url: str) -> str:
    """Длинную ссылку КТВ-ЛУЧ (/novost/<хвост>/<id>/) — в их короткую /n/<id>/ (сайт сам перенаправит)."""
    match = re.match(r"https?://ktv-ray\.ru/novost/.+/(\d+)/?$", url)
    return f"https://ktv-ray.ru/n/{match.group(1)}/" if match else url


SOURCE_VERBS = ["Узнал", "Рассказали", "Прочитал", "Увидел", "Говорят"]
SOURCE_PLACES = ["отсюда", "там", "тут", "здесь"]


def source_line(post: dict) -> str | None:
    """«Узнал здесь: <ссылка>», «Говорят там: <ссылка>»… Вариант зависит от id поста, поэтому
    при каждой сборке текста (проверка, публикация) у одного поста он один и тот же.
    У своей новости из бота (source.type = "user") ссылки нет — и строки нет."""
    if not post["source"].get("url"):
        return None
    n = int(hashlib.md5(post["id"].encode("utf-8")).hexdigest(), 16)
    verb = SOURCE_VERBS[n % len(SOURCE_VERBS)]
    place = SOURCE_PLACES[n // len(SOURCE_VERBS) % len(SOURCE_PLACES)]
    return f"{verb} {place}: {short_url(post['source']['url'])}"


def render_text(post: dict, instagram: bool = False) -> str:
    """Текст поста для соцсетей: заголовок, пересказ, источник, хэштеги.
    В Instagram ссылки в подписи не кликаются — строку с источником там не ставим."""
    parts = [post["title"], post["body"], None if instagram else source_line(post), " ".join(post.get("hashtags", []))]
    return "\n\n".join(p for p in parts if p)


IG_RATIO = (4 / 5, 1.91)  # Instagram принимает фото от 4:5 (вертикальное) до 1.91:1 (горизонтальное)


def ig_image(path: Path, post: dict) -> Path:
    """Картинка для Instagram: основная, если пропорции подходят, иначе обрезанная по центру копия <имя>_ig.jpg."""
    from PIL import Image

    src = image_path(path, post)
    im = Image.open(src)
    w, h = im.size
    if IG_RATIO[0] <= w / h <= IG_RATIO[1]:
        return src
    if w / h < IG_RATIO[0]:
        nh = round(w / IG_RATIO[0])
        box = (0, (h - nh) // 2, w, (h - nh) // 2 + nh)
    else:
        nw = round(h * IG_RATIO[1])
        box = ((w - nw) // 2, 0, (w - nw) // 2 + nw, h)
    dst = src.with_name(src.stem + "_ig.jpg")
    im.convert("RGB").crop(box).save(dst, quality=92)
    return dst


def add_publication(post: dict, platform: str, channel: str, status: str, at: str | None = None, **fields) -> dict:
    """Записывает результат публикации (status: published / scheduled / error).

    Запись с той же площадкой и тем же post_id (например, scheduled -> published) обновляется на месте:
    меняются статус и переданные поля, пустые (None) поля и время без --at остаются прежними.
    """
    publications = post.setdefault("publications", [])
    for record in publications:
        if record["platform"] == platform and fields.get("post_id") and record.get("post_id") == fields["post_id"]:
            record["status"] = status
            record.update({k: v for k, v in fields.items() if v is not None})
            if at:
                record["published_at"] = at
            return record
    record = {
        "platform": platform,
        "channel": channel,
        "status": status,
        "published_at": at or datetime.now().astimezone().isoformat(timespec="seconds"),
        **fields,
    }
    publications.append(record)
    return record


def is_published(post: dict, platform: str) -> bool:
    return any(p["platform"] == platform and p["status"] == "published" for p in post.get("publications", []))


VK_GOROD_N = {"platform": "vk", "channel": "В городе Н сегодня произошло", "project_id": 365896,
              "account_id": 2334893, "group_id": -242062669}
# тот же канал, что telegram/City_N в старых записях (публиковали через Postiz до 12.10)
TG_POSTMYPOST = {"platform": "telegram", "channel": "City_N_news", "project_id": 365896,
                 "account_id": 2334920, "chat_id": -1003957700884}
MAX_GOROD_N = {"platform": "max", "channel": "В городе Н сегодня произошло", "project_id": 365896,
               "account_id": 2335160, "chat_id": -79823903943329}
IG_GOROD_N = {"platform": "instagram", "channel": "city_n_news", "project_id": 365896, "account_id": 2344463}
POSTMYPOST_ACCOUNTS = {"vk": VK_GOROD_N, "tg": TG_POSTMYPOST, "max": MAX_GOROD_N, "ig": IG_GOROD_N}


def rename(path: Path, hhmm: str) -> Path:
    """20261006_2000-name.json -> 20261006_<hhmm>-name.json, вместе с картинкой."""
    post = load(path)
    date, rest = path.stem.split("_", 1)
    new_stem = f"{date}_{hhmm}-{rest.split('-', 1)[1]}"
    old_image = image_path(path, post)
    new_path = path.with_name(new_stem + ".json")
    if old_image.exists():
        new_image = path.with_name(new_stem + old_image.suffix)
        old_image.rename(new_image)
        post.setdefault("image", {})["file"] = new_image.name
    post["id"] = new_stem
    save(new_path, post)
    if new_path != path:
        path.unlink()
    return new_path


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("post")
    parser.add_argument("--instagram", action="store_true")
    parser.add_argument("--ig-image", action="store_true")
    parser.add_argument("--rename", metavar="HHMM")
    parser.add_argument("--record-postmypost", metavar="PUBLICATION_ID")
    parser.add_argument("--account", default="vk", choices=sorted(POSTMYPOST_ACCOUNTS), help="аккаунт Postmypost")
    parser.add_argument("--file-id", help="file_id картинки в Postmypost")
    parser.add_argument("--url", help="ссылка на пост (VK, Instagram)")
    parser.add_argument("--at", help="время публикации ISO, по умолчанию сейчас")
    parser.add_argument("--status", default="published", choices=["published", "scheduled", "error"])
    args = parser.parse_args()

    path = Path(args.post)
    if args.rename:
        print(f"Переименовано: {rename(path, args.rename)}")
        return
    post = load(path)
    if args.instagram:
        print(render_text(post, instagram=True))
        return
    if args.ig_image:
        print(ig_image(path, post))
        return
    if args.record_postmypost:
        account = POSTMYPOST_ACCOUNTS[args.account]
        record = add_publication(
            post, account["platform"], account["channel"], args.status, at=args.at, via="postmypost",
            project_id=account["project_id"], account_id=account["account_id"],
            post_id=args.record_postmypost, file_id=args.file_id, url=args.url,
        )
        record.setdefault("url", None)
        record.setdefault("file_id", None)
        record["error"] = None
        save(path, post)
        print(f"Записано: {account['platform']}/{account['channel']} {args.status}")
        return
    print(render_text(post))
    print(f"\n--- {len(render_text(post))} символов (Instagram {len(render_text(post, instagram=True))}); "
          f"картинка: {image_path(path, post).name}")
    for p in post.get("publications", []):
        print(f"{p['platform']}/{p['channel']}: {p['status']} {p.get('published_at', '')} {p.get('url', '')}")


if __name__ == "__main__":
    main()
