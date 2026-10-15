#!/bin/bash
# Своя новость из бота: прогон Claude по одному элементу data/inbox/<id>.
#   auto/inbox.sh <id> draft    — написать пост (или переделать по замечанию), бот пришлёт предпросмотр
#   auto/inbox.sh <id> publish  — опубликовать готовый пост сейчас или ко времени meta.when;
#                                 если пост выходит в ближайшие 15 мин — дождаться и проверить выход
# Запускает scripts/inbox_bot.py. Лог: ~/gorod-n/temp/logs/inbox_ГГГГ-ММ-ДД.log
set -u
cd "$(dirname "$0")/.."
ROOT="$PWD"
ITEM="$1"
ACTION="$2"
mkdir -p temp/logs temp/auto
exec >>"temp/logs/inbox_$(date +%F).log" 2>&1
set -a; . "$HOME/.config/gorodn.env"; set +a
export PATH="$ROOT/venv/bin:$HOME/.local/bin:$PATH"
# прогоны по своим новостям — строго по одному
exec 9>temp/auto/.inbox.lock
flock 9

run_claude() {  # $1 — имя промта: auto/inbox_<имя>.md
  # Один CPU: подождать Claude ai-editor (до 5 мин) — пользователь ждёт ответа в боте
  for _ in $(seq 10); do
    pgrep -u deploy -f '.local/bin/claude' >/dev/null || break
    sleep 30
  done
  echo "===== $(date '+%F %T') $ITEM $1"
  timeout -s KILL 1200 claude -p "$(sed "s|{ITEM}|$ITEM|g" "auto/inbox_$1.md")" \
    --tools "Read,Edit,Write,Bash,Grep,Glob,Skill,Agent" \
    --permission-mode dontAsk \
    --allowedTools "Read(//home/gorodn/gorod-n/**),Edit(//home/gorodn/gorod-n/**),Write(//home/gorodn/gorod-n/**),Grep,Glob,Skill,Agent,Bash,mcp__postmypost" \
    --output-format json < /dev/null > temp/auto/inbox_claude.json
  rc=$?
  python -c 'import json;d=json.load(open("temp/auto/inbox_claude.json"));print("is_error",d.get("is_error"),"turns",d.get("num_turns"),"ms",d.get("duration_ms"),"cost",round(d.get("total_cost_usd") or 0,3));print(d.get("result",""))' 2>/dev/null
  echo "claude exit=$rc"
}

run_claude "$ACTION"
if [ "$ACTION" = publish ]; then
  wait=$(python scripts/inbox_bot.py wait "$ITEM")
  if [ "${wait:-0}" -gt 0 ]; then
    echo "$(date '+%F %T') жду выхода поста ${wait} с"
    flock -u 9  # пока ждём, другие новости могут готовиться
    sleep "$wait"
    flock 9
    run_claude check
  fi
fi
python scripts/inbox_bot.py done "$ITEM" --rc "$rc"
echo "===== $(date '+%F %T') конец"
