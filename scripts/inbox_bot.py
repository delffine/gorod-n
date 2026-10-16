"""Бот-приёмник своих новостей «Город Н» (Telegram и MAX).

Пользователь присылает боту текст новости (и фото). Бот складывает его в data/inbox/<id>/,
запускает auto/inbox.sh <id> draft (Claude пишет пост по скиллу, раздел «Своя новость (бот)»)
и присылает предпросмотр с кнопками: сейчас / в очередь / ко времени / переделать / отмена.
Ответы идут в тот мессенджер, откуда пришла новость (meta.json → messenger).

Ключи — в ~/.config/gorodn.env:
    TG_BOT_TOKEN, TG_BOT_ALLOWED    — Telegram: токен @BotFather и ID пользователей через запятую
    MAX_BOT_TOKEN, MAX_BOT_ALLOWED  — MAX: токен с business.max.ru и user_id через запятую
Мессенджер без токена не запускается. Сообщения чужих бот игнорирует и только пишет их ID в лог.

Использование (на VPS):
    python scripts/inbox_bot.py run                     # слушать ботов (так его запускает auto/inbox_bot.sh)
    python scripts/inbox_bot.py set <id> key=value ...  # поменять поля meta.json (status, post, factcheck, url, error)
    python scripts/inbox_bot.py done <id> [--rc N]      # прислать пользователю итог прогона Claude по статусу
    python scripts/inbox_bot.py queue                   # id первой новости в очереди (status queued) или пусто
    python scripts/inbox_bot.py wait <id>               # сколько секунд ждать до проверки выхода поста (0 — не ждать)

Файлы элемента data/inbox/<id>/: text.md — текст (подписи альбома подряд), photo.jpg, photo_2.jpg… — фото,
meta.json — статус и прочее. Статусы: new → drafting → draft → publishing | queued → published | scheduled;
cancelled; error. Черновик без ответа дольше DRAFT_TTL удаляется целиком: папка, JSON и картинка поста.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INBOX = ROOT / "data" / "inbox"
STATE = INBOX / ".state.json"
TZ = timezone(timedelta(hours=4))  # время города Н (Europe/Samara)
SLOTS = (8, 14, 20)  # автопостинг cron, ±30 мин
GROUP_PAUSE = 3  # с: альбом приходит несколькими сообщениями — черновик начинаем после паузы
DRAFT_TTL = timedelta(hours=1)  # черновик без ответа удаляется: к этому времени уже прислана новая попытка

sys.path.insert(0, str(ROOT / "scripts"))
import post_json  # noqa: E402

HELP = """Пришлите текст новости одним сообщением, можно с фото (или альбомом).

Есть фото — в пост пойдёт оно, в нашей сепии. Напишите в тексте «карандаш» или «акварель» — \
вместо сепии будет рисунок по фото в стиле старой книжной иллюстрации. Нет фото — картинку нарисует нейросеть; \
пожелание к ней можно дописать отдельной строкой: «Картинка: …».

Напишите в тексте «от лица Бендера» — пост будет от первого лица: Остап сам видел и рассказывает.

Через пару минут пришлю готовый пост с кнопками. Без вашего «Сейчас» / «В очередь» / «Ко времени» \
ничего не публикуется.

/status — прошлый пост и где он вышел, что в работе, в очереди и когда следующий автопрогон"""

STATUS_RU = {
    "new": "принята", "drafting": "пишется", "draft": "черновик", "publishing": "публикуется",
    "queued": "в очереди", "scheduled": "запланирована", "published": "опубликована",
    "cancelled": "отменена", "error": "ошибка",
}


def now() -> datetime:
    return datetime.now(TZ)


def log(text: str):
    print(f"{now():%F %T} {text}", flush=True)


def multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    """Тело multipart/form-data: обычные поля + файлы-картинки. Возвращает (тело, Content-Type)."""
    boundary = uuid.uuid4().hex
    body = b"".join(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()
    )
    for k, path in files.items():
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{Path(path).name}"\r\n'
                 f"Content-Type: image/jpeg\r\n\r\n").encode() + Path(path).read_bytes() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


# --- мессенджеры
#
# Событие от мессенджера — словарь:
#   {"kind": "message", "user", "chat", "text", "photos": [ссылка для download], "group": id альбома или None,
#    "start": True для /start и кнопки «Начать»}
#   {"kind": "button", "user", "chat", "data", "callback": исходный объект нажатия}
# Кнопки — строки списков (текст, data).

class Telegram:
    name = "tg"

    def __init__(self):
        self.token = os.environ["TG_BOT_TOKEN"]
        self.allowed = allowed_ids("TG_BOT_ALLOWED")

    def api(self, method: str, files: dict | None = None, **params):
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        fields = {k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
                  for k, v in params.items() if v is not None}
        if files:
            body, content_type = multipart(fields, files)
            request = urllib.request.Request(url, body, {"Content-Type": content_type})
        else:
            request = urllib.request.Request(url, urllib.parse.urlencode(fields).encode())
        try:
            with urllib.request.urlopen(request, timeout=int(params.get("timeout", 0)) + 30) as response:
                return json.load(response)["result"]
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"tg {method}: {e.code} {e.read().decode(errors='replace')}") from None

    @staticmethod
    def keyboard(buttons: list) -> dict:
        return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in buttons]}

    def setup(self):
        self.api("setMyCommands", commands=[{"command": "status", "description": "Что в работе, в очереди и в расписании"},
                                            {"command": "start", "description": "Как прислать новость"}])

    def poll(self, state: dict, timeout: int) -> list[dict]:
        updates = self.api("getUpdates", offset=state.get("offset", 0), timeout=timeout,
                           allowed_updates=["message", "callback_query"])
        events = []
        for update in updates:
            state["offset"] = update["update_id"] + 1
            if "callback_query" in update:
                cq = update["callback_query"]
                events.append({"kind": "button", "user": cq["from"]["id"], "chat": cq["message"]["chat"]["id"],
                               "data": cq["data"], "callback": cq, "who": cq["from"]})
            elif "message" in update:
                msg = update["message"]
                text = msg.get("text") or msg.get("caption") or ""
                document = msg.get("document") or {}
                photo = (msg["photo"][-1]["file_id"] if msg.get("photo")
                         else document["file_id"] if document.get("mime_type") in ("image/jpeg", "image/png") else None)
                events.append({"kind": "message", "user": msg["from"]["id"], "chat": msg["chat"]["id"],
                               "text": text, "photos": [photo] if photo else [], "group": msg.get("media_group_id"),
                               "start": text.startswith(("/start", "/help")), "who": msg["from"]})
        return events

    def download(self, file_id: str, dst: Path):
        info = self.api("getFile", file_id=file_id)
        urllib.request.urlretrieve(f"https://api.telegram.org/file/bot{self.token}/{info['file_path']}", dst)

    def send(self, chat: int, text: str, buttons: list | None = None, photo: Path | None = None):
        markup = self.keyboard(buttons) if buttons else None
        if photo and len(text) <= 1024:
            self.api("sendPhoto", files={"photo": photo}, chat_id=chat, caption=text, reply_markup=markup)
            return
        if photo:
            self.api("sendPhoto", files={"photo": photo}, chat_id=chat)
        self.api("sendMessage", chat_id=chat, text=text, reply_markup=markup, link_preview_options={"is_disabled": True})

    def answer(self, event: dict, notification: str | None = None, buttons: list | None = None):
        """Ответ на нажатие; buttons — новая клавиатура под сообщением ([] — убрать), None — не трогать."""
        cq = event["callback"]
        try:
            self.api("answerCallbackQuery", callback_query_id=cq["id"], text=notification)
        except RuntimeError as e:  # нажатие дошло с опозданием («query is too old») — само действие всё равно выполняем
            log(f"tg answerCallbackQuery: {e}")
        if buttons is not None:
            self.api("editMessageReplyMarkup", chat_id=event["chat"], message_id=cq["message"]["message_id"],
                     reply_markup=self.keyboard(buttons))


class Max:
    name = "max"
    base = "https://platform-api.max.ru"

    def __init__(self):
        self.token = os.environ["MAX_BOT_TOKEN"]
        self.allowed = allowed_ids("MAX_BOT_ALLOWED")

    def api(self, http: str, path: str, body: dict | None = None, timeout: int = 0, **params):
        query = urllib.parse.urlencode({k: str(v).lower() if isinstance(v, bool) else v
                                        for k, v in params.items() if v is not None})
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        request = urllib.request.Request(f"{self.base}{path}?{query}", data, method=http,
                                         headers={"Authorization": self.token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout + 30) as response:
                return json.load(response)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"max {http} {path}: {e.code} {e.read().decode(errors='replace')}") from None

    @staticmethod
    def keyboard(buttons: list) -> dict:
        return {"type": "inline_keyboard", "payload": {"buttons": [
            [{"type": "callback", "text": t, "payload": d} for t, d in row] for row in buttons]}}

    def poll(self, state: dict, timeout: int) -> list[dict]:
        result = self.api("GET", "/updates", timeout=timeout, marker=state.get("max_marker"), limit=100,
                          types="message_created,message_callback,bot_started")
        if result.get("marker") is not None:
            state["max_marker"] = result["marker"]
        events = []
        for update in result.get("updates", []):
            kind = update.get("update_type")
            if kind == "bot_started":
                events.append({"kind": "message", "user": update["user"]["user_id"], "chat": update["user"]["user_id"],
                               "text": "", "photos": [], "group": None, "start": True, "who": update["user"]})
            elif kind == "message_callback":
                cb = update["callback"]
                events.append({"kind": "button", "user": cb["user"]["user_id"], "chat": cb["user"]["user_id"],
                               "data": cb.get("payload", ""), "callback": update, "who": cb["user"]})
            elif kind == "message_created":
                msg = update["message"]
                sender = msg.get("sender") or {}
                if sender.get("is_bot") or msg["recipient"].get("chat_type") != "dialog":
                    continue
                # пересланное сообщение — тоже новость: берём его текст и фото
                bodies = [msg.get("body") or {}, ((msg.get("link") or {}).get("message") or {})]
                text = "\n".join(b["text"] for b in bodies if b.get("text"))
                photos = [a["payload"]["url"] for b in bodies for a in (b.get("attachments") or [])
                          if a.get("type") == "image" and a.get("payload", {}).get("url")]
                events.append({"kind": "message", "user": sender.get("user_id"), "chat": sender.get("user_id"),
                               "text": text, "photos": photos, "group": None,
                               "start": text.startswith(("/start", "/help")), "who": sender})
        return events

    def setup(self):
        self.api("PATCH", "/me/commands", {"commands": [{"name": "status", "description": "Что в работе, в очереди и в расписании"},
                                               {"name": "start", "description": "Как прислать новость"}]})

    def download(self, url: str, dst: Path):
        urllib.request.urlretrieve(url, dst)

    def upload_image(self, path: Path) -> dict:
        """Загрузить картинку: POST /uploads?type=image → url, туда файл → JSON для вложения."""
        url = self.api("POST", "/uploads", type="image")["url"]
        body, content_type = multipart({}, {"data": path})
        with urllib.request.urlopen(urllib.request.Request(url, body, {"Content-Type": content_type}), timeout=120) as r:
            return {"type": "image", "payload": json.load(r)}

    def send(self, chat: int, text: str, buttons: list | None = None, photo: Path | None = None):
        attachments = ([self.upload_image(photo)] if photo else []) + ([self.keyboard(buttons)] if buttons else [])
        body = {"text": text[:4000], "attachments": attachments or None}
        for attempt in range(5):  # картинка обрабатывается не сразу: attachment.not.ready — повторить
            try:
                self.api("POST", "/messages", body, user_id=chat, disable_link_preview=True)
                return
            except RuntimeError as e:
                if "not.ready" not in str(e) or attempt == 4:
                    raise
                time.sleep(2)

    def answer(self, event: dict, notification: str | None = None, buttons: list | None = None):
        """Ответ на нажатие; buttons — новая клавиатура ([] — убрать): сообщение пересобирается с теми же картинками."""
        body = {"notification": notification or "Принято"}
        message = (event["callback"].get("message") or {}).get("body") or {}
        if buttons is not None and message:
            images = [{"type": "image", "payload": {"token": a["payload"]["token"]}}
                      for a in message.get("attachments") or [] if a.get("type") == "image"]
            body["message"] = {"text": message.get("text"), "attachments": images + ([self.keyboard(buttons)] if buttons else [])}
        try:
            self.api("POST", "/answers", body, callback_id=event["callback"]["callback"]["callback_id"])
        except RuntimeError as e:
            log(f"max answers: {e}")


def allowed_ids(var: str) -> set[int]:
    return {int(x) for x in os.environ.get(var, "").replace(" ", "").split(",") if x}


def messenger(name: str):
    return {"tg": Telegram, "max": Max}[name]()


# --- элементы data/inbox/<id>

def meta_path(item: str) -> Path:
    return INBOX / item / "meta.json"


def load_meta(item: str) -> dict:
    return json.loads(meta_path(item).read_text(encoding="utf-8"))


def update_meta(item: str, **fields) -> dict:
    meta = load_meta(item)
    meta.update(fields)
    meta_path(item).write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return meta


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict):
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def add_message(bot, item: str, event: dict):
    """Дописать к элементу текст и фото из сообщения (первое сообщение или следующее из альбома)."""
    folder = INBOX / item
    if event["text"]:
        with open(folder / "text.md", "a", encoding="utf-8") as f:
            f.write(event["text"].strip() + "\n")
    add_photos(bot, item, event["photos"])


def add_photos(bot, item: str, sources: list):
    folder = INBOX / item
    photos = load_meta(item)["photos"]
    for source in sources:
        name = "photo.jpg" if not photos else f"photo_{len(photos) + 1}.jpg"
        bot.download(source, folder / name)
        photos.append(name)
    update_meta(item, photos=photos)


def new_item(bot, event: dict) -> str:
    item = now().strftime("%Y%m%d_%H%M%S")
    while (INBOX / item).exists():
        item += "x"
    (INBOX / item).mkdir(parents=True)
    (INBOX / item / "text.md").write_text("", encoding="utf-8")
    meta_path(item).write_text("{}", encoding="utf-8")
    update_meta(item, id=item, messenger=bot.name, chat_id=event["chat"], received_at=now().isoformat(timespec="seconds"),
                status="new", photos=[], feedback=[], post=None, when=None)
    add_message(bot, item, event)
    return item


def remove_item(item: str, meta: dict):
    """Удалить элемент целиком: его пост (JSON и картинку) из posts/ и папку data/inbox/<id>."""
    if meta.get("post"):
        post_file = ROOT / meta["post"]
        try:
            post_json.image_path(post_file, post_json.load(post_file)).unlink(missing_ok=True)
        except (OSError, ValueError):
            pass
        post_file.unlink(missing_ok=True)
    shutil.rmtree(INBOX / item)


def start_job(item: str, action: str):
    """auto/inbox.sh <id> draft|publish в фоне; по окончании он сам вызовет `inbox_bot.py done`."""
    update_meta(item, status="drafting" if action == "draft" else "publishing", error=None)
    subprocess.Popen([str(ROOT / "auto" / "inbox.sh"), item, action], cwd=ROOT, start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log(f"{item}: запущен {action}")


def next_slot() -> datetime:
    current = now()
    for day in range(2):
        for hour in SLOTS:
            slot = (current + timedelta(days=day)).replace(hour=hour, minute=0, second=0, microsecond=0)
            if slot - timedelta(minutes=30) > current:
                return slot
    return current


def parse_time(text: str) -> datetime | None:
    """«18:30», «в 18.30», «завтра 9:00», «12.10 18:30». Прошедшее время без даты — на завтра."""
    m = re.fullmatch(r"(?:(сегодня|завтра|послезавтра)\s+|(\d{1,2})\.(\d{1,2})(?:\.(\d{2}|\d{4}))?\s+)?(?:в\s+)?"
                     r"(\d{1,2})[:.](\d{2})", text.strip().lower())
    if not m:
        return None
    word, day, month, year, hour, minute = m.groups()
    current = now()
    try:
        when = current.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
        if day:
            year = int(year) + (2000 if len(year) == 2 else 0) if year else current.year
            when = when.replace(year=year, month=int(month), day=int(day))
    except ValueError:
        return None
    when += timedelta(days={"завтра": 1, "послезавтра": 2}.get(word, 0))
    if not word and not day and when < current:
        when += timedelta(days=1)
    return when


def draft_buttons(item: str) -> list:
    return [
        [("✅ Сейчас", f"now:{item}"), ("🕗 В очередь", f"queue:{item}"), ("🕐 Ко времени", f"time:{item}")],
        [("✏️ Переделать", f"redo:{item}"), ("❌ Отмена", f"cancel:{item}")],
    ]


def items_by_status(*statuses: str) -> list[str]:
    if not INBOX.exists():
        return []
    return sorted(p.parent.name for p in INBOX.glob("*/meta.json") if load_meta(p.parent.name).get("status") in statuses)


def post_title(meta: dict) -> str:
    try:
        return post_json.load(ROOT / meta["post"])["title"]
    except (OSError, KeyError, TypeError, ValueError):
        return meta["id"]


PLATFORMS = (("telegram", "Telegram"), ("vk", "VK"), ("max", "MAX"), ("instagram", "Instagram"))


def last_post_report() -> str:
    """Последний пост в posts/ (по имени YYYYMMDD_HHMM-…) и что с ним в каждой сети."""
    posts = sorted((ROOT / "posts").glob("*.json"))
    if not posts:
        return "📰 Прошлых постов нет."
    try:
        post = post_json.load(posts[-1])
    except (OSError, ValueError) as e:
        return f"📰 Прошлый пост {posts[-1].name}: не читается ({e})"
    records = post.get("publications", [])
    if any(r["status"] == "scheduled" and r.get("via") == "postmypost" and r.get("published_at")
           and datetime.fromisoformat(r["published_at"]) <= now() for r in records):
        # время вышло, а записи ещё scheduled: спросить Postmypost (иначе их обновит только следующий автопрогон)
        try:
            subprocess.run([sys.executable, str(ROOT / "scripts" / "pmp_api.py"), "check", str(posts[-1])],
                           cwd=ROOT, capture_output=True, timeout=90)
            records = post_json.load(posts[-1]).get("publications", [])
        except (OSError, ValueError, subprocess.TimeoutExpired) as e:
            print(f"pmp_api check {posts[-1].name}: {e}", flush=True)
    lines = [f"📰 Прошлый пост: {post.get('title') or posts[-1].stem}"]
    if not records:
        lines.append("⚠️ Не опубликован ни в одну сеть.")
    for platform, name in PLATFORMS:
        mine = [r for r in records if r["platform"] == platform]
        published = [r for r in mine if r["status"] == "published"]
        scheduled = [r for r in mine if r["status"] == "scheduled"]
        if published:
            r = published[-1]
            times = f" ({len(published)} раза!)" if len(published) > 1 else ""
            line = f"✅ {at(r)}{times}"
        elif scheduled:
            r = scheduled[-1]
            when = datetime.fromisoformat(r["published_at"]) if r.get("published_at") else None
            line = (f"🕐 запланирован на {at(r)}" if when and when > now()
                    else f"⏳ назначен на {at(r)}, выход не подтверждён")
        elif mine:
            line = f"❌ ошибка: {mine[-1].get('error') or 'причина в логе'}"
        else:
            line = "— нет"
        if records:
            lines.append(f"• {name}: {line}")
    return "\n".join(lines)


def at(record: dict) -> str:
    try:
        return f"{datetime.fromisoformat(record['published_at']).astimezone(TZ):%d.%m %H:%M}"
    except (KeyError, TypeError, ValueError):
        return "?"


def queue_report() -> str:
    lines = []
    for item in items_by_status("queued", "scheduled", "publishing", "drafting", "draft"):
        meta = load_meta(item)
        when = f" — {datetime.fromisoformat(meta['when']):%d.%m %H:%M}" if meta.get("when") not in (None, "now", "queue") else ""
        lines.append(f"• {STATUS_RU[meta['status']]}{when}: {post_title(meta)}")
    return (last_post_report() + "\n\n" + ("\n".join(lines) or "Пусто: ни черновиков, ни очереди.")
            + "\n\n" + next_run_report())


def next_run_report() -> str:
    """Когда следующий автопрогон cron: точное время старта пишет auto/run.sh в temp/auto/next_run."""
    queued = items_by_status("queued")
    what = f"опубликует из очереди «{post_title(load_meta(queued[0]))}»" if queued else "возьмёт новость с сайта"
    try:
        start = datetime.fromtimestamp(int((ROOT / "temp" / "auto" / "next_run").read_text()), TZ)
    except (OSError, ValueError):
        start = None
    if start and start > now():
        return f"⏰ Автопрогон: {start:%d.%m в %H:%M} — {what}."
    if start and now() - start < timedelta(hours=1):  # старше часа — файл остался от упавшего прогона
        return f"⏰ Автопрогон идёт сейчас (начат в {start:%H:%M})."
    slot = next_slot()
    return (f"⏰ Автопрогон: {slot:%d.%m} между {slot - timedelta(minutes=30):%H:%M} "
            f"и {slot + timedelta(minutes=30):%H:%M} — {what}.")


# --- обработка сообщений и кнопок

class Inbox:
    """Общее состояние для всех мессенджеров; обработка событий — под одной блокировкой."""

    def __init__(self):
        INBOX.mkdir(parents=True, exist_ok=True)
        self.state = load_state()
        self.pending = {}  # элемент -> (бот, время последнего сообщения)
        self.groups = {}  # id альбома -> элемент
        self.lock = threading.Lock()

    def on_message(self, bot, event: dict):
        chat, text = event["chat"], event["text"]
        if event["start"]:
            bot.send(chat, HELP)
            return
        if text.startswith("/status"):
            bot.send(chat, queue_report())
            return
        awaiting = self.state.pop("awaiting", None)
        group = event["group"] and f"{bot.name}:{event['group']}"
        if awaiting and awaiting.get("messenger", "tg") == bot.name and awaiting["kind"] == "redo" and (text or event["photos"]):
            # правка может прийти с новым фото (или альбомом) — оно заменяет прежние
            item = awaiting["item"]
            meta = load_meta(item)
            feedback = text
            if event["photos"]:
                for name in meta["photos"]:
                    (INBOX / item / name).unlink(missing_ok=True)
                update_meta(item, photos=[])
                add_photos(bot, item, event["photos"])
                feedback = ((text + "\n") if text else "") + "Фото заменено на новое — картинку к посту сделать заново из него."
                if group:
                    self.groups[group] = item
            update_meta(item, feedback=meta["feedback"] + [feedback])
            self.pending[item] = (bot, time.time())  # черновик запустит start_ready, когда догрузится альбом
            log(f"{item}: правка ({bot.name})")
            return
        if awaiting and awaiting.get("messenger", "tg") == bot.name and text and not event["photos"]:
            item = awaiting["item"]
            if awaiting["kind"] == "time":
                when = parse_time(text)
                if not when or when < now() + timedelta(minutes=3):
                    self.state["awaiting"] = awaiting
                    bot.send(chat, "Не понял время или оно уже прошло. Примеры: 18:30, завтра 9:00, 12.10 18:30")
                    return
                update_meta(item, when=when.isoformat(timespec="minutes"))
                start_job(item, "publish")
                bot.send(chat, f"Ставлю публикацию на {when:%d.%m в %H:%M}…")
            return
        if group and group in self.groups:
            item = self.groups[group]
            add_message(bot, item, event)
        else:
            if not text and not event["photos"]:
                bot.send(chat, "Такое не понимаю: пришлите текст новости и, если есть, фото.")
                return
            item = new_item(bot, event)
            if group:
                self.groups[group] = item
            log(f"{item}: новая новость ({bot.name})")
        self.pending[item] = (bot, time.time())

    def on_button(self, bot, event: dict):
        action, item = event["data"].split(":", 1)
        chat = event["chat"]
        if not meta_path(item).exists():
            bot.answer(event, "Черновик уже удалён: час без ответа", buttons=[])
            return
        meta = load_meta(item)
        allowed = {"cancel": ("draft", "queued")}.get(action, ("draft",))
        if meta["status"] not in allowed:
            bot.answer(event, f"Новость уже {STATUS_RU[meta['status']]}")
            return
        if action == "queue":
            bot.answer(event, "В очереди", buttons=[[("❌ Убрать из очереди", f"cancel:{item}")]])
        elif action in ("now", "cancel"):
            bot.answer(event, "Принято", buttons=[])
        else:
            bot.answer(event)
        if action == "now":
            update_meta(item, when="now")
            start_job(item, "publish")
            bot.send(chat, "Публикую…")
        elif action == "queue":
            update_meta(item, status="queued", when="queue")
            bot.send(chat, f"Поставил в очередь: выйдет с ближайшим автопостом, около {next_slot():%H:%M}.")
        elif action == "time":
            update_meta(item, draft_at=now().isoformat(timespec="seconds"))  # час на ответ — заново
            self.state["awaiting"] = {"kind": "time", "item": item, "messenger": bot.name}
            bot.send(chat, "Когда публиковать? Например: 18:30, завтра 9:00, 12.10 18:30")
        elif action == "redo":
            update_meta(item, draft_at=now().isoformat(timespec="seconds"))
            self.state["awaiting"] = {"kind": "redo", "item": item, "messenger": bot.name}
            bot.send(chat, "Что поправить? Напишите одним сообщением.")
        elif action == "cancel":
            update_meta(item, status="cancelled")
            bot.send(chat, "Отменено.")
        log(f"{item}: кнопка {action} ({bot.name})")

    def handle(self, bot, event: dict):
        who = event.get("who") or {}
        if event["user"] not in bot.allowed:
            log(f"чужой ({bot.name}): id {event['user']} @{who.get('username')} {who.get('first_name')} — игнор")
            return
        try:
            if event["kind"] == "button":
                self.on_button(bot, event)
            else:
                self.on_message(bot, event)
        except Exception as e:
            log(f"ошибка ({bot.name}): {e!r}")
            try:
                bot.send(event["chat"], f"⚠️ Ошибка бота: {e}")
            except Exception:
                pass

    def start_ready(self):
        """Запустить черновики, по которым альбом уже точно догрузился."""
        for item, (bot, last) in list(self.pending.items()):
            if time.time() - last > GROUP_PAUSE:
                del self.pending[item]
                bot.send(load_meta(item)["chat_id"], "Принял, готовлю пост — это пара минут.")
                start_job(item, "draft")

    def expire_drafts(self, bot):
        """Удалить черновики этого мессенджера, на которые не ответили за DRAFT_TTL."""
        for item in items_by_status("draft"):
            meta = load_meta(item)
            if meta.get("messenger", "tg") != bot.name or item in self.pending:
                continue
            since = datetime.fromisoformat(meta.get("draft_at") or meta["received_at"])
            if now() - since < DRAFT_TTL:
                continue
            title = post_title(meta)
            remove_item(item, meta)
            if (self.state.get("awaiting") or {}).get("item") == item:
                del self.state["awaiting"]
            log(f"{item}: черновик удалён — без ответа с {since:%d.%m %H:%M}")
            try:
                bot.send(meta["chat_id"], f"🗑 Черновик удалён — час без ответа: {title}")
            except Exception as e:
                log(f"{item}: не сообщил об удалении: {e}")

    def listen(self, bot):
        log(f"{bot.name}: слушаю, разрешены: {sorted(bot.allowed) or 'никто'}")
        try:
            bot.setup()
        except Exception as e:
            log(f"{bot.name} setup: {e}")
        while True:
            try:
                events = bot.poll(self.state, timeout=1 if self.pending else 50)
            except Exception as e:  # сеть, 5xx и т. п. — подождать и продолжить
                log(f"{bot.name} poll: {e}")
                time.sleep(10)
                continue
            with self.lock:
                for event in events:
                    self.handle(bot, event)
                try:
                    self.expire_drafts(bot)
                except Exception as e:
                    log(f"{bot.name} expire_drafts: {e!r}")
                save_state(self.state)
                self.start_ready()


def run():
    inbox = Inbox()
    bots = [messenger(name) for name, var in (("tg", "TG_BOT_TOKEN"), ("max", "MAX_BOT_TOKEN")) if os.environ.get(var)]
    if not bots:
        sys.exit("нет ни TG_BOT_TOKEN, ни MAX_BOT_TOKEN")
    threads = [threading.Thread(target=inbox.listen, args=(bot,), daemon=True) for bot in bots]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


# --- команды для auto/inbox.sh и Claude

def done(item: str, rc: int | None):
    meta = load_meta(item)
    if meta["status"] in ("drafting", "publishing"):
        meta = update_meta(item, status="error", error=f"Claude не закончил работу (код {rc}), подробности в логе")
    bot, chat, status = messenger(meta.get("messenger", "tg")), meta["chat_id"], meta["status"]
    if status == "draft":
        update_meta(item, draft_at=now().isoformat(timespec="seconds"))  # отсюда считается DRAFT_TTL
        post_file = ROOT / meta["post"]
        post = post_json.load(post_file)
        text = post_json.render_text(post)
        if meta.get("factcheck"):
            bot.send(chat, f"Фактчек: {meta['factcheck']}")
        image = post_json.image_path(post_file, post)
        bot.send(chat, text if len(text) <= 1024 else f"{text}\n\n({len(text)} символов)",
                 buttons=draft_buttons(item), photo=image if image.exists() else None)
    elif status == "published":
        bot.send(chat, f"✅ Опубликовано: {post_title(meta)}\n{meta.get('url') or ''}".strip())
    elif status == "scheduled":
        when = datetime.fromisoformat(meta["when"])
        if when > now():
            bot.send(chat, f"🕐 Запланировано на {when:%d.%m в %H:%M}: {post_title(meta)}")
        else:
            bot.send(chat, f"⏳ Postmypost выкладывает с задержкой (назначено на {when:%H:%M}): {post_title(meta)}\n"
                           "Ссылку пришлю, когда выйдет, — проверка при ближайшем автопостинге.")
    elif status == "error":
        bot.send(chat, f"⚠️ Не получилось: {meta.get('error') or 'причина в логе'}")


def wait_seconds(item: str) -> int:
    """Сколько ждать перед проверкой выхода поста: запланирован на ближайшие 15 мин — до времени + 2 мин, иначе 0."""
    meta = load_meta(item)
    if meta["status"] != "scheduled" or meta.get("when") in (None, "now", "queue"):
        return 0
    left = (datetime.fromisoformat(meta["when"]) - now()).total_seconds()
    return int(max(left, 0)) + 120 if left < 15 * 60 else 0


def set_fields(item: str, pairs: list[str]):
    fields = {}
    for pair in pairs:
        key, value = pair.split("=", 1)
        fields[key] = None if value in ("", "null") else value
    update_meta(item, **fields)
    print(f"{item}: {fields}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run")
    p = sub.add_parser("set")
    p.add_argument("item")
    p.add_argument("pairs", nargs="+", metavar="key=value")
    p = sub.add_parser("done")
    p.add_argument("item")
    p.add_argument("--rc", type=int)
    sub.add_parser("queue")
    sub.add_parser("wait").add_argument("item")
    args = parser.parse_args()
    if args.command == "run":
        run()
    elif args.command == "set":
        set_fields(args.item, args.pairs)
    elif args.command == "done":
        done(args.item, args.rc)
    elif args.command == "queue":
        print(next(iter(items_by_status("queued")), ""))
    elif args.command == "wait":
        print(wait_seconds(args.item))


if __name__ == "__main__":
    main()
