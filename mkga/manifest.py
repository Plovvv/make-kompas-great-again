"""Манифест мода (файл mkga-mod.json в корне мода) и его проверка."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

MANIFEST_NAME = "mkga-mod.json"

ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,38}[a-z0-9]$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
KINDS = ("app", "macro", "library")
MIN_KOMPAS_VERSION = 17  # с v17 (в т.ч. Home) доступны API и SDK

REQUIRED_KEYS = (
    "id", "name", "version", "description", "author", "license", "kind", "entry",
)


class ManifestError(ValueError):
    """Манифест некорректен."""


@dataclass(frozen=True)
class Manifest:
    id: str
    name: str
    version: str
    description: str
    author: str
    license: str
    kind: str
    entry: str
    kompas_versions: tuple[int, ...] = ()
    homepage: str = ""
    tags: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()  # pip-пакеты, например "pywin32"


def _check_entry(entry: str) -> None:
    if not entry or not isinstance(entry, str):
        raise ManifestError("entry: должен быть непустой строкой")
    p = PurePosixPath(entry.replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts or re.match(r"^[A-Za-z]:", entry):
        raise ManifestError(f"entry: недопустимый путь {entry!r}")
    if p.suffix != ".py":
        raise ManifestError("entry: ожидается .py-файл")


def parse_manifest(data: Any) -> Manifest:
    if not isinstance(data, dict):
        raise ManifestError("манифест должен быть JSON-объектом")
    for key in REQUIRED_KEYS:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ManifestError(f"поле {key!r} обязательно и должно быть непустой строкой")
    if not ID_RE.match(data["id"]):
        raise ManifestError(
            "id: латиница в нижнем регистре, цифры и дефис, 2–40 символов, "
            "начинается с буквы, не заканчивается дефисом"
        )
    if not SEMVER_RE.match(data["version"]):
        raise ManifestError("version: ожидается формат MAJOR.MINOR.PATCH")
    if data["kind"] not in KINDS:
        raise ManifestError(f"kind: одно из {', '.join(KINDS)}")
    _check_entry(data["entry"])

    versions = data.get("kompas_versions", [])
    if not isinstance(versions, list) or not all(
        isinstance(v, int) and not isinstance(v, bool) and v >= MIN_KOMPAS_VERSION
        for v in versions
    ):
        raise ManifestError(
            f"kompas_versions: список целых чисел не меньше {MIN_KOMPAS_VERSION}, например [22, 23, 24]"
        )
    for key in ("tags", "requires"):
        v = data.get(key, [])
        if not isinstance(v, list) or not all(isinstance(x, str) and x for x in v):
            raise ManifestError(f"{key}: ожидается список строк")

    return Manifest(
        id=data["id"],
        name=data["name"].strip(),
        version=data["version"],
        description=data["description"].strip(),
        author=data["author"].strip(),
        license=data["license"].strip(),
        kind=data["kind"],
        entry=data["entry"].replace("\\", "/"),
        kompas_versions=tuple(versions),
        homepage=str(data.get("homepage", "")),
        tags=tuple(data.get("tags", [])),
        requires=tuple(data.get("requires", [])),
    )


def load_manifest(path: str | Path) -> Manifest:
    """Читает манифест из файла или из папки мода."""
    p = Path(path)
    if p.is_dir():
        p = p / MANIFEST_NAME
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ManifestError(f"не найден {p}") from e
    except json.JSONDecodeError as e:
        raise ManifestError(f"{p}: некорректный JSON: {e}") from e
    return parse_manifest(data)
