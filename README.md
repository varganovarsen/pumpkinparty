# Тыквенный спас

Локальное веб-приложение для домашней вечеринки: сервер на ноутбуке, картинка на телевизоре, гости со смартфонов. Спецификация: [`docs/spec/SPEC.md`](docs/spec/SPEC.md).

## Запуск

- Ноутбук (Ubuntu): `./start.sh` — ставит зависимости в `.venv`, поднимает сервер и открывает Firefox в киоске на `/tv`. `./start.sh --no-browser` — только сервер.
- Windows (разработка): `start.bat`, затем `http://localhost:8000/tv`.
- Вручную: `python -m server [--port 8000] [--data data] [--speed 1]`.

| Адрес | Кто |
|---|---|
| `/tv` | телевизор (только с самого ноутбука) |
| `/host`, `/check` | ведущий (ссылок нигде нет) |
| `/` | гости, по QR |
| `/carve` | iPad |
| `/download` | скачивание фото |

## Разработка

- Тесты: `pip install -r requirements-dev.txt && python -m pytest`. Синтаксис JS: `node --experimental-vm-modules tools/check_js.mjs`.
- Симулятор: `python tools/simulator.py --players 8 --speed 30 --scenario evening` (квиз — на тестовом контенте).
- Попробовать квиз без настоящего контента: `set PUMPKIN_CONTENT=tests\fixtures\content` (Windows) перед запуском сервера.
- Контент: `python tools/check_content.py`. Липсинк: `python tools/make_lipsync.py`, предпросмотр — `/tools/lipsync-preview`.
- Заглушки ассетов: `python tools/make_stubs.py` (нужен ffmpeg).
- Модель тыквы из glTF: `python tools/pack_model.py <папка со scene.gltf>` → `assets/carve/pumpkin.glb`.
- Сторонние материалы и лицензии: [`docs/CREDITS.md`](docs/CREDITS.md).
- Протокол: [`docs/PROTOCOL.md`](docs/PROTOCOL.md), решения: [`docs/DECISIONS.md`](docs/DECISIONS.md), чек-лист вечера: [`docs/CHECKLIST.md`](docs/CHECKLIST.md).

## Состояние

- Этап 1 (ядро, модули 01 и 08) готов.
- Этап 2: прототип резьбы на `/carve` проверен на iPad — решение «идём» (`docs/DECISIONS.md`). Аллея и голосование — день 11.
- Этап 3: квиз (4 раунда, бонусы за скорость, раунд 4 с ручной проверкой, скрытый рейтинг) готов. Симулятор прогоняет его целиком.
- Этапы 4-6: фото (селфи, альбом, кадры вебки, финальное фото, скачивание), голова-тыква (таймер, Rive, липсинк), игра, аллея и голосование, таймер, слайд-шоу, общий рейтинг — готовы. Симулятор прогоняет весь вечер.
- Код прошёл ревью (код и архитектура), исправления внесены. Черновик контента готов: 38 фактов, 30 вопросов, 10 фото сортов (`content/`, источники — `content/SOURCES.md`).
- Дальше: полный прогон вечера руками, вычитка контента, настоящие ассеты и озвучка, репетиция на ноутбуке.
