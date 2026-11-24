"""Запуск мода: контекст и вызов run(ctx) из entry-файла."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .manifest import load_manifest


@dataclass
class ModContext:
    """Всё, что мод получает при запуске.

    kompas() подключается к КОМПАСу лениво, поэтому моды, которым КОМПАС не
    нужен (и тесты на Linux), работают без него.
    """

    mod_dir: Path
    data_dir: Path
    log: Callable[[str], None] = print
    connect: Callable[[], Any] | None = None
    _kompas: Any = field(default=None, init=False, repr=False)

    def kompas(self):
        if self._kompas is None:
            connect = self.connect
            if connect is None:
                from .core.kompas import connect as default_connect
                connect = default_connect
            self._kompas = connect()
        return self._kompas


def run_mod(mods_dir: str | Path, mod_id: str, ctx: ModContext | None = None) -> Any:
    mod_dir = Path(mods_dir) / mod_id
    manifest = load_manifest(mod_dir)
    if ctx is None:
        ctx = ModContext(mod_dir=mod_dir, data_dir=mod_dir.parent.parent / "data" / mod_id)
    ctx.data_dir.mkdir(parents=True, exist_ok=True)

    entry = mod_dir / manifest.entry
    module_name = f"mkga_mod_{manifest.id.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, entry)
    if spec is None or spec.loader is None:
        raise ImportError(f"не удалось загрузить {entry}")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(mod_dir))
    try:
        spec.loader.exec_module(module)
        run = getattr(module, "run", None)
        if not callable(run):
            raise AttributeError(f"{manifest.entry}: нет функции run(ctx)")
        return run(ctx)
    finally:
        try:
            sys.path.remove(str(mod_dir))
        except ValueError:
            pass
        sys.modules.pop(module_name, None)
