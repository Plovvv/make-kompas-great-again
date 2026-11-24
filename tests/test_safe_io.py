"""Тесты безопасной записи и отката. Корзина Windows подменена: тесты ничего не кладут в настоящую."""

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from mkga.core import safe_io
from mkga.core.safe_io import BackupStore, SafeIOError


class SafeIOTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.work = self.tmp / "work"
        self.work.mkdir()
        self.recycle = self.tmp / "recycle"
        self.recycle.mkdir()
        self.trashed: list[Path] = []
        self.store = BackupStore(self.tmp / "store", trash=self._fake_trash)

    def tearDown(self):
        self._tmp.cleanup()

    def _fake_trash(self, p: Path) -> None:
        self.trashed.append(p)
        shutil.move(str(p), str(self.recycle / p.name))

    def _file(self, name: str, data: bytes = b"original") -> Path:
        p = self.work / name
        p.write_bytes(data)
        return p

    # --- запись и откат -------------------------------------------------------------
    def test_create_then_undo_trashes_new_file(self):
        p = self.work / "new.txt"
        with self.store.begin("m", "создать") as s:
            s.write_text(p, "hello")
            sid = s.info.id
        self.assertEqual(p.read_text(encoding="utf-8"), "hello")
        report = self.store.undo(sid)
        self.assertTrue(report.ok)
        self.assertFalse(p.exists())
        self.assertEqual(self.trashed, [p.resolve()])  # в корзину, а не удалено навсегда

    def test_modify_then_undo_restores_original_bytes(self):
        p = self._file("a.bin", b"\x00\x01original")
        with self.store.begin("m", "правка") as s:
            s.write_bytes(p, b"changed")
            sid = s.info.id
        self.assertEqual(p.read_bytes(), b"changed")
        self.assertTrue(self.store.undo(sid).ok)
        self.assertEqual(p.read_bytes(), b"\x00\x01original")

    def test_delete_goes_to_trash_and_undo_restores(self):
        p = self._file("d.txt", b"keep me")
        with self.store.begin("m", "удалить") as s:
            s.delete(p)
            sid = s.info.id
        self.assertFalse(p.exists())
        self.assertEqual(len(self.trashed), 1)
        self.assertTrue(self.store.undo(sid).ok)
        self.assertEqual(p.read_bytes(), b"keep me")

    def test_track_external_write(self):
        p = self._file("ext.m3d", b"v1")
        with self.store.begin("m", "SaveAs из КОМПАСа") as s:
            s.track(p)
            p.write_bytes(b"v2 written by KOMPAS")  # пишет кто-то другой
            sid = s.info.id
        self.assertTrue(self.store.undo(sid).ok)
        self.assertEqual(p.read_bytes(), b"v1")

    def test_track_new_path_created_externally_is_trashed_on_undo(self):
        p = self.work / "made-by-kompas.m3d"
        with self.store.begin("m", "создать") as s:
            s.track(p)
            p.write_bytes(b"x")
            sid = s.info.id
        self.assertTrue(self.store.undo(sid).ok)
        self.assertFalse(p.exists())

    # --- сбои ---------------------------------------------------------------------------
    def test_exception_rolls_everything_back(self):
        a = self._file("a.txt", b"A")
        b = self._file("b.txt", b"B")
        new = self.work / "n.txt"
        with self.assertRaises(ValueError):
            with self.store.begin("m", "упадёт") as s:
                s.write_bytes(a, b"A2")
                s.delete(b)
                s.write_bytes(new, b"N")
                raise ValueError("мод сломался")
        self.assertEqual(a.read_bytes(), b"A")
        self.assertEqual(b.read_bytes(), b"B")
        self.assertFalse(new.exists())
        self.assertEqual(self.store.sessions()[0].status, safe_io.ROLLED_BACK)

    def test_failed_atomic_write_keeps_original_and_leaves_no_temp(self):
        p = self._file("a.txt", b"safe")
        real_replace = os.replace
        failed = []

        def flaky_replace(src, dst):
            # падает ровно один раз: при записи нового содержимого в целевой файл
            if Path(dst) == p.resolve() and not failed and Path(src).read_bytes() == b"new":
                failed.append(1)
                raise OSError("диск полон")
            return real_replace(src, dst)

        with mock.patch("mkga.core.safe_io.os.replace", side_effect=flaky_replace):
            with self.assertRaises(OSError):
                with self.store.begin("m", "сбой записи") as s:
                    s.write_bytes(p, b"new")
        self.assertEqual(failed, [1])  # сбой действительно произошёл на записи
        self.assertEqual(p.read_bytes(), b"safe")
        self.assertEqual([f.name for f in self.work.iterdir()], ["a.txt"])  # нет мусорных .tmp

    def test_crashed_session_stays_open_and_can_be_undone(self):
        p = self._file("a.txt", b"before")
        s = self.store.begin("m", "оборвётся")
        s.write_bytes(p, b"after")
        # процесс «умер»: commit не вызван
        info = self.store.sessions()[0]
        self.assertEqual(info.status, safe_io.OPEN)
        self.assertTrue(self.store.undo(info.id).ok)
        self.assertEqual(p.read_bytes(), b"before")

    # --- защита от чужих правок ---------------------------------------------------
    def test_undo_refuses_when_file_changed_after_session(self):
        p = self._file("a.txt", b"orig")
        with self.store.begin("m", "правка") as s:
            s.write_bytes(p, b"mod")
            sid = s.info.id
        p.write_bytes(b"user kept working")  # пользователь продолжил работу
        report = self.store.undo(sid)
        self.assertFalse(report.ok)
        self.assertEqual(report.conflicts, [str(p.resolve())])
        self.assertEqual(p.read_bytes(), b"user kept working")  # ничего не затёрто
        self.assertTrue(self.store.undo(sid, force=True).ok)  # только явным решением
        self.assertEqual(p.read_bytes(), b"orig")

    def test_undo_is_all_or_nothing(self):
        a = self._file("a.txt", b"A")
        b = self._file("b.txt", b"B")
        with self.store.begin("m", "две правки") as s:
            s.write_bytes(a, b"A2")
            s.write_bytes(b, b"B2")
            sid = s.info.id
        b.write_bytes(b"B3")  # конфликт только у второго
        self.assertFalse(self.store.undo(sid).ok)
        self.assertEqual(a.read_bytes(), b"A2")  # и первый не откатили частично

    def test_undo_twice_is_an_error(self):
        p = self._file("a.txt")
        with self.store.begin("m", "x") as s:
            s.write_bytes(p, b"y")
            sid = s.info.id
        self.store.undo(sid)
        with self.assertRaises(SafeIOError):
            self.store.undo(sid)

    # --- предпросмотр -------------------------------------------------------------------
    def test_dry_run_touches_nothing_and_lists_changes(self):
        a = self._file("a.txt", b"A")
        gone = self._file("gone.txt", b"G")
        new = self.work / "new.txt"
        with self.store.begin("m", "предпросмотр", dry_run=True) as s:
            s.write_bytes(a, b"A2")
            s.write_bytes(new, b"N")
            s.delete(gone)
            kinds = [(c.kind, Path(c.path).name) for c in s.changes]
        self.assertEqual(kinds, [("modify", "a.txt"), ("create", "new.txt"), ("delete", "gone.txt")])
        self.assertEqual(a.read_bytes(), b"A")
        self.assertTrue(gone.exists())
        self.assertFalse(new.exists())
        self.assertEqual(self.trashed, [])
        self.assertFalse(self.store.root.exists())  # даже хранилище не создавалось

    # --- отказы ---------------------------------------------------------------------------
    def test_rejects_directory_store_and_double_touch(self):
        p = self._file("a.txt")
        with self.store.begin("m", "x") as s:
            with self.assertRaises(SafeIOError):
                s.write_bytes(self.work, b"x")  # папка
            with self.assertRaises(SafeIOError):
                s.write_bytes(self.store.root / "evil.txt", b"x")  # хранилище откатов
            s.write_bytes(p, b"1")
            with self.assertRaises(SafeIOError):
                s.write_bytes(p, b"2")  # тот же файл второй раз
            with self.assertRaises(SafeIOError):
                s.delete(self.work / "missing.txt")  # нечего удалять

    def test_use_after_close_is_rejected(self):
        s = self.store.begin("m", "x")
        s.commit()
        with self.assertRaises(SafeIOError):
            s.write_bytes(self.work / "late.txt", b"x")

    # --- чистка ---------------------------------------------------------------------------
    def test_prune_removes_old_but_keeps_open_sessions(self):
        p = self._file("a.txt")
        with self.store.begin("m", "старая") as s:
            s.write_bytes(p, b"x")
            old_id = s.info.id
        open_s = self.store.begin("m", "оборванная")
        open_s.track(self.work / "t.txt")
        long_ago = time.time() - 40 * 86400
        for sid in (old_id, open_s.info.id):
            f = self.store.root / sid / "session.json"
            data = json.loads(f.read_text(encoding="utf-8"))
            data["created"] = long_ago
            f.write_text(json.dumps(data), encoding="utf-8")
        removed = self.store.prune(max_age_days=30)
        self.assertEqual(removed, [old_id])
        self.assertTrue((self.store.root / open_s.info.id).is_dir())

    def test_default_store_dir_respects_mkga_home(self):
        with mock.patch.dict(os.environ, {"MKGA_HOME": str(self.tmp / "home")}):
            self.assertEqual(safe_io.default_store_dir(), self.tmp / "home" / "backups")


class ContextTests(unittest.TestCase):
    def test_ctx_session_uses_store_and_mod_id(self):
        from mkga.runner import ModContext
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            store = BackupStore(tmp / "store", trash=lambda p: p.unlink())
            ctx = ModContext(mod_dir=tmp / "mods" / "demo", data_dir=tmp / "d", backups=store)
            target = tmp / "f.txt"
            target.write_text("v1", encoding="utf-8")
            with ctx.session("правка") as s:
                s.write_text(target, "v2")
            info = store.sessions()[0]
            self.assertEqual((info.mod_id, info.title, info.status), ("demo", "правка", safe_io.COMMITTED))
            self.assertTrue(store.undo(info.id).ok)
            self.assertEqual(target.read_text(encoding="utf-8"), "v1")


if __name__ == "__main__":
    unittest.main()
