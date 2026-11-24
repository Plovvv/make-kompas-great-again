"""Командная строка: python -m mkga <команда>."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import registry_source
from .installer import (
    InstallError, default_mods_dir, install_from_registry, install_zip,
    list_installed, uninstall,
)
from .manifest import ManifestError, load_manifest
from .registry import RegistryError, load_registry, search
from .runner import run_mod


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mkga", description="MAKE KOMPAS GREAT AGAIN: хаб модов для КОМПАС-3D (неофициальный)")
    p.add_argument("--version", action="version", version=f"mkga {__version__}")
    p.add_argument("--registry", help="файл или https-ссылка на registry.json")
    p.add_argument("--mods-dir", type=Path, help="папка установленных модов")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="найти мод в реестре")
    s.add_argument("query", nargs="*")
    sub.add_parser("list", help="показать установленные моды")
    s = sub.add_parser("install", help="установить мод из реестра")
    s.add_argument("id")
    s = sub.add_parser("install-zip", help="установить мод из локального zip (для разработки)")
    s.add_argument("zip", type=Path)
    s = sub.add_parser("uninstall", help="удалить мод")
    s.add_argument("id")
    s = sub.add_parser("run", help="запустить установленный мод")
    s.add_argument("id")
    s = sub.add_parser("validate", help="проверить манифест мода в папке")
    s.add_argument("path", type=Path)
    sub.add_parser("gui", help="окно хаба")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    mods_dir = args.mods_dir or default_mods_dir()
    try:
        if args.cmd == "search":
            entries = search(load_registry(registry_source(args.registry)), " ".join(args.query))
            if not entries:
                print("Ничего не найдено.")
            for e in entries:
                print(f"{e.id:24} {e.tag:10} {e.name} — {e.description}")
        elif args.cmd == "list":
            installed = list_installed(mods_dir)
            if not installed:
                print("Установленных модов нет.")
            for m in installed:
                print(f"{m.id:24} {m.version:10} {m.name}")
        elif args.cmd == "install":
            entries = {e.id: e for e in load_registry(registry_source(args.registry))}
            if args.id not in entries:
                print(f"Мод {args.id!r} не найден в реестре.", file=sys.stderr)
                return 1
            m = install_from_registry(entries[args.id], mods_dir)
            print(f"Установлено: {m.name} {m.version}")
        elif args.cmd == "install-zip":
            m = install_zip(args.zip, mods_dir)
            print(f"Установлено: {m.name} {m.version}")
        elif args.cmd == "uninstall":
            print("Удалено." if uninstall(args.id, mods_dir) else "Такого мода нет.")
        elif args.cmd == "run":
            run_mod(mods_dir, args.id)
        elif args.cmd == "validate":
            m = load_manifest(args.path)
            print(f"OK: {m.id} {m.version} ({m.kind})")
        elif args.cmd == "gui":
            from .gui import launch
            launch(registry_source(args.registry), mods_dir)
    except (ManifestError, RegistryError, InstallError) as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
