#!/bin/bash
# Автопостинг «Город Н» по cron: одна новость -> пост -> TG + VK + MAX + Instagram.
# Cron стартует за 30 мин до целевого времени, случайная пауза 0-60 мин даёт ±30 мин.
# Ручной прогон без паузы: auto/run.sh --now
# Лог: ~/gorod-n/temp/logs/auto_ГГГГ-ММ-ДД.log
set -u
cd "$(dirname "$0")/.."
ROOT="$PWD"
mkdir -p temp/logs temp/auto
LOG="temp/logs/auto_$(date +%F).log"
exec >>"$LOG" 2>&1
exec 9>temp/auto/.lock
flock -n 9 || { echo "$(date '+%F %T') прошлый прогон ещё идёт — пропуск"; exit 0; }

delay=0
[ "${1:-}" != "--now" ] && delay=$((RANDOM % 3600))
# время старта для /status в боте; удаляется в конце прогона
echo $(( $(date +%s) + delay )) > temp/auto/next_run
trap 'rm -f temp/auto/next_run' EXIT
if [ "$delay" -gt 0 ]; then
  echo "$(date '+%F %T') пауза ${delay} с"
  sleep "$delay"
fi

# Один CPU: не запускаться параллельно с Claude ai-editor (ждём до 20 мин)
for _ in $(seq 40); do
  pgrep -u deploy -f '.local/bin/claude' >/dev/null || break
  sleep 30
done

echo "===== $(date '+%F %T') старт"
set -a; . "$HOME/.config/gorodn.env"; set +a
export PATH="$ROOT/venv/bin:$HOME/.local/bin:$PATH"

timeout -s KILL 1500 claude -p "$(cat auto/prompt.md)" \
  --tools "Read,Edit,Write,Bash,Grep,Glob,Skill,Agent" \
  --permission-mode dontAsk \
  --allowedTools "Read(//home/gorodn/gorod-n/**),Edit(//home/gorodn/gorod-n/**),Write(//home/gorodn/gorod-n/**),Grep,Glob,Skill,Agent,Bash,mcp__postmypost" \
  --output-format json < /dev/null > temp/auto/claude.json
rc=$?
python -c 'import json;d=json.load(open("temp/auto/claude.json"));print("is_error",d.get("is_error"),"turns",d.get("num_turns"),"ms",d.get("duration_ms"),"cost",round(d.get("total_cost_usd") or 0,3));print(d.get("result",""))' 2>/dev/null
echo "claude exit=$rc"
python scripts/cleanup.py  # посты и элементы бота старше 3 дней
echo "===== $(date '+%F %T') конец"
