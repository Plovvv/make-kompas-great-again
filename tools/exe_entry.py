"""Точка входа собранного exe (PyInstaller). Двойной щелчок без аргументов открывает окно хаба.

MKGA.exe      без консоли (окно хаба; запуск модов хабом тоже идёт этим файлом)
mkga-cli.exe  с консолью (все команды: pack, check, verify-registry, run, ...)
"""

import sys

from mkga.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or ["gui"]))
