"""Реестр модов: список, который хаб читает из репозитория на GitHub.

Каждая запись закреплена за конкретным релизом и хешем архива. Новая запись
или обновление версии попадает в реестр только через pull request и проверку.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .manifest import ID_RE, ManifestError

REPO_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SCHEMA = 1


class RegistryError(ValueError):
    """Реестр некорректен."""


@dataclass(frozen=True)
class RegistryEntry:
    id: str
    name: str
    description: str
    repo: str          # "owner/name"
    tag: str           # тег релиза, например "v0.1.0"
    sha256: str        # хеш архива релиза
    tags: tuple[str, ...] = ()

    @property
    def asset_name(self) -> str:
        return f"{self.id}-{self.tag}.zip"

    @property
    def download_url(self) -> str:
        return f"https://github.com/{self.repo}/releases/download/{self.tag}/{self.asset_name}"


def parse_registry(data: Any) -> list[RegistryEntry]:
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise RegistryError(f"ожидается объект со schema = {SCHEMA}")
    mods = data.get("mods")
    if not isinstance(mods, list):
        raise RegistryError("поле mods должно быть списком")
    entries: list[RegistryEntry] = []
    seen: set[str] = set()
    for i, raw in enumerate(mods):
        where = f"mods[{i}]"
        if not isinstance(raw, dict):
            raise RegistryError(f"{where}: ожидается объект")
        for key in ("id", "name", "description", "repo", "tag", "sha256"):
            if not isinstance(raw.get(key), str) or not raw[key].strip():
                raise RegistryError(f"{where}: поле {key!r} обязательно")
        if not ID_RE.match(raw["id"]):
            raise RegistryError(f"{where}: некорректный id {raw['id']!r}")
        if raw["id"] in seen:
            raise RegistryError(f"{where}: повторяющийся id {raw['id']!r}")
        seen.add(raw["id"])
        if not REPO_RE.match(raw["repo"]):
            raise RegistryError(f"{where}: repo должен быть в виде owner/name")
        if not SHA256_RE.match(raw["sha256"]):
            raise RegistryError(f"{where}: sha256 — 64 символа hex в нижнем регистре")
        tags = raw.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise RegistryError(f"{where}: tags — список строк")
        entries.append(
            RegistryEntry(
                id=raw["id"], name=raw["name"].strip(), description=raw["description"].strip(),
                repo=raw["repo"], tag=raw["tag"], sha256=raw["sha256"], tags=tuple(tags),
            )
        )
    return entries


def load_registry(source: str | Path) -> list[RegistryEntry]:
    """Читает реестр из локального файла или по http(s)-ссылке."""
    s = str(source)
    if s.startswith(("http://", "https://")):
        with urllib.request.urlopen(s, timeout=20) as resp:  # noqa: S310 (URL задаёт пользователь/конфиг)
            text = resp.read().decode("utf-8")
    else:
        text = Path(s).read_text(encoding="utf-8")
    try:
        return parse_registry(json.loads(text))
    except json.JSONDecodeError as e:
        raise RegistryError(f"некорректный JSON: {e}") from e


def search(entries: Iterable[RegistryEntry], query: str) -> list[RegistryEntry]:
    """Поиск без учёта регистра по id, названию, описанию и тегам; все слова должны найтись."""
    words = query.lower().split()
    if not words:
        return list(entries)
    result = []
    for e in entries:
        haystack = " ".join((e.id, e.name, e.description, *e.tags)).lower()
        if all(w in haystack for w in words):
            result.append(e)
    return result
