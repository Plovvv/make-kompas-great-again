# -*- mode: python ; coding: utf-8 -*-
# Спецификация PyInstaller для MKGA. Запускается скриптом tools/build_exe.py, вручную не нужна.
#
# Два exe в одной папке (общие библиотеки):
#   MKGA.exe      без консоли: окно хаба (двойной щелчок); им же хаб запускает моды отдельными процессами
#   mkga-cli.exe  с консолью: все команды (pack, check, verify-registry, run, ...)
#
# Моды это Python-код, который загружается из папки пользователя во время работы, а не при сборке. PyInstaller
# не видит, что они импортируют, поэтому в сборку включена ВСЯ стандартная библиотека (кроме тестов и
# инструментов разработки) и pywin32: так любой мод, которому хватает стандартной библиотеки, работает в exe.
# Сторонние пакеты из `requires` манифеста в exe недоступны.
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent
BUILD = ROOT / "build"

_EXCLUDED_STDLIB = {"test", "idlelib", "turtledemo", "lib2to3", "ensurepip", "distutils", "pydoc_data", "tkinter.test"}
# модули, которых нет в Windows (иначе в журнале сборки шумные ошибки «не найден»)
_NOT_ON_WINDOWS = {"syslog", "grp", "pwd", "termios", "fcntl", "resource", "nis", "spwd", "crypt", "ossaudiodev",
                   "readline", "tzdata"}
stdlib = sorted(m for m in sys.stdlib_module_names
                if m not in _EXCLUDED_STDLIB and m not in _NOT_ON_WINDOWS and not m.startswith("_"))
# Весь пакет mkga целиком: моды импортируют mkga.core.model3d, mkga.ui.window и т.п. во время работы, а PyInstaller
# включает только то, что видит в коде хаба (проверено: без этого `from mkga.core.model3d import Part` в exe падает).
mkga_modules = collect_submodules("mkga")
pywin32 = ["pythoncom", "pywintypes", "win32api", "win32con", "win32com", "win32com.client",
           "win32com.client.dynamic", "win32com.client.gencache", "winreg"]

a = Analysis(
    [str(ROOT / "tools" / "exe_entry.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=stdlib + pywin32 + mkga_modules,
    excludes=sorted(_EXCLUDED_STDLIB) + ["PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)

icon = str(BUILD / "mkga.ico")
version = str(BUILD / "version_info.txt")

gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name="MKGA", console=False, icon=icon, version=version,
          debug=False, strip=False, upx=False)
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name="mkga-cli", console=True, icon=icon, version=version,
          debug=False, strip=False, upx=False)
coll = COLLECT(gui, cli, a.binaries, a.datas, strip=False, upx=False, name="MKGA")
