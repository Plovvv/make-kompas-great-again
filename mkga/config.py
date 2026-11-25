"""Настройки хаба."""

from __future__ import annotations

import os
from pathlib import Path

# Реестр модов в репозитории проекта на GitHub (новые моды попадают в него через pull request).
DEFAULT_REGISTRY_URL = "https://raw.githubusercontent.com/Plovvv/make-kompas-great-again/main/registry/registry.json"

_LOCAL_REGISTRY = Path(__file__).resolve().parent.parent / "registry" / "registry.json"


def registry_source(cli_value: str | None = None) -> str:
    """Откуда читать реестр: флаг --registry, переменная MKGA_REGISTRY, ссылка по умолчанию, локальный файл."""
    if cli_value:
        return cli_value
    env = os.environ.get("MKGA_REGISTRY")
    if env:
        return env
    if DEFAULT_REGISTRY_URL:
        return DEFAULT_REGISTRY_URL
    return str(_LOCAL_REGISTRY)
