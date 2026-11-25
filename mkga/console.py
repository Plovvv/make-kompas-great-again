"""Вывод в консоль и в трубы без падений на русском тексте.

В обычном окне терминала Python печатает юникод правильно. Но когда вывод перенаправлен (труба, файл,
CI, запуск модов хабом), на Windows используется кодировка системы (cp1252, cp1251) и русские буквы
вызывают UnicodeEncodeError. Поэтому для перенаправленного вывода включается UTF-8.
"""

from __future__ import annotations

import os
import sys


def ensure_utf8_output() -> None:
    """Включить UTF-8 для stdout/stderr, если они перенаправлены (не терминал). Безопасно вызывать много раз.

    Если потока нет вообще (exe без консоли запущен двойным щелчком), подставляется «чёрная дыра»:
    иначе print и argparse падали бы при попытке написать в None.
    """
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115  (живёт до конца процесса)
    for stream in (sys.stdout, sys.stderr):
        if stream is None or stream.isatty():
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # подменённый поток (тесты) или уже закрыт
            pass
