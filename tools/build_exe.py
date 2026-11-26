"""Сборка exe хаба MKGA (Windows): папка с MKGA.exe и mkga-cli.exe и zip для раздачи.

    python tools/build_exe.py            # собрать и проверить
    python tools/build_exe.py --no-smoke # без проверки собранного
    python tools/build_exe.py --clean    # пересоздать окружение сборки

Всё нужное для сборки (PyInstaller, pywin32) ставится в ИЗОЛИРОВАННОЕ окружение build/venv внутри проекта,
системный Python не затрагивается. Результат: build/dist/MKGA/ и build/MKGA-<версия>-windows.zip.
Пользователю собранного exe Python не нужен.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
VENV = BUILD / "venv"
DIST = BUILD / "dist"
BUNDLED_MODS = ("components",)        # моды из папки mods/, которые кладутся в поставку (bundled/) и ставятся без сети
sys.path.insert(0, str(ROOT))

from mkga import __version__  # noqa: E402
from mkga.console import ensure_utf8_output  # noqa: E402


def run(cmd: list[str], **kw) -> None:
    print("  $", " ".join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def ensure_venv(clean: bool) -> Path:
    if clean and VENV.exists():
        print("Удаляю старое окружение сборки…")
        shutil.rmtree(VENV)
    if not venv_python().exists():
        print("Создаю изолированное окружение сборки:", VENV)
        run([sys.executable, "-m", "venv", VENV])
    py = venv_python()
    print("Устанавливаю инструменты сборки (PyInstaller, pywin32) в окружение сборки…")
    run([py, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", ROOT / "tools" / "build-requirements.txt"])
    return py


def write_version_file() -> Path:
    """Свойства файла exe (вкладка «Подробно»): версия, описание, лицензия."""
    parts = [int(p) for p in __version__.split(".")] + [0, 0, 0]
    v = tuple(parts[:4])
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'MKGA contributors'),
      StringStruct('FileDescription', 'MKGA: unofficial mod hub for KOMPAS-3D'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('InternalName', 'mkga'),
      StringStruct('LegalCopyright', 'MIT License. Not affiliated with ASCON.'),
      StringStruct('OriginalFilename', 'MKGA.exe'),
      StringStruct('ProductName', 'MAKE KOMPAS GREAT AGAIN'),
      StringStruct('ProductVersion', '{__version__}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ])
"""
    path = BUILD / "version_info.txt"
    path.write_text(text, encoding="utf-8")
    return path


def build(clean: bool) -> Path:
    BUILD.mkdir(exist_ok=True)
    py = ensure_venv(clean)
    from mkga.ui.icon import write_ico
    print("Рисую иконку:", write_ico(BUILD / "mkga.ico"))
    write_version_file()
    if DIST.exists():
        shutil.rmtree(DIST)
    print("Собираю exe (несколько минут)…")
    run([py, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", DIST, "--workpath", BUILD / "work",
         ROOT / "tools" / "mkga.spec"], cwd=ROOT)
    folder = DIST / "MKGA"
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT / name, folder / name)
    from mkga.bundled import write_bundle
    bundled = write_bundle([ROOT / "mods" / name for name in BUNDLED_MODS], folder / "bundled")
    print("Моды в поставке:", ", ".join(f"{b.id} {b.version}" for b in bundled))
    (folder / "README.txt").write_text(
        "MKGA (MAKE KOMPAS GREAT AGAIN): неофициальный хаб модов для КОМПАС-3D. Проект не связан с АСКОН.\n\n"
        "Запуск: MKGA.exe (окно хаба). Python устанавливать не нужно. КОМПАС-3D должен быть установлен\n"
        "и запущен, когда вы запускаете моды. Мод «Каталог комплектующих» входит в поставку: в хабе откройте\n"
        "«Каталог» и нажмите «Установить».\n"
        "Команды (сборка и проверка модов и т.д.): mkga-cli.exe --help\n"
        "Моды и их данные хранятся в %APPDATA%\\MKGA. Удалить программу: удалить эту папку.\n"
        "Исходный код и документация: https://github.com/Plovvv/make-kompas-great-again\n",
        encoding="utf-8")
    return folder


def zip_folder(folder: Path) -> Path:
    archive = BUILD / f"MKGA-{__version__}-windows.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                zf.write(p, Path("MKGA") / p.relative_to(folder))
    return archive


def clean_env() -> dict[str, str]:
    """Окружение «чужого» компьютера: в PATH нет Python, MKGA_HOME во временной папке."""
    keep = {k: v for k, v in os.environ.items() if k.upper() in ("SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP",
                                                                  "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PATHEXT")}
    keep["PATH"] = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    return keep


def smoke(folder: Path) -> None:
    """Проверить собранное в окружении без Python: версия, страж, сборка мода, установка и запуск мода, окно хаба."""
    cli, gui = folder / "mkga-cli.exe", folder / "MKGA.exe"
    tmp = Path(tempfile.mkdtemp(prefix="mkga-smoke-"))
    env = clean_env()
    env["MKGA_HOME"] = str(tmp / "home")
    print("\nПроверка собранного (в PATH нет Python):")

    def cli_run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run([str(cli), *args], env=env, capture_output=True, text=True, encoding="utf-8", cwd=tmp)

    r = cli_run("--version")
    assert r.returncode == 0 and __version__ in r.stdout, r.stdout + r.stderr
    print("  ✓ версия:", r.stdout.strip())

    r = cli_run("check", str(ROOT / "mods"))
    assert r.returncode == 0, r.stdout + r.stderr
    print("  ✓ страж правил:", r.stdout.strip().splitlines()[-1])

    r = cli_run("pack", str(ROOT / "mods" / "_template"), "--out", str(tmp / "dist"))
    assert r.returncode == 0, r.stdout + r.stderr
    archive = tmp / "dist" / "hello-kompas-v0.1.0.zip"
    assert archive.exists(), r.stdout
    print("  ✓ сборка релиза мода:", archive.name)

    r = cli_run("install-zip", str(archive))
    assert r.returncode == 0, r.stdout + r.stderr
    print("  ✓ установка мода из архива")

    r = cli_run("run", "hello-kompas", "--fake-kompas")
    assert r.returncode == 0 and "Фейковый документ.m3d" in r.stdout, r.stdout + r.stderr
    print("  ✓ запуск мода (мод загружен из папки пользователя, Python на машине не нужен)")

    # мод, который импортирует ВСЕ модули mkga, доступные модам (PyInstaller сам их не видит) и строит деталь на фейке
    mod = tmp / "home" / "mods" / "import-check"
    mod.mkdir(parents=True)
    (mod / "mkga-mod.json").write_text(
        '{"id": "import-check", "name": "Import check", "version": "0.1.0", "description": "d", "author": "a", '
        '"license": "MIT", "kind": "macro", "entry": "main.py"}', encoding="utf-8")
    (mod / "main.py").write_text(
        "import importlib, pkgutil, zoneinfo, mkga\n"
        "from mkga.core.model3d import Part\n"
        "def run(ctx):\n"
        "    names = [m.name for m in pkgutil.walk_packages(mkga.__path__, 'mkga.')\n"
        "             if not m.name.startswith(('mkga.ui.demo',)) or True]\n"
        "    for n in names:\n"
        "        importlib.import_module(n)\n"
        "    with Part.new(ctx.kompas()) as part:\n"
        "        with part.sketch('XOY') as sk:\n"
        "            sk.circle(0, 0, 5)\n"
        "        part.extrude(sk, 10)\n"
        "    ctx.log(f'импортировано модулей mkga: {len(names)}, деталь на фейке построена, zoneinfo есть')\n",
        encoding="utf-8")
    r = cli_run("run", "import-check", "--fake-kompas", "--yes")
    assert r.returncode == 0 and "импортировано модулей mkga" in r.stdout, r.stdout + r.stderr
    print("  ✓", r.stdout.strip().splitlines()[-1])

    # окно хаба: запускается и живёт
    proc = subprocess.Popen([str(gui)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(8)
    alive = proc.poll() is None
    proc.kill()
    assert alive, "MKGA.exe завершился сразу после запуска"
    print("  ✓ окно хаба запускается (MKGA.exe)")
    r = cli_run("--registry", str(tmp / "нет-реестра.json"), "install", BUNDLED_MODS[0])
    assert r.returncode == 0 and "Установлено" in r.stdout, r.stdout + r.stderr
    assert BUNDLED_MODS[0] in cli_run("list").stdout
    print("  ✓ мод из поставки ставится без сети и без реестра")
    shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ensure_utf8_output()  # вывод в трубу (CI, запуск из другой программы) не должен падать на русском и на галочках
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clean", action="store_true", help="пересоздать окружение сборки")
    ap.add_argument("--no-smoke", action="store_true", help="не проверять собранное")
    args = ap.parse_args()
    if os.name != "nt":
        print("Сборка exe поддерживается только в Windows.", file=sys.stderr)
        return 2
    folder = build(args.clean)
    if not args.no_smoke:
        smoke(folder)
    archive = zip_folder(folder)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    size = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
    print(f"\nГотово: {folder}  ({size / 1048576:.1f} МБ распакованно)")
    print(f"Архив:  {archive}  ({archive.stat().st_size / 1048576:.1f} МБ)")
    print(f"sha256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
