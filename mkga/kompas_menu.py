"""Пункты MKGA в меню самого КОМПАС (раздел «Приложения → Утилиты»).

Как это устроено. КОМПАС хранит набор подключённых приложений и утилит в файле конфигурации
`%APPDATA%\\ASCON\\KOMPAS-3D\\<версия>\\KOMPAS.kit.config` (UTF-16 XML). Утилита это строка
`<Utility path="..." displayName="..." params="..." description="..."/>`: так КОМПАС сам запускает «Калькулятор» и
редактор библиотек. Мы добавляем такие же строки для хаба и модов MKGA: это штатный механизм «Конфигуратора»
(Приложения → Конфигуратор → Структура → Утилита), мы лишь вносим те же записи без ручных кликов.

Правила («Не убий»):
- файл меняется только при ЗАКРЫТОМ КОМПАС (иначе КОМПАС перезапишет его при выходе, а мы могли бы повредить открытый файл);
- запись идёт через сессию отката `safe_io` (снимок, `python -m mkga undo`), оригинал не теряется;
- трогаются только наши строки (в описании метка `[mkga]`); чужие утилиты и приложения не меняются;
- убрать пункты можно командой `python -m mkga kompas-menu remove`.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence
from xml.etree import ElementTree as ET
from xml.sax.saxutils import quoteattr

from .core.safe_io import BackupStore, SafeIOError

MARK = "[mkga]"                         # метка в описании: так находим свои строки
_ROW = re.compile(r"[ \t]*<Utility\b[^>]*/>[ \t]*\r?\n?")
_UTILITY = re.compile(r"<Utility\b[^>]*/>")
_EMPTY_GROUPS = re.compile(r"<Groups\s*/>|<Groups>\s*</Groups>")
_ONLY_EMPTY_GROUP = re.compile(r"<Groups>\s*<Group>\s*</Group>\s*</Groups>")


class MenuError(SafeIOError):
    """Нельзя изменить меню КОМПАС (текст понятен пользователю)."""


@dataclass(frozen=True)
class MenuEntry:
    title: str                         # как называется пункт в меню КОМПАС
    path: str                          # исполняемый файл
    params: str = ""                   # параметры командной строки
    description: str = ""

    def xml(self) -> str:
        desc = f"{self.description} {MARK}".strip()
        return (f"<Utility path={quoteattr(self.path)} displayName={quoteattr(self.title)} "
                f"params={quoteattr(self.params)} description={quoteattr(desc)}/>")


# --- поиск файлов и состояния КОМПАС -----------------------------------------------------------------------
def kompas_config_dir(appdata: str | Path | None = None) -> Path:
    base = Path(appdata) if appdata else Path(os.environ.get("APPDATA", ""))
    return base / "ASCON" / "KOMPAS-3D"


def kit_configs(appdata: str | Path | None = None) -> dict[str, Path]:
    """Файлы конфигурации по версиям КОМПАС («24» -> путь), только существующие."""
    root = kompas_config_dir(appdata)
    found: dict[str, Path] = {}
    if root.is_dir():
        for d in sorted(root.iterdir()):
            f = d / "KOMPAS.kit.config"
            if d.is_dir() and d.name.isdigit() and f.is_file():
                found[d.name] = f
    return found


def is_kompas_running() -> bool:
    """Запущен ли KOMPAS.exe (только Windows; на других системах считаем, что нет)."""
    if os.name != "nt":
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq KOMPAS.exe", "/NH"], capture_output=True, text=True,
                             timeout=20, creationflags=0x08000000).stdout
    except (OSError, subprocess.SubprocessError):
        return True                    # не смогли проверить: безопаснее считать, что запущен
    return "KOMPAS.exe" in out


# --- чтение и правка текста ----------------------------------------------------------------------------------
def read_config(path: Path) -> str:
    raw = Path(path).read_bytes()
    if not raw.startswith(b"\xff\xfe"):
        raise MenuError(f"неожиданный формат {path}: ожидается UTF-16 с меткой порядка байтов, ничего не меняю")
    return raw[2:].decode("utf-16-le")


def encode_config(text: str) -> bytes:
    return b"\xff\xfe" + text.encode("utf-16-le")


def our_rows(text: str) -> list[str]:
    return [m.group(0) for m in _UTILITY.finditer(text) if MARK in m.group(0)]


def apply_entries(text: str, entries: Sequence[MenuEntry]) -> str:
    """Текст конфигурации, в котором наши строки заменены на `entries` (чужие строки не затронуты)."""
    cleaned = remove_entries(text)
    matches = list(_UTILITY.finditer(cleaned))
    new_rows = [e.xml() for e in entries]
    if not new_rows:
        return cleaned
    if matches:                        # после последней утилиты, в той же группе и с тем же отступом
        last = matches[-1]
        line_start = cleaned.rfind("\n", 0, last.start()) + 1
        indent = cleaned[line_start:last.start()]
        eol = "\r\n" if "\r\n" in cleaned else "\n"
        insert = "".join(f"{eol}{indent}{row}" for row in new_rows)
        return cleaned[:last.end()] + insert + cleaned[last.end():]
    eol = "\r\n" if "\r\n" in cleaned else "\n"
    empty = _EMPTY_GROUPS.search(cleaned)
    if empty:                          # КОМПАС v25: пользовательский файл пуст («<Groups/>»), создаём группу с нашими утилитами
        line_start = cleaned.rfind("\n", 0, empty.start()) + 1
        indent = cleaned[line_start:empty.start()]
        if indent.strip():
            indent = ""
        rows = "".join(f"{eol}{indent}\t\t{row}" for row in new_rows)
        block = f"<Groups>{eol}{indent}\t<Group>{rows}{eol}{indent}\t</Group>{eol}{indent}</Groups>"
        return cleaned[:empty.start()] + block + cleaned[empty.end():]
    close = cleaned.find("</Group>")
    if close != -1:                    # утилит в файле нет, но группы есть: в конец первой группы, с отступом её последней строки
        line_start = cleaned.rfind("\n", 0, close) + 1
        indent_close = cleaned[line_start:close]
        indent = (indent_close if not indent_close.strip() else "") + "\t"
        insert = "".join(f"{indent}{row}{eol}" for row in new_rows)
        return cleaned[:line_start] + insert + cleaned[line_start:]
    raise MenuError("в файле конфигурации нет групп для утилит: не знаю, куда вставлять пункты (формат отличается от проверенного)")


def remove_entries(text: str) -> str:
    """Убрать наши строки целиком (вместе с переводом строки); пустую группу, которую создали мы, свернуть обратно в «<Groups/>»."""
    def drop(m: re.Match) -> str:
        return "" if MARK in m.group(0) else m.group(0)
    removed = _ROW.sub(drop, text)
    if removed != text:
        removed = _ONLY_EMPTY_GROUP.sub("<Groups/>", removed)
    return removed


def _check_xml(text: str, path: Path) -> None:
    """Результат должен оставаться корректным XML: иначе файл не пишем."""
    try:
        ET.fromstring(encode_config(text))
    except ET.ParseError as e:
        raise MenuError(f"после правки {path.name} стал бы некорректным XML ({e}); ничего не изменено") from e


# --- состав пунктов ------------------------------------------------------------------------------------------------
def default_entries(exe: str | Path, mod_ids: Sequence[tuple[str, str]] = (), mods_dir: str | Path | None = None) -> list[MenuEntry]:
    """Пункт хаба и по пункту на каждый мод (id, название). `exe` это MKGA.exe собранной версии."""
    exe = str(Path(exe))
    extra = f'--mods-dir "{mods_dir}" ' if mods_dir else ""
    entries = [MenuEntry("MKGA: хаб модов", exe, "", "Каталог модов MKGA: найти, поставить и запустить мод")]
    for mod_id, name in mod_ids:
        entries.append(MenuEntry(f"MKGA: {name}", exe, f"{extra}run {mod_id}", f"Мод {mod_id}"))
    return entries


def find_exe(explicit: str | Path | None = None) -> Path | None:
    """MKGA.exe для пунктов меню: заданный, текущий (собранная версия) или собранный в build/dist."""
    import sys
    if explicit:
        return Path(explicit) if Path(explicit).is_file() else None
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    guess = Path(__file__).resolve().parent.parent / "build" / "dist" / "MKGA" / "MKGA.exe"
    return guess if guess.is_file() else None


def installed_entries(exe: str | Path, mods_dir: str | Path, custom_mods_dir: bool = False) -> list[MenuEntry]:
    """Пункты для хаба и всех установленных модов-приложений."""
    from .installer import list_installed
    mods = [(m.id, m.name) for m in list_installed(mods_dir) if m.kind == "app"]
    return default_entries(exe, mods, mods_dir if custom_mods_dir else None)


# --- действия ----------------------------------------------------------------------------------------------------------
@dataclass
class Report:
    version: str
    path: Path
    before: int                        # сколько наших строк было
    after: int                         # сколько стало
    changed: bool
    session_id: str | None = None


def status(version: str | None = None, appdata: str | Path | None = None) -> dict[str, int]:
    """Версия КОМПАС -> число наших пунктов в её конфигурации."""
    result = {}
    for ver, path in kit_configs(appdata).items():
        if version and ver != version:
            continue
        result[ver] = len(our_rows(read_config(path)))
    return result


def apply(entries: Sequence[MenuEntry], *, versions: Sequence[str] | None = None, appdata: str | Path | None = None,
          store: BackupStore | None = None, dry_run: bool = False,
          running: Callable[[], bool] = is_kompas_running) -> list[Report]:
    """Записать пункты в конфигурацию (пустой `entries` = убрать наши пункты)."""
    configs = {v: p for v, p in kit_configs(appdata).items() if not versions or v in versions}
    if not configs:
        raise MenuError("не найден файл KOMPAS.kit.config (КОМПАС ни разу не запускался под этим пользователем?)")
    if not dry_run and running():
        raise MenuError("КОМПАС запущен. Закройте его (сохранив работу) и повторите: иначе он перезапишет изменения при выходе")
    store = store or BackupStore()
    reports = []
    for ver, path in configs.items():
        text = read_config(path)
        new = apply_entries(text, entries)
        _check_xml(new, path)
        before, after = len(our_rows(text)), len(our_rows(new))
        changed = new != text
        sid = None
        if changed:
            with store.begin("mkga", f"Меню КОМПАС {ver}: " + ("пункты MKGA" if entries else "убрать пункты MKGA"),
                             dry_run=dry_run) as session:
                session.write_bytes(path, encode_config(new))
                sid = session.info.id
        reports.append(Report(ver, path, before, after, changed, None if dry_run else sid))
    return reports
