"""Новости Сызрани из двух RSS: «маленькая Сызрань» (syzran-small.ru, приоритетный; статьи /pages-… отбрасываются) и КТВ-ЛУЧ.

Использование:
    python scripts/fetch_news.py                 # скачать обе ленты в data/raw/ и вывести общий список
    python scripts/fetch_news.py --list          # список из уже скачанных сегодняшних лент
    python scripts/fetch_news.py --show 195258   # полный текст новости по ID (любого источника)
    python scripts/fetch_news.py --feed data/raw/2026-10-06_feed.rss --show 195258

Список: «МС» — маленькая Сызрань (ID ~104xxx), «КТВ» — КТВ-ЛУЧ (ID ~195xxx). Время местное (UTC+4).
"""
import argparse
import html
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_image import ROOT  # noqa: E402
from post_json import short_url  # noqa: E402

FEED_URL = "https://ktv-ray.ru/feed.rss"
SMALL_URL = "https://www.syzran-small.ru"
SMALL_FEED_URL = f"{SMALL_URL}/rss-ya.php"
LOCAL_TZ = timezone(timedelta(hours=4))
SMALL_NAME = "маленькая Сызрань"
KTV_NAME = "КТВ-ЛУЧ"


def raw_path(suffix: str) -> Path:
    return ROOT / "data" / "raw" / f"{date.today().isoformat()}_{suffix}"


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def save(path: Path, data: bytes, label: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    print(f"{label}: {path}")


def local_time(pub: str) -> str:
    return parsedate_to_datetime(pub).astimezone(LOCAL_TZ).strftime("%d.%m %H:%M") if pub else ""


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


# --- КТВ-ЛУЧ (RSS) ---

def ktv_items(path: Path) -> list[dict]:
    result = []
    for it in ET.parse(path).getroot().iter("item"):
        link = it.findtext("link") or ""
        match = re.search(r"/(\d+)/?$", link)
        full = next((ch.text or "" for ch in it if ch.tag.endswith("full-text")), "")
        enclosure = it.find("enclosure")
        pub = it.findtext("pubDate") or ""
        result.append({
            "source": KTV_NAME, "tag": "КТВ",
            "id": int(match.group(1)) if match else None,
            "title": (it.findtext("title") or "").strip(),
            "url": short_url(link),
            "when": local_time(pub),
            "date": pub,
            "text": clean(full),
            "image": enclosure.get("url") if enclosure is not None else None,
        })
    return result


# --- маленькая Сызрань (RSS для Яндекса, windows-1251, пространство имён по умолчанию) ---

def small_items(path: Path) -> list[dict]:
    ns = "{https://backend.userland.com/rss2}"
    result = []
    for it in ET.parse(path).getroot().iter(f"{ns}item"):
        link = it.findtext(f"{ns}link") or ""
        match = re.search(r"/news-(\d+)$", link)
        if not match:  # статьи (/pages-…) не берём
            continue
        full = next((ch.text or "" for ch in it if ch.tag.endswith("full-text")), "")
        enclosure = it.find(f"{ns}enclosure")
        pub = it.findtext(f"{ns}pubDate") or ""
        result.append({
            "source": SMALL_NAME, "tag": "МС",
            "id": int(match.group(1)),
            "title": (it.findtext(f"{ns}title") or "").strip(),
            "url": link,
            "when": local_time(pub),
            "date": pub,
            "text": clean(full),
            "image": enclosure.get("url") if enclosure is not None else None,
        })
    return result


def small_article(news_id: int) -> dict:
    url = f"{SMALL_URL}/news-{news_id}"
    page = get(url).decode("cp1251", errors="replace")
    title = re.search(r'<div class="newstitle"><h1>(.*?)</h1>', page, re.S)
    published = re.search(r'itemprop="datePublished" content="([^"]+)"', page)
    image = re.search(r'<div class="newsfoto"><img src="([^"]+)"', page)
    body = re.search(r'<div class="newsfoto">.*?</div>(.*?)<div class="newssource">', page, re.S)
    text = body.group(1) if body else ""
    text = re.sub(r'<div class="partnews.*?закрыть X</div>\s*</div>', " ", text, flags=re.S)
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.S)
    return {
        "title": clean(title.group(1)) if title else "",
        "url": url,
        "date": published.group(1) if published else "",
        "image": SMALL_URL + image.group(1) if image else None,
        "text": clean(text),
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--feed", type=Path, help="файл RSS КТВ-ЛУЧ (по умолчанию сегодняшний)")
    parser.add_argument("--small", type=Path, help="файл RSS «маленькой Сызрани» (по умолчанию сегодняшний)")
    parser.add_argument("--list", action="store_true", help="не скачивать, только список")
    parser.add_argument("--show", type=int, metavar="ID", help="полный текст новости")
    args = parser.parse_args()

    feed = args.feed or raw_path("feed.rss")
    small = args.small or raw_path("small.rss")
    if not args.feed and not args.small and not args.list and not args.show:
        save(feed, get(FEED_URL), f"Лента {KTV_NAME}")
        save(small, get(SMALL_FEED_URL), f"Лента «{SMALL_NAME}»")

    news = (small_items(small) if small.exists() else []) + (ktv_items(feed) if feed.exists() else [])
    if args.show:
        item = next((n for n in news if n["id"] == args.show), None)
        if item:
            print(f"[{item['source']}] {item['title']}\n{item['url']}\n{item['date']}\nКартинка: {item['image']}\n\n{item['text']}")
            return
        # нет в лентах — старая новость «маленькой Сызрани»: качаем её страницу
        art = small_article(args.show)
        if not art["title"]:
            sys.exit(f"Новости {args.show} нет ни в лентах, ни на {SMALL_URL}")
        print(f"[{SMALL_NAME}] {art['title']}\n{art['url']}\n{art['date']}\nКартинка: {art['image']}\n\n{art['text']}")
        return
    if not news:
        sys.exit("Нет файлов лент: запустите без параметров, чтобы скачать")
    for n in news:
        print(f"{n['tag']:3} {n['id']} | {n['when']} | {n['title']}")


if __name__ == "__main__":
    main()
