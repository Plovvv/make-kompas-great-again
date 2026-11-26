"""Моды «в поставке»: архивы модов лежат рядом с exe (папка `bundled`), поэтому хаб ставит их без сети и без реестра.

Зачем: реестр на GitHub может быть недоступен или пуст, а первый запуск не должен упираться в «каталог пуст». Состав
поставки описывает `bundled/index.json` (его пишет `tools/build_exe.py`):

    {"schema": 1, "mods": [{"id", "name", "description", "version", "tags", "file", "sha256"}]}

Перед установкой хеш файла сверяется с индексом, а `install_zip` дополнительно проверяет манифест, защиту от zip-slip и
совпадение id. Поставляемый мод ставится так же, как мод из каталога, и так же откатывается удалением.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .installer import sha256_file
from .registry import RegistryEntry

BUNDLED_REPO = "local/bundled"      # «репозиторий» записи каталога для моды из поставки (скачивания нет)
INDEX_NAME = "index.json"


@dataclass(frozen=True)
class BundledMod:
    id: str
    name: str
    description: str
    version: str
    tags: tuple[str, ...]
    path: Path
    sha256: str

    @property
    def tag(self) -> str:
        return f"v{self.version}"

    def entry(self) -> RegistryEntry:
        """Запись для каталога хаба: тот же вид, что у мода из реестра, но с репозиторием-заглушкой."""
        return RegistryEntry(self.id, self.name, self.description, BUNDLED_REPO, self.tag, self.sha256, self.tags)


def bundled_dir() -> Path | None:
    """Папка с поставляемыми модами: MKGA_BUNDLED, иначе `bundled` рядом с exe (в исходниках по умолчанию нет)."""
    override = os.environ.get("MKGA_BUNDLED")
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "bundled"
    return None


def load_bundled(directory: str | Path | None = None) -> tuple[list[BundledMod], list[str]]:
    """Прочитать индекс поставки. Возвращает (моды, замечания); повреждённая запись пропускается, а не роняет хаб."""
    directory = bundled_dir() if directory is None else Path(directory)
    if directory is None or not (directory / INDEX_NAME).is_file():
        return [], []
    problems: list[str] = []
    try:
        data = json.loads((directory / INDEX_NAME).read_text(encoding="utf-8-sig"))
        items = data["mods"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        return [], [f"{INDEX_NAME}: не удалось прочитать ({e})"]
    mods = []
    for item in items:
        try:
            path = directory / item["file"]
            if path.resolve().parent != directory.resolve():
                raise ValueError("файл вне папки поставки")
            if not path.is_file():
                raise ValueError("файла нет")
            if sha256_file(path) != str(item["sha256"]).lower():
                raise ValueError("хеш файла не совпал с индексом")
            mods.append(BundledMod(item["id"], item["name"], item["description"], str(item["version"]),
                                   tuple(item.get("tags", ())), path, str(item["sha256"]).lower()))
        except (KeyError, TypeError, ValueError) as e:
            problems.append(f"мод из поставки {item.get('id', '?') if isinstance(item, dict) else '?'}: {e}")
    return mods, problems


def _version(text: str) -> tuple[int, ...]:
    parts = text.strip().lstrip("vV").split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return ()


def merge_entries(entries: Iterable[RegistryEntry], bundled: Sequence[BundledMod]) -> list[RegistryEntry]:
    """Записи каталога плюс моды из поставки: при одинаковом id остаётся более новая версия (при равной каталог)."""
    result = {e.id: e for e in entries}
    for b in bundled:
        current = result.get(b.id)
        if current is None or _version(b.version) > _version(current.tag):
            result[b.id] = b.entry()
    return list(result.values())


def bundled_by_id(bundled: Sequence[BundledMod]) -> dict[str, BundledMod]:
    return {b.id: b for b in bundled}


def write_bundle(mod_dirs: Sequence[Path], out_dir: Path) -> list[BundledMod]:
    """Собрать архивы модов в `out_dir` и записать индекс (используется при сборке exe)."""
    from .release import build_release

    out_dir.mkdir(parents=True, exist_ok=True)
    mods = []
    for mod_dir in mod_dirs:
        info = build_release(mod_dir, out_dir)
        m = info.manifest
        mods.append(BundledMod(m.id, m.name, m.description, m.version, tuple(m.tags), info.path, info.sha256))
    index = {"schema": 1, "mods": [{"id": b.id, "name": b.name, "description": b.description, "version": b.version,
                                    "tags": list(b.tags), "file": b.path.name, "sha256": b.sha256} for b in mods]}
    (out_dir / INDEX_NAME).write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return mods
