"""Чистка старья «Город Н»: посты и элементы бота старше KEEP_DAYS.

- posts/YYYYMMDD_HHMM-*: все файлы поста (JSON, картинка), если время в имени (время выхода) старше срока;
- data/inbox/<id>: завершённые элементы бота (опубликованы, отменены, ошибка), полученные раньше срока.
Дубли проверяются по постам за последние 3 дня, поэтому более старые не нужны.

Использование (запускает auto/run.sh в конце прогона):
    python scripts/cleanup.py            # удалить
    python scripts/cleanup.py --dry-run  # только показать
"""
import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEEP_DAYS = 3
DONE = ("published", "scheduled", "cancelled", "error")  # с остальными бот ещё работает


def old_posts(border: datetime) -> list[Path]:
    files = []
    for path in sorted((ROOT / "posts").iterdir()):
        m = re.match(r"(\d{8}_\d{4})-", path.name)
        if path.is_file() and m and datetime.strptime(m.group(1), "%Y%m%d_%H%M") < border:
            files.append(path)
    return files


def old_inbox(border: datetime) -> list[Path]:
    folders = []
    for meta_file in sorted((ROOT / "data" / "inbox").glob("*/meta.json")):
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            received = datetime.fromisoformat(meta["received_at"]).replace(tzinfo=None)
        except (OSError, ValueError, KeyError):
            continue
        if meta.get("status") in DONE and received < border:
            folders.append(meta_file.parent)
    return folders


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    border = datetime.now() - timedelta(days=KEEP_DAYS)  # на VPS локальное время — время города Н
    posts, inbox = old_posts(border), old_inbox(border)
    for path in posts:
        if not args.dry_run:
            path.unlink()
    for folder in inbox:
        if not args.dry_run:
            shutil.rmtree(folder)
    verb = "к удалению" if args.dry_run else "удалено"
    print(f"cleanup: {verb} файлов постов {len(posts)}, элементов бота {len(inbox)} (старше {border:%d.%m %H:%M})")
    for path in posts + inbox:
        print(f"  {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
