"""Запуск мода ОТДЕЛЬНЫМ ПРОЦЕССОМ (PRINCIPLES, п. 1.8: сбой одного мода не роняет хаб и другие моды).

Хаб не выполняет код модов у себя: окно мода это самостоятельный процесс `python -m mkga run <id>`,
а его вывод читается построчно и попадает в журнал хаба. Закрытие хаба моды не закрывает.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

_CREATE_NO_WINDOW = 0x08000000  # не показывать окно консоли у дочернего python.exe на Windows


def mod_command(mods_dir: str | Path, mod_id: str) -> list[str]:
    """Команда запуска установленного мода (для исходников и для собранного exe)."""
    base = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "mkga"]
    return [*base, "--mods-dir", str(mods_dir), "run", mod_id]


def start_mod(
    mods_dir: str | Path,
    mod_id: str,
    on_line: Callable[[str], None],
    on_exit: Callable[[int], None],
) -> subprocess.Popen:
    """Запустить мод и вернуть процесс. on_line и on_exit вызываются из служебного потока."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    if not getattr(sys, "frozen", False):
        # запуск из исходников: дочерний процесс должен найти пакет mkga
        package_parent = str(Path(__file__).resolve().parent.parent)
        env["PYTHONPATH"] = package_parent + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.Popen(  # noqa: S603  (команда собрана из sys.executable и проверенного id)
        mod_command(mods_dir, mod_id), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, creationflags=_CREATE_NO_WINDOW if os.name == "nt" else 0,
    )

    def pump() -> None:
        assert proc.stdout is not None
        try:
            for raw in proc.stdout:
                on_line(raw.decode("utf-8", "replace").rstrip("\r\n"))
        finally:
            proc.stdout.close()
        on_exit(proc.wait())

    threading.Thread(target=pump, daemon=True).start()
    return proc
