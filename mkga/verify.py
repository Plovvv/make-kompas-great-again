"""Проверка релизов модов по записям реестра (для CI pull request и для рецензента).

Для каждой записи скачивается архив релиза и проверяется:
  * хеш совпадает с записью (код не подменили после проверки);
  * архив безопасен (пути, ссылки, размер), манифест корректен, `id` и версия совпадают с записью;
  * страж правил (`mkga check`): мод не пишет файлы и не сохраняет документы в обход `ctx.session`;
  * имя и описание в реестре совпадают с манифестом (предупреждение).

Проверка НЕ выполняет код мода: страж разбирает исходники как текст. Но он ловит только случайные ошибки,
не злой умысел, поэтому новый мод обязательно читает человек перед слиянием.
"""

from __future__ import annotations

import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .guard import check_path, violations
from .installer import InstallError, _find_mod_root, _safe_extract, download, sha256_file
from .manifest import ManifestError, load_manifest
from .registry import RegistryEntry, load_registry


@dataclass
class Report:
    entry: RegistryEntry
    problems: list[str] = field(default_factory=list)   # из-за них запись нельзя принимать
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def verify_archive(archive: str | Path, entry: RegistryEntry) -> Report:
    """Проверить локальный архив против записи реестра."""
    report = Report(entry)
    archive = Path(archive)
    got = sha256_file(archive)
    if got != entry.sha256:
        report.problems.append(f"хеш архива {got[:12]}… не совпал с реестром {entry.sha256[:12]}…")
        return report  # дальше доверять содержимому нельзя
    with tempfile.TemporaryDirectory() as tmp:
        try:
            with zipfile.ZipFile(archive) as zf:
                _safe_extract(zf, Path(tmp) / "x")
            root = _find_mod_root(Path(tmp) / "x")
            manifest = load_manifest(root)
        except zipfile.BadZipFile:
            report.problems.append("файл не является zip-архивом")
            return report
        except (InstallError, ManifestError) as e:
            report.problems.append(str(e))
            return report
        if manifest.id != entry.id:
            report.problems.append(f"id в манифесте ({manifest.id!r}) не совпал с реестром ({entry.id!r})")
        tag_version = entry.tag.lstrip("vV")
        if manifest.version != tag_version:
            report.problems.append(f"версия в манифесте ({manifest.version}) не совпала с тегом ({entry.tag})")
        if not (root / manifest.entry).is_file():
            report.problems.append(f"entry {manifest.entry!r} отсутствует в архиве")
        for f in violations(check_path(root)):
            report.problems.append(f"страж правил: {f}")
        if manifest.name != entry.name:
            report.warnings.append(f"название в реестре ({entry.name!r}) отличается от манифеста ({manifest.name!r})")
        if manifest.description != entry.description:
            report.warnings.append("описание в реестре отличается от манифеста")
    return report


def verify_entry(entry: RegistryEntry, fetch: Callable[[str, Path], None] = download) -> Report:
    """Скачать архив релиза записи (по адресу из реестра) и проверить его."""
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / entry.asset_name
        try:
            fetch(entry.download_url, archive)
        except Exception as e:  # noqa: BLE001  сеть, 404 и т.д. это проблема записи, а не падение проверки
            report = Report(entry)
            report.problems.append(f"не удалось скачать {entry.download_url}: {e}")
            return report
        return verify_archive(archive, entry)


def verify_registry(source: str | Path, only: set[str] | None = None,
                    fetch: Callable[[str, Path], None] = download) -> list[Report]:
    """Проверить все записи реестра (или только указанные id)."""
    entries = load_registry(source)
    return [verify_entry(e, fetch) for e in entries if not only or e.id in only]
