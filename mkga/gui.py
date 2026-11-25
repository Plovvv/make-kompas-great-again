"""Окно хаба (запуск `python -m mkga gui`). Само окно: mkga/ui/hub.py."""

from __future__ import annotations

from pathlib import Path

from .ui.hub import run_hub


def launch(registry: str, mods_dir: Path) -> None:
    run_hub(registry, mods_dir)
