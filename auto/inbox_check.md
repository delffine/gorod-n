Своя новость «Город Н» из бота: элемент data/inbox/{ITEM}/. Пост уже отправлен в Postmypost,
нужно только проверить, вышел ли он. Вопросов не задавай, ничего не публикуй заново.

Используй скилл city-n-news-to-soc: по шагу 0 проверь только пост из meta.json (поле post) —
`get_publication(<post_id>)` для записей `scheduled` в его `publications`.
- Вышло — обнови записи (`post_json.py --record-postmypost …` без `--status`) и
  `python scripts/inbox_bot.py set {ITEM} status=published url=<ссылка VK>`.
- Ещё ждёт публикации — ничего не меняй (статус останется scheduled, закроет следующий запуск).
- Ошибка публикации — `python scripts/inbox_bot.py set {ITEM} status=error "error=<что случилось>"`.

Итог — одна строка.
