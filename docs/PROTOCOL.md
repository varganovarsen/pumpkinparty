# Протокол клиент ↔ сервер

Версия этапа 1 (ядро). Дополняется в модулях 02-07 до начала каждого этапа.

## REST (вход и загрузки)

| Метод и путь | Тело / параметры | Ответ |
|---|---|---|
| `GET /api/health` | — | `{ok, server_ms, speed}` |
| `GET /api/info` | — | `{join_url, name_max, avatars:[{id,url,taken}], stickers:[url]}` |
| `GET /api/qr.svg?path=/` | путь на сервере | SVG с QR на `join_url + path` |
| `POST /api/upload_avatar` | multipart `file` (JPEG/PNG/HEIC) | `{ok, upload_id, preview_url}` — превью уже с EXIF-поворотом |
| `POST /api/avatar_crop` | `{upload_id, cx, cy, size}` (доли превью: центр и сторона квадрата от меньшей стороны) | `{ok, avatar_ref, avatar_url}` — PNG 256×256 с круглой прозрачностью |
| `POST /api/join` | `{name, avatar_kind: pumpkin\|photo, avatar_ref, as_host?}` | `{ok, token, me}`; ошибка 409 `{code, error, can_claim?}` |
| `POST /api/claim` | `{name}` | «Это я?»: `{ok, token, me}`, только если игрок не в сети |
| `GET /api/check` | — | `{items:[{id,title,status: ok\|warn\|fail\|info, detail, items}], summary}` |
| `GET /api/webcam_test` | — | JPEG или 503 `{error}` |
| `GET /api/pumpkin/{player_id}` | — | `{exists, version, camera:{theta,phi,radius}, mask_size, masks:{through,depth}, shots:{lit,dark,side}}` (URL с `?v=версия`) |
| `POST /api/pumpkin/{player_id}` | multipart: `through.png`, `depth.png` (маски развёртки, квадрат, одинаковый размер), `lit.jpg`, `dark.jpg`, `side.jpg`, `camera` (JSON) | то же, что GET, + `ok`; ошибки `bad_mask`, `bad_shot`, `bad_request`, `not_found`, `locked` (идёт голосование) |

Коды ошибок входа: `bad_name`, `name_taken`, `avatar_taken`, `bad_avatar`, `host_exists`, `not_found`.

## WebSocket

`/ws?role=tv|host|player|carve&token=…` (токен только у `player`). Сообщения JSON `{"t": "<тип>", …}`.

- `role=tv` принимается только с localhost (если `tv_localhost_only`), иначе `{"t":"error","code":"tv_localhost_only"}` и закрытие 4403.
- `role=player` с неизвестным токеном: `{"t":"auth_failed"}` и закрытие 4401 → клиент забывает токен и показывает вход.
- Закрытия 4400/4401/4403 — без переподключения. Остальные — переподключение с нарастающей паузой (0,4 → 5 с).

### Синхронизация часов

Клиент → `{"t":"ping","c":<performance.now()>}`, сервер → `{"t":"pong","c":…,"s":<server_ms>}`.
При подключении 5 пингов, дальше пинг каждые 4 с (он же проверка живости: нет сообщений 20 с → переподключение).
Берётся замер с наименьшим RTT: `serverNow = s + rtt/2 + (now - t_замера) * speed`.
Все дедлайны и метки сервер присылает как серверное время (мс или с, указано в поле).
`speed` — ускорение времени для симулятора (из снимка).

### Снимок (`snapshot`) — первое сообщение после подключения

Общие поля: `role, server_ms, speed, scene, settings, join_url`.

| Роль | Дополнительно |
|---|---|
| player | `me`, `facts`, `facts_locked`, `avatars_taken`, `quiz` (вид игрока) |
| tv | `players`, `head`, `stubs` (список путей-заглушек), `quiz` |
| host | `players`, `log` (50 строк), `scenes`, `next_step`, `tv_count`, `quiz` (полный вид) |
| carve | `players` (без очков, с `pumpkin_version`: 0 — тыквы нет) |

`scene = {scene, payload, started_at, participating, title}`.
`me = {id, name, avatar_url, avatar_kind, avatar_ref, is_host, in_scoring, score}` (`score = null`, если общий рейтинг скрыт).
`players[] = {id, name, avatar_url, avatar_kind, is_host, in_scoring, connected, pumpkin_version, score}`.
`facts[] = {n, text|null}` (`null` — ещё не показан; во время раунда 4 все `null`).
`next_step = {label, cmd, args?, disabled?, hint?}` или `null` — контекстная кнопка «Следующий шаг»: `/host` просто шлёт команду `cmd` с `args`.

Повторная доставка безопасна: снимок полностью заменяет состояние клиента.

### Маски тыквы

Квадратные PNG 8 бит (по умолчанию 2048×2048) в развёртке модели: верхняя строка картинки = `v = 0`
(как текстуры glTF, загружаются с `flipY = false`). `through`: 255 — вырезано насквозь. `depth`: 0-255 — глубина
декора (одна глубина, 255). Файлы лежат в `data/pumpkins/<player_id>/`, хранится только последняя версия.

### Квиз (`quiz`)

Фазы: `idle` → `intro` (заставка раунда) → `question` → [`judging`, только раунд 4] → `reveal` → … → `rating` (итоги
раунда) → `intro` следующего раунда. После итогов раунда 4 `done = true`. Живые фазы (уход из сцены с подтверждением):
`question`, `judging`.

Общие поля: `round` (1-4, 0 — не начат), `rounds_total`, `phase`, `done`, `round_title`, `q_index` (с 0), `q_count`,
`started_at_ms`, `deadline_ms` (серверное время, мс), `answer_seconds`, `warn_seconds`, `facts_locked`.
В фазах `question/judging/reveal`: `question = {id, kind: choice|text, text, options?}` (+ `image_url` только tv/host),
`answered_count`, `eligible_count`.
- `reveal`: `{skipped, top: [{player_id, name, avatar_url, t, bonus}], correct, counts[4], explain}` для выбора,
  `{skipped, top, answer, answers: [{name, avatar_url, text, verdict}]}` для раунда 4.
- `rating`: `{round: [{player_id, name, avatar_url, points, place}], total: [...] | null}` (вне зачёта не показываются,
  `total = null`, пока общий рейтинг скрыт).
- только player: `my = {eligible, answered, choice?, text?, result?: {points, bonus, correct, skipped}, verdict?,
  round_points?, round_place?}`.
- только host: `next`, `question_full` (с правильным ответом / эталоном), `answers: [{player_id, name, avatar_url,
  choice, text, verdict, t}]`, `waiting` (имена тех, кто ещё не ответил).

Порядок ответов (бонусы +50/+25/+10) — по номеру прихода на сервер. Начисления: `quiz` 200 за верный, `quiz_bonus`,
`ref` = id вопроса (`r1q03`, раунд 4 — `r4q1`…).

### События сервера

| `t` | Кому | Поля |
|---|---|---|
| `scene` | все | как `scene` в снимке |
| `settings` | все | `settings` |
| `players` | tv, host, carve | `players` (carve — без очков) |
| `me` | конкретный player | `me` |
| `avatars_taken` | player | `taken` |
| `facts` | player | `facts`, `locked` |
| `quiz` | tv, host, каждый player | `quiz` (вид для роли) |
| `head` | tv | `head = {fact_id, text, audio_url, mode, seconds, called_at}` или `null` |
| `log` | host | `entry = {id, ts, player_id, text}` |
| `next_step` | host | `next_step` |
| `tv_count` | host | `count` |
| `sound_test` | tv | — |
| `reload` | tv | перезагрузить текущую сцену |
| `reset` | все | вечер сброшен; player забывает токен |
| `reply` | автор команды | `{id, ok, error?, code?, …}` (событие, вызванное командой, приходит раньше `reply`) |

### Команды (`{"t":"cmd","cmd":"<имя>","id":<n>, …}`)

Сервер проверяет роль; чужая команда → `reply` с `code: "forbidden"`.

| Роль | Команда | Аргументы |
|---|---|---|
| host | `set_scene` | `scene, payload?, force?` — из живой фазы (вопрос квиза, игра, голосование) без `force` вернёт `code: "confirm_required"` |
| host | `set_setting` | `key, value`; ключи: `host_in_scoring, hide_total, head_mode, head_enabled, head_interval_minutes, light_mode, new_photo_card` |
| host | `adjust_score` | `player_id, amount (≠0), note` → запись `manual` в ledger |
| host | `reset_evening` | `confirm: "СБРОС"` → `{backup}` |
| host | `reload_scene`, `sound_test` | — |
| host | `skip_question` | — закрыть вопрос без начислений |
| host | `quiz_start_round`, `quiz_show`, `quiz_close`, `quiz_reveal`, `quiz_next` | — (только в сцене `quiz`) |
| host | `quiz_verdict` | `player_id, ok: true\|false\|null` (null — снять вердикт) |
| host | `quiz_verdict_rest` | `ok` — всем без вердикта |
| host | `get_log` | `player_id?` → `{log}` |
| host | `head_call`, `head_skip` | — |
| tv | `head_shown`, `head_done` | `fact_id` |
| player | `update_profile` | `avatar_kind, avatar_ref` |
| player | `quiz_answer` | `qid, choice (0-3)` или `qid, text` → ошибки `closed`, `late`, `already`, `bad_answer` |
| все | `snapshot` | — (прислать снимок заново) |
