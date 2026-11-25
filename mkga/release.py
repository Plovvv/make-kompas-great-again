"""Сборка релиза мода: воспроизводимый zip, хеш и запись для реестра.

    python -m mkga pack mods/my-mod --tag v0.2.0 --repo owner/my-mod

Результат `dist/<id>-<тег>.zip` кладётся в релиз на GitHub под ЭТИМ ЖЕ именем (так хаб строит ссылку), а хеш и
запись для `registry/registry.json` печатаются в консоль. Архив воспроизводим: тот же код даёт тот же файл и
тот же хеш (отсортированные пути, фиксированное время, одинаковое сжатие), поэтому хеш можно проверить
независимо.

Перед сборкой всегда проверяются манифест и страж правил (`mkga check`): мод, который пишет файлы в обход
`ctx.session`, не собирается.
"""

from __future__ import annotations

import json
import os
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .guard import check_path, violations
from .installer import sha256_file
from .manifest import Manifest, ManifestError, load_manifest
from .registry import REPO_RE, RegistryError, parse_registry

# Что не попадает в релиз: служебное, кэши и тесты (код мода от них не зависит).
EXCLUDED_DIRS = {"__pycache__", ".git", ".github", ".idea", ".vscode", ".venv", "venv", "tests", "dist", "build",
                 ".mypy_cache", ".pytest_cache", "node_modules"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".orig", ".rej", ".swp", ".tmp"}
EXCLUDED_NAMES = {".DS_Store", "Thumbs.db", ".gitignore", ".gitattributes"}
MAX_BYTES = 50 * 1024 * 1024        # предел размера всех файлов мода (до сжатия)
_FIXED_TIME = (1980, 1, 1, 0, 0, 0)  # формат zip не хранит время раньше 1980


class ReleaseError(RuntimeError):
    """Мод нельзя выпустить: понятная причина в тексте."""


@dataclass(frozen=True)
class ReleaseInfo:
    path: Path          # собранный архив
    manifest: Manifest
    tag: str
    sha256: str
    size: int           # размер архива, байт
    files: int          # файлов внутри


def _version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(p) for p in text.lstrip("vV").split("."))


def collect_files(mod_dir: Path) -> list[Path]:
    """Файлы мода для релиза, отсортированные по относительному пути."""
    out: list[Path] = []
    root = mod_dir.resolve()
    for current, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIRS)
        for name in sorted(names):
            p = Path(current) / name
            if name in EXCLUDED_NAMES or p.suffix in EXCLUDED_SUFFIXES:
                continue
            if p.is_symlink():
                raise ReleaseError(f"символьные ссылки в моде запрещены: {p.relative_to(root)}")
            out.append(p)
    return sorted(out, key=lambda p: p.relative_to(root).as_posix())


def build_release(mod_dir: str | Path, out_dir: str | Path = "dist", tag: str | None = None) -> ReleaseInfo:
    """Собрать релиз мода из папки. Тег по умолчанию `v<версия из манифеста>`."""
    mod_dir, out_dir = Path(mod_dir), Path(out_dir)
    try:
        manifest = load_manifest(mod_dir)
    except ManifestError as e:
        raise ReleaseError(f"манифест: {e}") from e
    except FileNotFoundError as e:
        raise ReleaseError(f"в папке {mod_dir} нет mkga-mod.json") from e

    tag = tag or f"v{manifest.version}"
    try:
        tag_ok = _version_tuple(tag) == _version_tuple(manifest.version)
    except ValueError:
        tag_ok = False
    if not tag_ok:
        raise ReleaseError(f"тег {tag!r} не соответствует версии в манифесте ({manifest.version}): "
                           f"ожидается v{manifest.version}")
    if not (mod_dir / manifest.entry).is_file():
        raise ReleaseError(f"entry {manifest.entry!r} отсутствует в папке мода")

    bad = violations(check_path(mod_dir))
    if bad:
        lines = "\n".join(f"  {f}" for f in bad)
        raise ReleaseError("мод пишет файлы или сохраняет документы в обход ctx.session "
                           f"(правила проекта, п. 1):\n{lines}")

    files = collect_files(mod_dir)
    total = sum(p.stat().st_size for p in files)
    if total > MAX_BYTES:
        raise ReleaseError(f"мод слишком большой: {total / 1048576:.1f} МБ при пределе {MAX_BYTES // 1048576} МБ")

    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / f"{manifest.id}-{tag}.zip"  # имя, по которому хаб строит ссылку на релиз
    root = mod_dir.resolve()
    fd, tmp_name = tempfile.mkstemp(dir=out_dir, prefix=".pack-", suffix=".tmp")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp_name, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for p in files:
                info = zipfile.ZipInfo(p.relative_to(root).as_posix(), date_time=_FIXED_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                info.create_system = 3  # одинаково на любой ОС (иначе хеш зависел бы от системы сборки)
                zf.writestr(info, p.read_bytes(), compresslevel=9)
        os.replace(tmp_name, archive)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return ReleaseInfo(path=archive, manifest=manifest, tag=tag, sha256=sha256_file(archive),
                       size=archive.stat().st_size, files=len(files))


def registry_entry(info: ReleaseInfo, repo: str) -> dict:
    """Запись для registry/registry.json (repo в виде owner/name)."""
    if not REPO_RE.match(repo):
        raise ReleaseError("repo должен быть в виде owner/name")
    m = info.manifest
    return {"id": m.id, "name": m.name, "description": m.description, "repo": repo, "tag": info.tag,
            "sha256": info.sha256, "tags": list(m.tags)}


def add_to_registry(registry_path: str | Path, entry: dict) -> str:
    """Добавить или обновить запись в registry.json. Возвращает «добавлено» или «обновлено»."""
    path = Path(registry_path)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"schema": 1, "mods": []}
    mods = [m for m in data.get("mods", []) if m.get("id") != entry["id"]]
    action = "обновлено" if len(mods) != len(data.get("mods", [])) else "добавлено"
    mods.append(entry)
    data["mods"] = sorted(mods, key=lambda m: m["id"])
    try:
        parse_registry(data)  # реестр должен остаться корректным
    except RegistryError as e:
        raise ReleaseError(f"запись не прошла проверку реестра: {e}") from e
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".registry-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    return action
