"""Настройки мода: маленький JSON-файл в папке данных мода (ctx.settings).

Это собственные данные MKGA (папка data_dir мода), а не файлы пользователя, поэтому пишутся
напрямую, но атомарно: сбой посреди записи не оставит полуфайла. Повреждённый файл не роняет
мод: он откладывается в `settings.json.corrupt`, а мод стартует с настройками по умолчанию.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable


class Settings:
    def __init__(self, path: str | Path, defaults: dict[str, Any] | None = None,
                 log: Callable[[str], None] = lambda _msg: None):
        self.path = Path(path)
        self.defaults = dict(defaults or {})
        self._log = log
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("ожидался объект JSON")
            self._data = data
        except (ValueError, OSError) as e:
            backup = self.path.with_name(self.path.name + ".corrupt")
            try:
                os.replace(self.path, backup)
            except OSError:
                pass
            self._log(f"Настройки повреждены ({e}); сохранены как {backup.name}, взяты значения по умолчанию.")
            self._data = {}

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._data:
            return self._data[key]
        if key in self.defaults:
            return self.defaults[key]
        return default

    def set(self, key: str, value: Any) -> None:
        """Записать значение и сразу сохранить на диск (значение должно сериализоваться в JSON)."""
        json.dumps(value)  # понятная ошибка до порчи состояния
        self._data[key] = value
        self._save()

    def reset(self) -> None:
        self._data = {}
        self._save()

    def as_dict(self) -> dict[str, Any]:
        return {**self.defaults, **self._data}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._data, ensure_ascii=False, indent=2).encode("utf-8")
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".settings-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
