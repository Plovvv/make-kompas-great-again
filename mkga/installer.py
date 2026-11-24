"""Установка модов: проверка хеша, безопасная распаковка, список, удаление."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from .manifest import MANIFEST_NAME, Manifest, ManifestError, load_manifest
from .registry import RegistryEntry


class InstallError(RuntimeError):
    """Не удалось установить мод."""


def default_mods_dir() -> Path:
    """Папка установленных модов: %APPDATA%\\MKGA\\mods на Windows, ~/.local/share/mkga/mods иначе."""
    override = os.environ.get("MKGA_HOME")
    if override:
        return Path(override) / "mods"
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "MKGA" / "mods"


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: str | Path) -> None:
    if not url.startswith("https://"):
        raise InstallError("скачивание разрешено только по https")
    with urllib.request.urlopen(url, timeout=60) as resp, open(dest, "wb") as out:  # noqa: S310
        shutil.copyfileobj(resp, out)


def _safe_extract(zf: zipfile.ZipFile, target: Path) -> None:
    """Распаковка с защитой от выхода за пределы папки (zip-slip) и от ссылок."""
    root = target.resolve()
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        p = PurePosixPath(name)
        if p.is_absolute() or ".." in p.parts or (p.parts and ":" in p.parts[0]):
            raise InstallError(f"небезопасный путь в архиве: {info.filename!r}")
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise InstallError(f"символьные ссылки в архиве запрещены: {info.filename!r}")
        dest = (root / name).resolve()
        if root != dest and root not in dest.parents:
            raise InstallError(f"небезопасный путь в архиве: {info.filename!r}")
    zf.extractall(root)


def _find_mod_root(folder: Path) -> Path:
    if (folder / MANIFEST_NAME).is_file():
        return folder
    subdirs = [d for d in folder.iterdir() if d.is_dir()]
    if len(subdirs) == 1 and (subdirs[0] / MANIFEST_NAME).is_file():
        return subdirs[0]
    raise InstallError(f"в архиве нет {MANIFEST_NAME} (ни в корне, ни в единственной папке)")


def install_zip(
    zip_path: str | Path,
    mods_dir: str | Path,
    *,
    expected_id: str | None = None,
    expected_sha256: str | None = None,
) -> Manifest:
    """Ставит мод из zip в mods_dir/<id>. Старая версия заменяется целиком."""
    zip_path, mods_dir = Path(zip_path), Path(mods_dir)
    if expected_sha256 is not None and sha256_file(zip_path) != expected_sha256.lower():
        raise InstallError("хеш архива не совпал с реестром — установка отменена")
    mods_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=mods_dir, prefix=".tmp-") as tmp:
        tmp_path = Path(tmp)
        try:
            with zipfile.ZipFile(zip_path) as zf:
                _safe_extract(zf, tmp_path / "x")
        except zipfile.BadZipFile as e:
            raise InstallError("файл не является zip-архивом") from e
        mod_root = _find_mod_root(tmp_path / "x")
        try:
            manifest = load_manifest(mod_root)
        except ManifestError as e:
            raise InstallError(f"манифест: {e}") from e
        if expected_id is not None and manifest.id != expected_id:
            raise InstallError(f"id в манифесте ({manifest.id!r}) не совпал с ожидаемым ({expected_id!r})")
        if not (mod_root / manifest.entry).is_file():
            raise InstallError(f"entry {manifest.entry!r} отсутствует в архиве")
        final = mods_dir / manifest.id
        backup = None
        if final.exists():
            backup = tmp_path / "old"
            final.rename(backup)
        try:
            shutil.move(str(mod_root), str(final))
        except Exception:
            if backup is not None and not final.exists():
                backup.rename(final)
            raise
    return manifest


def install_from_registry(entry: RegistryEntry, mods_dir: str | Path) -> Manifest:
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / entry.asset_name
        download(entry.download_url, archive)
        return install_zip(archive, mods_dir, expected_id=entry.id, expected_sha256=entry.sha256)


def list_installed(mods_dir: str | Path) -> list[Manifest]:
    mods_dir = Path(mods_dir)
    if not mods_dir.is_dir():
        return []
    result = []
    for d in sorted(mods_dir.iterdir()):
        if d.is_dir() and not d.name.startswith(".") and (d / MANIFEST_NAME).is_file():
            try:
                result.append(load_manifest(d))
            except ManifestError:
                continue
    return result


def uninstall(mod_id: str, mods_dir: str | Path) -> bool:
    target = Path(mods_dir) / mod_id
    if not target.is_dir():
        return False
    if target.resolve().parent != Path(mods_dir).resolve():
        raise InstallError("недопустимый id")
    shutil.rmtree(target)
    return True
