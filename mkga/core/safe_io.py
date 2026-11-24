"""Безопасная запись файлов с откатом (docs/PRINCIPLES.md, п. 1).

Мод НЕ пишет и не удаляет файлы пользователя напрямую. Всё идёт через сессию:

    store = BackupStore()                       # %LOCALAPPDATA%\\MKGA\\backups
    with store.begin("fasteners", "Создать болт M8") as s:
        s.write_bytes(path, data)               # файл есть: снимок + атомарная запись
        s.track(other_path)                     # путь запишет кто-то другой (например, КОМПАС
                                                # через doc.SaveAs): снимок до записи
        s.delete(old_path)                      # снимок + удаление в корзину
    # выход без ошибки: сессия зафиксирована; ошибка внутри: всё откатывается автоматически

    store.undo(session_id)                      # откат зафиксированной сессии из хаба

Предпросмотр: store.begin(..., dry_run=True) ничего не трогает на диске, а s.changes
возвращает список того, что БЫЛО БЫ изменено (создать, изменить, удалить), для показа
пользователю перед подтверждением.

Откат по принципу «всё или ничего» и с защитой от чужих правок: если файл с момента сессии
изменили (хеш не совпадает), откат отказывается и перечисляет конфликты. Перезаписать их можно
только явным force=True.

Хранилище: <корень>/<id сессии>/session.json и снимки <n>.snap. Расширение .snap выбрано, чтобы не
путать с копиями .bak, которые делает сам КОМПАС.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

CREATE, MODIFY, DELETE = "create", "modify", "delete"
OPEN, COMMITTED, UNDONE, ROLLED_BACK = "open", "committed", "undone", "rolled_back"


class SafeIOError(RuntimeError):
    """Операция отклонена или не удалась; файлы пользователя при этом не тронуты."""


def default_store_dir() -> Path:
    """Хранилище откатов: %LOCALAPPDATA%\\MKGA\\backups (MKGA_HOME\\backups, если задан MKGA_HOME)."""
    override = os.environ.get("MKGA_HOME")
    if override:
        return Path(override) / "backups"
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "MKGA" / "backups"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def move_to_recycle_bin(path: Path) -> None:
    """Отправить файл в корзину Windows (не удалять навсегда)."""
    if sys.platform != "win32":
        raise SafeIOError("корзина доступна только на Windows")
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _pack_ = 1 if ctypes.sizeof(ctypes.c_void_p) == 4 else 8
        _fields_ = [
            ("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    FO_DELETE = 3
    FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 0x4, 0x10, 0x40, 0x400
    op = SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = str(path.resolve()) + "\0"  # список путей заканчивается двойным нулём
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT
    code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if code != 0 or op.fAnyOperationsAborted:
        raise SafeIOError(f"не удалось отправить в корзину {path} (код {code})")


@dataclass
class Change:
    """Одна запись предпросмотра: что будет сделано с файлом."""
    kind: str   # create | modify | delete
    path: str


@dataclass
class Operation:
    kind: str
    path: str
    snapshot: str | None = None      # имя файла снимка внутри папки сессии
    sha_before: str | None = None
    sha_after: str | None = None     # None: ещё не известен (заполняется при commit)


@dataclass
class SessionInfo:
    id: str
    mod_id: str
    title: str
    created: float
    status: str = OPEN
    operations: list[Operation] = field(default_factory=list)


@dataclass
class UndoReport:
    ok: bool
    restored: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)   # файлы, изменённые после сессии


def _atomic_write(path: Path, data: bytes) -> None:
    """Записать файл целиком или не записывать вовсе: временный файл рядом и os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".mkga-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _atomic_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dst.parent, prefix=".mkga-", suffix=".tmp")
    os.close(fd)
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class Session:
    """Группа операций одного запуска мода: фиксируется или откатывается целиком."""

    def __init__(self, store: "BackupStore", info: SessionInfo, dry_run: bool = False):
        self._store = store
        self.info = info
        self.dry_run = dry_run
        self._dir = store.root / info.id
        self._paths: set[str] = set()
        self._planned: list[Change] = []
        self._closed = False
        if not dry_run:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._save()

    # --- предпросмотр ---------------------------------------------------------------
    @property
    def changes(self) -> list[Change]:
        """Что сделано (или было бы сделано при dry_run), по порядку."""
        return list(self._planned)

    # --- операции ---------------------------------------------------------------------
    def write_bytes(self, path: str | Path, data: bytes) -> None:
        p = self._check(path)
        existed = p.is_file()
        self._begin_op(MODIFY if existed else CREATE, p)
        if self.dry_run:
            return
        _atomic_write(p, data)
        self._finish_op(p, hashlib.sha256(data).hexdigest())

    def write_text(self, path: str | Path, text: str, encoding: str = "utf-8") -> None:
        self.write_bytes(path, text.encode(encoding))

    def track(self, path: str | Path) -> None:
        """Взять путь под защиту: его запишет кто-то другой (например, КОМПАС при SaveAs).

        Вызывать ДО записи. Существующий файл попадает в снимок; несуществующий будет
        считаться созданным в этой сессии. Итоговый хеш считается при фиксации сессии.
        """
        p = self._check(path)
        self._begin_op(MODIFY if p.is_file() else CREATE, p)

    def delete(self, path: str | Path) -> None:
        """Удалить файл: снимок для отката и отправка в корзину (не навсегда)."""
        p = self._check(path)
        if not p.is_file():
            raise SafeIOError(f"нечего удалять, файла нет: {p}")
        self._begin_op(DELETE, p)
        if self.dry_run:
            return
        self._store.trash(p)
        self._finish_op(p, None)

    # --- завершение -------------------------------------------------------------------
    def commit(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.dry_run:
            return
        for op in self.info.operations:
            if op.sha_after is None and op.kind != DELETE:
                p = Path(op.path)
                if p.is_file():
                    op.sha_after = sha256_of(p)
                else:  # трекали, но никто не записал
                    op.kind = DELETE if op.sha_before else op.kind
        self.info.status = COMMITTED
        self._save()

    def rollback(self) -> UndoReport:
        """Вернуть всё, как было до сессии (без проверки конфликтов: файлы только что наши)."""
        if self.dry_run:
            self._closed = True
            return UndoReport(ok=True)
        report = self._store._undo_info(self.info, force=True)
        self.info.status = ROLLED_BACK
        self._closed = True
        self._save()
        return report

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self.commit()
        elif not self._closed:
            self.rollback()
        return False  # исключение не глотаем

    # --- внутреннее -------------------------------------------------------------------
    def _check(self, path: str | Path) -> Path:
        if self._closed:
            raise SafeIOError("сессия уже завершена")
        p = Path(path).expanduser().resolve()
        if p.is_dir():
            raise SafeIOError(f"это папка, а не файл: {p}")
        if self._store.root.resolve() in p.parents:
            raise SafeIOError("нельзя трогать хранилище откатов")
        if str(p) in self._paths:
            raise SafeIOError(f"файл уже затронут в этой сессии: {p}")
        return p

    def _begin_op(self, kind: str, p: Path) -> None:
        self._paths.add(str(p))
        self._planned.append(Change(kind=kind, path=str(p)))
        if self.dry_run:
            return
        op = Operation(kind=kind, path=str(p))
        if p.is_file():
            op.sha_before = sha256_of(p)
            op.snapshot = f"{len(self.info.operations)}.snap"
            _atomic_copy(p, self._dir / op.snapshot)
        self.info.operations.append(op)
        self._save()  # запись о снимке появляется ДО самой операции

    def _finish_op(self, p: Path, sha_after: str | None) -> None:
        self.info.operations[-1].sha_after = sha_after
        self._save()

    def _save(self) -> None:
        data = json.dumps(asdict(self.info), ensure_ascii=False, indent=2).encode("utf-8")
        _atomic_write(self._dir / "session.json", data)


class BackupStore:
    """Хранилище снимков и журнал сессий."""

    def __init__(
        self,
        root: str | Path | None = None,
        trash: Callable[[Path], None] = move_to_recycle_bin,
    ):
        self.root = Path(root) if root is not None else default_store_dir()
        self.trash = trash

    def begin(self, mod_id: str, title: str, dry_run: bool = False) -> Session:
        sid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        info = SessionInfo(id=sid, mod_id=mod_id, title=title, created=time.time())
        return Session(self, info, dry_run=dry_run)

    def sessions(self) -> list[SessionInfo]:
        """Все сессии, новые первыми. Незавершённые (status=open) — признак аварии."""
        out: list[SessionInfo] = []
        if self.root.is_dir():
            for d in self.root.iterdir():
                f = d / "session.json"
                if f.is_file():
                    try:
                        out.append(self._load(f))
                    except (ValueError, KeyError, TypeError):
                        continue  # повреждённая запись не должна ломать список
        return sorted(out, key=lambda s: s.created, reverse=True)

    def undo(self, session_id: str, force: bool = False) -> UndoReport:
        """Откатить зафиксированную (или оборванную) сессию."""
        f = self.root / session_id / "session.json"
        if not f.is_file():
            raise SafeIOError(f"сессия не найдена: {session_id}")
        info = self._load(f)
        if info.status in (UNDONE, ROLLED_BACK):
            raise SafeIOError("сессия уже откачена")
        report = self._undo_info(info, force=force)
        if report.ok:
            info.status = UNDONE
            _atomic_write(f, json.dumps(asdict(info), ensure_ascii=False, indent=2).encode("utf-8"))
        return report

    def prune(self, max_age_days: float = 30, max_bytes: int | None = None) -> list[str]:
        """Удалить СТАРЫЕ снимки из хранилища откатов (только файлы самого MKGA).

        Не трогает оборванные сессии (open): по ним ещё можно восстановиться.
        Возвращает id удалённых сессий.
        """
        removed: list[str] = []
        now = time.time()
        sessions = [s for s in self.sessions() if s.status != OPEN]
        for s in sorted(sessions, key=lambda x: x.created):  # самые старые первыми
            too_old = now - s.created > max_age_days * 86400
            too_big = max_bytes is not None and self._size() > max_bytes
            if too_old or too_big:
                shutil.rmtree(self.root / s.id, ignore_errors=True)
                removed.append(s.id)
        return removed

    # --- внутреннее -------------------------------------------------------------------
    def _size(self) -> int:
        return sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())

    @staticmethod
    def _load(f: Path) -> SessionInfo:
        raw = json.loads(f.read_text(encoding="utf-8"))
        ops = [Operation(**o) for o in raw.pop("operations", [])]
        return SessionInfo(**raw, operations=ops)

    def _undo_info(self, info: SessionInfo, force: bool) -> UndoReport:
        sdir = self.root / info.id
        conflicts: list[str] = []
        if not force:
            for op in info.operations:
                if self._conflict(op):
                    conflicts.append(op.path)
        if conflicts:
            return UndoReport(ok=False, conflicts=conflicts)  # ничего не тронуто
        restored: list[str] = []
        for op in reversed(info.operations):
            p = Path(op.path)
            if op.snapshot:  # файл существовал до сессии: вернуть его содержимое
                snap = sdir / op.snapshot
                if not snap.is_file():
                    raise SafeIOError(f"снимок потерян, откат невозможен: {op.path}")
                _atomic_copy(snap, p)
                restored.append(op.path)
            elif op.kind == CREATE and p.is_file():  # создан в сессии: убрать в корзину
                self.trash(p)
                restored.append(op.path)
        return UndoReport(ok=True, restored=restored)

    @staticmethod
    def _conflict(op: Operation) -> bool:
        """Файл изменили после сессии? Тогда откат затёр бы чужую работу."""
        p = Path(op.path)
        if op.kind == DELETE:
            return p.exists()  # на его месте появился другой файл
        if op.sha_after is None:
            return False  # оборванная сессия: итоговое состояние неизвестно
        return not p.is_file() or sha256_of(p) != op.sha_after
