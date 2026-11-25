"""Модель хаба без интерфейса: объединение каталога и установленных модов, поиск, история изменений.

Отдельно от окна, чтобы логику можно было проверять обычными тестами.
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass
from typing import Iterable

from .core.safe_io import COMMITTED, OPEN, ROLLED_BACK, UNDONE, BackupStore
from .manifest import Manifest
from .registry import RegistryEntry

AVAILABLE, INSTALLED, UPDATE, LOCAL = "available", "installed", "update", "local"

STATE_LABEL = {
    AVAILABLE: "Не установлен",
    INSTALLED: "Установлен",
    UPDATE: "Есть обновление",
    LOCAL: "Свой (не из каталога)",
}


# Что есть в собранной версии (exe): стандартная библиотека и эти пакеты. Остальное из `requires` манифеста недоступно.
BUNDLED_PACKAGES = {"pywin32"}


def missing_requirements(manifest: Manifest, frozen: bool | None = None) -> list[str]:
    """Пакеты из `requires` мода, которых нет в этой сборке. В исходниках (не exe) пакеты ставит сам пользователь: пусто."""
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if not frozen:
        return []
    out = []
    for requirement in manifest.requires:
        name = re.split(r"[<>=!~;\[ ]", requirement.strip(), maxsplit=1)[0].lower().replace("_", "-")
        if name and name not in BUNDLED_PACKAGES:
            out.append(requirement)
    return out


def parse_version(text: str) -> tuple[int, ...] | None:
    """«v1.2.3» или «1.2.3» -> (1, 2, 3); для непонятной строки None."""
    parts = text.strip().lstrip("vV").split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return None


@dataclass(frozen=True)
class ModRow:
    id: str
    name: str
    description: str
    tags: tuple[str, ...]
    state: str
    installed_version: str | None = None    # версия установленного мода
    latest_tag: str | None = None           # тег в каталоге (например «v0.2.0»)
    manifest: Manifest | None = None        # есть, если мод установлен
    entry: RegistryEntry | None = None      # есть, если мод есть в каталоге

    @property
    def state_label(self) -> str:
        return STATE_LABEL[self.state]

    @property
    def is_installed(self) -> bool:
        return self.manifest is not None

    @property
    def can_install(self) -> bool:
        """Установить или обновить можно только то, что есть в каталоге и ещё не актуально."""
        return self.entry is not None and self.state in (AVAILABLE, UPDATE)

    @property
    def version_text(self) -> str:
        if self.installed_version:
            return self.installed_version
        return (self.latest_tag or "").lstrip("vV")


def _state(entry: RegistryEntry | None, manifest: Manifest | None) -> str:
    if manifest is None:
        return AVAILABLE
    if entry is None:
        return LOCAL
    latest, have = parse_version(entry.tag), parse_version(manifest.version)
    if latest is not None and have is not None:
        return UPDATE if latest > have else INSTALLED
    return INSTALLED if entry.tag.lstrip("vV") == manifest.version else UPDATE


def build_rows(entries: Iterable[RegistryEntry], installed: Iterable[Manifest]) -> list[ModRow]:
    """Одна строка на мод: из каталога, установленный или то и другое. Сортировка по названию."""
    catalog = {e.id: e for e in entries}
    local = {m.id: m for m in installed}
    rows = []
    for mod_id in sorted(set(catalog) | set(local)):
        entry, manifest = catalog.get(mod_id), local.get(mod_id)
        rows.append(ModRow(
            id=mod_id,
            name=(manifest.name if manifest else entry.name),
            description=(manifest.description if manifest else entry.description),
            tags=tuple(manifest.tags if manifest and manifest.tags else (entry.tags if entry else ())),
            state=_state(entry, manifest),
            installed_version=manifest.version if manifest else None,
            latest_tag=entry.tag if entry else None,
            manifest=manifest,
            entry=entry,
        ))
    return sorted(rows, key=lambda r: r.name.lower())


def filter_rows(rows: Iterable[ModRow], query: str = "", only_installed: bool = False) -> list[ModRow]:
    """Поиск без учёта регистра по id, названию, описанию и тегам; все слова должны найтись."""
    words = query.lower().split()
    out = []
    for r in rows:
        if only_installed and not r.is_installed:
            continue
        haystack = " ".join((r.id, r.name, r.description, *r.tags)).lower()
        if all(w in haystack for w in words):
            out.append(r)
    return out


# --- история изменений файлов (откат) ------------------------------------------------------------

HISTORY_STATUS = {
    COMMITTED: "Применено",
    UNDONE: "Откачено",
    ROLLED_BACK: "Отменено из-за ошибки",
    OPEN: "Прервано",
}


@dataclass(frozen=True)
class HistoryRow:
    id: str
    when: str
    mod_id: str
    title: str
    status: str
    status_label: str
    files: int

    @property
    def can_undo(self) -> bool:
        """Откатить можно применённую и прерванную сессии."""
        return self.status in (COMMITTED, OPEN)


def history_rows(store: BackupStore) -> list[HistoryRow]:
    """Журнал изменений файлов модами, новые первыми."""
    return [
        HistoryRow(
            id=s.id,
            when=time.strftime("%d.%m.%Y %H:%M", time.localtime(s.created)),
            mod_id=s.mod_id,
            title=s.title,
            status=s.status,
            status_label=HISTORY_STATUS.get(s.status, s.status),
            files=len(s.operations),
        )
        for s in store.sessions()
    ]
