# AGENTS.md

Инструкции для ИИ-агентов, работающих с этим репозиторием (Claude Code, Codex, Cursor и другие).

**Главный файл: [CLAUDE.md](CLAUDE.md).** Там карта проекта, команды, правила работы и текущий статус. Прочитайте его
первым. Дальше по задаче:

| Что делаете | Читайте |
|---|---|
| Любое изменение | [docs/PRINCIPLES.md](docs/PRINCIPLES.md) (правила, которые проверяются кодом) и [docs/ROADMAP.md](docs/ROADMAP.md) |
| Мод | [docs/WRITING_MODS.md](docs/WRITING_MODS.md) |
| 3D-построение, API КОМПАС | [docs/MODEL3D.md](docs/MODEL3D.md), `python tools/inspect_api.py find|show` |
| Интерфейс | [docs/UI_STYLE.md](docs/UI_STYLE.md) |
| Проверка на КОМПАС | [docs/VERIFICATION.md](docs/VERIFICATION.md), [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md) |

Коротко, чего нельзя:

1. Писать, удалять и сохранять файлы пользователя и документы КОМПАС в обход `ctx.session` / `Kompas.save_as`.
2. Утверждать, что что-то работает, без проверки: на фейковом КОМПАС (`mkga.core.fake`) и, если затронут КОМПАС, живым
   тестом с расчётом. Что не проверено, помечайте «не проверено».
3. Добавлять зависимости для пользователя, сетевые вызовы во время работы мода, данные и модели АСКОН.
4. Менять документы пользователя через 3D-слой (он создаёт только свои документы) и закрывать чужие документы.

Перед завершением: `python -m unittest discover -s tests -t .`, `python -m mkga check mods`, обновите документацию.
