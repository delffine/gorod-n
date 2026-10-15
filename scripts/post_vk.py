"""Публикация поста с картинкой на стену группы ВКонтакте.

Использование:
    python scripts/post_vk.py --check                       # проверить ключ и доступ к группе
    python scripts/post_vk.py <пост.json>                    # опубликовать пост, результат — в JSON
    python scripts/post_vk.py <текст.txt> <картинка.jpg>     # опубликовать текст с картинкой
    python scripts/post_vk.py --delete <id поста>             # удалить пост

Ключи берутся из .env: VK_GROUP_ID, VK_TOKEN (ключ группы — для проверки),
VK_ADMIN_TOKEN (ключ пользователя-администратора с правами wall, photos, groups —
для загрузки фото, публикации и удаления; с ключом группы фото к посту не прикрепить).
"""
import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_image import ROOT, load_env  # noqa: E402
import post_json  # noqa: E402

API = "https://api.vk.com/method/"
VERSION = "5.199"


class VkError(Exception):
    pass


def call(method: str, token: str, **params) -> dict:
    params.update(access_token=token, v=VERSION)
    data = urllib.parse.urlencode(params).encode("utf-8")
    with urllib.request.urlopen(API + method, data=data, timeout=60) as resp:
        answer = json.load(resp)
    if "error" in answer:
        err = answer["error"]
        raise VkError(f"{method}: [{err.get('error_code')}] {err.get('error_msg')}")
    return answer["response"]


def upload_file(url: str, path: Path, field: str = "photo") -> dict:
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field}"; filename="{path.name}"\r\n'
        "Content-Type: image/jpeg\r\n\r\n"
    ).encode("utf-8") + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def credentials() -> tuple[str, str]:
    env = load_env(ROOT / ".env")
    group_id = "".join(c for c in env.get("VK_GROUP_ID", "") if c.isdigit())  # club123 / -123 / 123
    token = env.get("VK_TOKEN")
    if not group_id or not token:
        sys.exit("В .env не заполнены VK_GROUP_ID / VK_TOKEN")
    return group_id, token


def admin_token() -> str:
    """Ключ пользователя-администратора группы: только с ним фото прикрепляется к посту как фото."""
    token = load_env(ROOT / ".env").get("VK_ADMIN_TOKEN")
    if not token:
        sys.exit("В .env не заполнен VK_ADMIN_TOKEN (ключ администратора, см. README)")
    return token


def check():
    group_id, token = credentials()
    info = call("groups.getById", token, group_id=group_id)
    group = info["groups"][0] if isinstance(info, dict) else info[0]
    print(f"Группа: {group['name']} (id {group['id']})")
    user = call("users.get", admin_token())[0]
    print(f"Администратор: {user['first_name']} {user['last_name']}")
    server = call("photos.getWallUploadServer", admin_token(), group_id=group_id)
    print("Загрузка фото на стену: доступна" if server.get("upload_url") else "Нет upload_url")


def upload_photo(token: str, group_id: str, image_file: Path) -> str:
    """Загружает фото на стену группы и возвращает строку вложения для wall.post."""
    server = call("photos.getWallUploadServer", token, group_id=group_id)
    uploaded = upload_file(server["upload_url"], image_file)
    saved = call(
        "photos.saveWallPhoto", token, group_id=group_id,
        photo=uploaded["photo"], server=uploaded["server"], hash=uploaded["hash"],
    )[0]
    return f"photo{saved['owner_id']}_{saved['id']}"


def publish(message: str, image_file: Path) -> tuple[str, int]:
    group_id, _ = credentials()
    token = admin_token()
    attachment = upload_photo(token, group_id, image_file)

    post = call(
        "wall.post", token, owner_id=f"-{group_id}", from_group=1,
        message=message, attachments=attachment,
    )
    print(f"Опубликовано: https://vk.com/wall-{group_id}_{post['post_id']}")
    return group_id, post["post_id"]


def publish_json(path: Path):
    """Публикует пост из JSON и дописывает в него результат (успех или ошибку)."""
    post = post_json.load(path)
    if post_json.is_published(post, "vk"):
        sys.exit("Этот пост уже опубликован в VK (см. publications в JSON)")
    try:
        group_id, post_id = publish(post_json.render_text(post), post_json.image_path(path, post))
    except VkError as e:
        post_json.add_publication(post, "vk", f"club{credentials()[0]}", "error", error=str(e))
        post_json.save(path, post)
        raise
    post_json.add_publication(
        post, "vk", f"club{group_id}", "published", via="vk_api",
        post_id=post_id, url=f"https://vk.com/wall-{group_id}_{post_id}", error=None,
    )
    post_json.save(path, post)


def delete(post_id: int):
    group_id, _ = credentials()
    call("wall.delete", admin_token(), owner_id=f"-{group_id}", post_id=post_id)
    print(f"Удалено: wall-{group_id}_{post_id}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text_file", nargs="?", help="пост .json или текст .txt")
    parser.add_argument("image_file", nargs="?")
    parser.add_argument("--check", action="store_true", help="только проверить доступ")
    parser.add_argument("--delete", type=int, metavar="POST_ID", help="удалить пост группы")
    args = parser.parse_args()
    try:
        if args.check:
            check()
        elif args.delete:
            delete(args.delete)
        elif args.text_file and args.text_file.endswith(".json"):
            publish_json(Path(args.text_file))
        elif args.text_file and args.image_file:
            publish(Path(args.text_file).read_text(encoding="utf-8").strip(), Path(args.image_file))
        else:
            parser.error("нужен пост .json, либо файлы текста и картинки, либо --check")
    except VkError as e:
        sys.exit(f"Ошибка VK API {e}")


if __name__ == "__main__":
    main()
