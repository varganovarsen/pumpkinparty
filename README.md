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

- Тесты: `pip install -r requirements-dev.txt && python -m pytest`.
- Симулятор: `python tools/simulator.py --players 8 --speed 30 --scenario evening`.
- Контент: `python tools/check_content.py`.
- Заглушки ассетов: `python tools/make_stubs.py` (нужен ffmpeg).
- Модель тыквы из glTF: `python tools/pack_model.py <папка со scene.gltf>` → `assets/carve/pumpkin.glb`.
- Сторонние материалы и лицензии: [`docs/CREDITS.md`](docs/CREDITS.md).
- Протокол: [`docs/PROTOCOL.md`](docs/PROTOCOL.md), решения: [`docs/DECISIONS.md`](docs/DECISIONS.md), чек-лист вечера: [`docs/CHECKLIST.md`](docs/CHECKLIST.md).

## Состояние

- Этап 1 (ядро, модули 01 и 08) готов.
- Этап 2: прототип резьбы на `/carve` готов, ждёт проверки на iPad (решение «идём / не идём», см. `docs/DECISIONS.md`).
- Дальше: квиз (модуль 02).
