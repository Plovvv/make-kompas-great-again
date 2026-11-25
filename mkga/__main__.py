"""Командная строка: python -m mkga <команда>."""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path

from . import __version__
from .console import ensure_utf8_output
from .core.kompas import KompasError
from .core.safe_io import BackupStore, SafeIOError
from .guard import check_path, violations
from .config import registry_source
from .installer import (
    InstallError, default_mods_dir, install_from_registry, install_zip,
    list_installed, uninstall,
)
from .manifest import ManifestError, load_manifest
from .registry import RegistryError, load_registry, search
from .runner import run_mod, run_mod_dir


def _add_run_options(s: argparse.ArgumentParser) -> None:
    s.add_argument("--fake-kompas", action="store_true",
                   help="не подключаться к КОМПАСу, а использовать фейковый (для разработки и проверки)")
    s.add_argument("--yes", action="store_true",
                   help="подтверждать предупреждения о версии КОМПАСа без вопроса")


def _cli_confirm(yes: bool):
    """Вопрос пользователю в консоли. Без терминала и без --yes ответ «нет»."""
    def confirm(message: str) -> bool:
        print(f"Предупреждение: {message}", file=sys.stderr)
        if yes:
            return True
        if not sys.stdin or not sys.stdin.isatty():
            return False
        return input("Продолжить? [y/N] ").strip().lower() in ("y", "yes", "д", "да")
    return confirm


def _connector(args):
    """None: обычное подключение к КОМПАСу; иначе фейковый КОМПАС с документом-заглушкой."""
    if not args.fake_kompas:
        return None
    from .core.fake import FakeDocument, make_fake_kompas
    return lambda: make_fake_kompas(documents=[FakeDocument("Фейковый документ.m3d")])


def _run_guarded(call) -> int:
    """Запуск мода: ошибка мода не должна ронять хаб и не показывается как «падение»."""
    try:
        call()
    except (KompasError, SafeIOError) as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 1
    except (ManifestError, InstallError):
        raise
    except Exception as e:  # мод упал: показываем причину и сохраняем работоспособность хаба
        traceback.print_exc()
        print(f"Мод завершился с ошибкой: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    return 0


def _pack(args) -> int:
    import json

    from .release import ReleaseError, add_to_registry, build_release, registry_entry
    if args.add_to_registry and not args.repo:
        print("Ошибка: для --add-to-registry нужен --repo owner/name", file=sys.stderr)
        return 1
    try:
        info = build_release(args.path, args.out, args.tag)
        entry = registry_entry(info, args.repo) if args.repo else None
        action = add_to_registry(args.add_to_registry, entry) if args.add_to_registry else None
    except ReleaseError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 1
    print(f"Собрано: {info.path}  ({info.size} байт, файлов {info.files})")
    print(f"sha256: {info.sha256}")
    print(f"Загрузите этот файл в релиз с тегом {info.tag!r} под именем {info.path.name!r}.")
    if entry:
        print("Запись для registry/registry.json:")
        print(json.dumps(entry, ensure_ascii=False, indent=2))
        if action:
            print(f"Реестр {args.add_to_registry}: {action}.")
    return 0


def _verify_registry(args) -> int:
    from .verify import verify_registry
    reports = verify_registry(registry_source(args.registry), only=set(args.only) if args.only else None)
    bad = 0
    for r in reports:
        status = "OK" if r.ok else "ОШИБКА"
        print(f"{status:7} {r.entry.id} {r.entry.tag}")
        for line in r.problems:
            print(f"        - {line}")
        for line in r.warnings:
            print(f"        ! {line}")
        bad += 0 if r.ok else 1
    print(f"Записей проверено: {len(reports)}, с ошибками: {bad}")
    return 1 if bad else 0


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
    _add_run_options(s)
    s = sub.add_parser("run-dev", help="запустить мод прямо из папки, без установки (для разработки)")
    s.add_argument("path", type=Path)
    _add_run_options(s)
    s = sub.add_parser("validate", help="проверить манифест мода в папке")
    s.add_argument("path", type=Path)
    s = sub.add_parser("pack", help="собрать релиз мода: воспроизводимый zip, хеш и запись для реестра")
    s.add_argument("path", type=Path, help="папка мода (с mkga-mod.json)")
    s.add_argument("--out", type=Path, default=Path("dist"), help="куда положить архив (по умолчанию dist)")
    s.add_argument("--tag", help="тег релиза (по умолчанию v<версия из манифеста>)")
    s.add_argument("--repo", help="репозиторий релиза owner/name: тогда печатается запись для реестра")
    s.add_argument("--add-to-registry", type=Path, metavar="registry.json",
                   help="добавить или обновить запись в этом файле реестра (нужен --repo)")
    s = sub.add_parser("verify-registry", help="скачать релизы из реестра и проверить хеш, манифест и страж правил")
    s.add_argument("--only", nargs="*", default=None, metavar="ID", help="проверить только эти id")
    s = sub.add_parser("check", help="проверить код мода: нет ли записи файлов в обход ctx.session")
    s.add_argument("path", type=Path)
    sub.add_parser("history", help="журнал изменений файлов, сделанных модами (для отката)")
    s = sub.add_parser("undo", help="откатить сессию изменений из журнала")
    s.add_argument("session_id")
    s.add_argument("--force", action="store_true",
                   help="откатить, даже если файлы изменены после сессии (затрёт эти правки!)")
    s = sub.add_parser("ui-demo", help="демо окна мода (пишет только во временную папку)")
    s.add_argument("--fake-kompas", action="store_true", help="не подключаться к настоящему КОМПАСу")
    s.add_argument("--dark", action="store_true", help="тёмная тема")
    sub.add_parser("gui", help="окно хаба")
    return p


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_output()  # перенаправленный вывод (CI, запуск из хаба) на Windows иначе падает на русском
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
            return _run_guarded(lambda: run_mod(
                mods_dir, args.id, connect=_connector(args), confirm=_cli_confirm(args.yes)))
        elif args.cmd == "run-dev":
            return _run_guarded(lambda: run_mod_dir(
                args.path, connect=_connector(args), confirm=_cli_confirm(args.yes)))
        elif args.cmd == "validate":
            m = load_manifest(args.path)
            print(f"OK: {m.id} {m.version} ({m.kind})")
        elif args.cmd == "pack":
            return _pack(args)
        elif args.cmd == "verify-registry":
            return _verify_registry(args)
        elif args.cmd == "check":
            findings = check_path(args.path)
            for f in findings:
                print(f)
            bad = violations(findings)
            print(f"Нарушений: {len(bad)}, разрешено с пометкой: {len(findings) - len(bad)}")
            return 1 if bad else 0
        elif args.cmd == "history":
            sessions = BackupStore().sessions()
            if not sessions:
                print("Изменений файлов модами не было.")
            for si in sessions:
                when = time.strftime("%Y-%m-%d %H:%M", time.localtime(si.created))
                print(f"{si.id}  {when}  {si.status:11} {si.mod_id}: {si.title} ({len(si.operations)} файл.)")
        elif args.cmd == "undo":
            report = BackupStore().undo(args.session_id, force=args.force)
            if report.ok:
                print(f"Откат выполнен, восстановлено файлов: {len(report.restored)}")
                for p in report.restored:
                    print(f"  {p}")
            else:
                print("Откат НЕ выполнен: эти файлы изменены после сессии:", file=sys.stderr)
                for p in report.conflicts:
                    print(f"  {p}", file=sys.stderr)
                print("Если уверены, повторите с --force (правки после сессии будут потеряны).", file=sys.stderr)
                return 1
        elif args.cmd == "ui-demo":
            from .ui.demo import run_demo
            run_demo(fake_kompas=args.fake_kompas, dark=args.dark)
        elif args.cmd == "gui":
            from .gui import launch
            launch(registry_source(args.registry), mods_dir)
    except (ManifestError, RegistryError, InstallError, SafeIOError) as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
