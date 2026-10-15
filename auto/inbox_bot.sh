#!/bin/bash
# Бот-приёмник своих новостей (scripts/inbox_bot.py). Cron раз в 5 минут:
# если бот уже работает — сразу выходит, если нет (перезагрузка, падение) — запускает.
# Лог: ~/gorod-n/temp/logs/inbox_bot.log
set -u
cd "$(dirname "$0")/.."
mkdir -p temp/logs temp/auto
exec 8>temp/auto/.inbox_bot.lock
flock -n 8 || exit 0
set -a; . "$HOME/.config/gorodn.env"; set +a
exec >>temp/logs/inbox_bot.log 2>&1
exec venv/bin/python -u scripts/inbox_bot.py run
