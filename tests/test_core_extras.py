"""Версии, фейковый КОМПАС, save_as через safe_io, настройки, ошибки COM, CLI с фейком."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from mkga.__main__ import main
from mkga.core import versions
from mkga.core.fake import FakeDocument, make_fake_kompas
from mkga.core.kompas import KompasError, KompasVersionError, com_errors, describe_com_error
from mkga.core.safe_io import BackupStore
from mkga.core.settings import Settings
from mkga.runner import ModContext, run_mod_dir

ROOT = Path(__file__).resolve().parent.parent


class VersionPolicyTests(unittest.TestCase):
    def test_levels(self):
        v = versions
        self.assertEqual(v.check_version((24, 0, 3, 0), [23, 24]).level, v.OK)
        self.assertEqual(v.check_version((25, 0, 0, 0), [23, 24]).level, v.WARN)      # новее
        self.assertEqual(v.check_version((23, 0, 0, 0), [22, 24]).level, v.WARN)      # «дырка»
        self.assertEqual(v.check_version((21, 0, 0, 0), [22, 24]).level, v.REFUSE)    # старее
        self.assertEqual(v.check_version((24, 0, 3, 0), []).level, v.WARN)            # не заявлено

    def test_message_mentions_user_version_and_tested(self):
        msg = versions.check_version((25, 1, 2, 3), [24]).message
        self.assertIn("25.1.2.3", msg)
        self.assertIn("v24", msg)

    def test_supports_uses_table_and_rejects_typos(self):
        table = {"new_thing": 25}
        self.assertFalse(versions.supports("new_thing", (24, 0, 3, 0), table))
        self.assertTrue(versions.supports("new_thing", (25, 0, 0, 0), table))
        with self.assertRaises(ValueError):
            versions.supports("new_thng", (25, 0, 0, 0), table)

    def test_kompas_supports_delegates(self):
        k = make_fake_kompas(version=(24, 0, 3, 0))
        with self.assertRaises(ValueError):  # таблица пока пуста: ничего не выдумываем
            k.supports("anything")


class ContextVersionTests(unittest.TestCase):
    def _ctx(self, tmp, version, tested, confirm=None):
        logs = []
        ctx = ModContext(
            mod_dir=Path(tmp) / "m", data_dir=Path(tmp) / "d", log=logs.append,
            connect=lambda: make_fake_kompas(version=version),
            tested_versions=tested, confirm=confirm,
        )
        return ctx, logs

    def test_ok_runs_and_logs_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx, logs = self._ctx(tmp, (24, 0, 3, 0), [24])
            self.assertEqual(ctx.kompas().version, (24, 0, 3, 0))
            self.assertTrue(any("24.0.3.0" in m for m in logs))

    def test_refuse_old_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx, _ = self._ctx(tmp, (21, 0, 0, 0), [24])
            with self.assertRaises(KompasVersionError):
                ctx.kompas()

    def test_warn_without_confirm_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx, _ = self._ctx(tmp, (25, 0, 0, 0), [24])
            with self.assertRaises(KompasVersionError):
                ctx.kompas()

    def test_warn_with_confirm_yes_and_no(self):
        asked = []
        with tempfile.TemporaryDirectory() as tmp:
            ctx, _ = self._ctx(tmp, (25, 0, 0, 0), [24], confirm=lambda m: asked.append(m) or True)
            ctx.kompas()
            self.assertEqual(len(asked), 1)
            ctx2, _ = self._ctx(tmp, (25, 0, 0, 0), [24], confirm=lambda m: False)
            with self.assertRaises(KompasVersionError):
                ctx2.kompas()

    def test_no_check_when_tested_versions_not_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx, _ = self._ctx(tmp, (99, 0, 0, 0), None)
            ctx.kompas()  # не бросает


class SaveAsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.store = BackupStore(self.tmp / "store", trash=lambda p: p.unlink())
        self.k = make_fake_kompas(documents=[FakeDocument("Деталь.m3d")])
        self.doc = self.k.active_document

    def tearDown(self):
        self._tmp.cleanup()

    def test_save_as_new_file_and_undo_removes_it(self):
        out = self.tmp / "out.m3d"
        with self.store.begin("m", "сохранить") as s:
            self.k.save_as(s, self.doc, out)
            sid = s.info.id
        self.assertEqual(out.read_bytes(), FakeDocument.CONTENT)
        self.assertTrue(self.store.undo(sid).ok)
        self.assertFalse(out.exists())

    def test_save_as_over_existing_file_is_undoable(self):
        out = self.tmp / "out.m3d"
        out.write_bytes(b"user's precious file")
        with self.store.begin("m", "перезапись") as s:
            self.k.save_as(s, self.doc, out)
            sid = s.info.id
        self.assertEqual(out.read_bytes(), FakeDocument.CONTENT)
        self.assertTrue(self.store.undo(sid).ok)
        self.assertEqual(out.read_bytes(), b"user's precious file")

    def test_kompas_refusal_rolls_session_back(self):
        out = self.tmp / "out.m3d"
        out.write_bytes(b"keep")
        self.doc.save_result = False
        with self.assertRaises(KompasError):
            with self.store.begin("m", "отказ") as s:
                self.k.save_as(s, self.doc, out)
        self.assertEqual(out.read_bytes(), b"keep")

    def test_dry_run_does_not_save(self):
        out = self.tmp / "out.m3d"
        with self.store.begin("m", "предпросмотр", dry_run=True) as s:
            self.k.save_as(s, self.doc, out)
            self.assertEqual([c.kind for c in s.changes], ["create"])
        self.assertFalse(out.exists())
        self.assertEqual(self.doc.saved_to, [])


class SettingsTests(unittest.TestCase):
    def test_defaults_set_and_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "d" / "settings.json"
            s = Settings(path, defaults={"units": "mm"})
            self.assertEqual(s.get("units"), "mm")
            s.set("units", "inch")
            s.set("recent", ["a", "б"])
            s2 = Settings(path, defaults={"units": "mm"})
            self.assertEqual((s2.get("units"), s2.get("recent")), ("inch", ["a", "б"]))
            s2.reset()
            self.assertEqual(Settings(path, defaults={"units": "mm"}).get("units"), "mm")

    def test_corrupt_file_does_not_break_mod(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text("{ не json", encoding="utf-8")
            logs = []
            s = Settings(path, defaults={"a": 1}, log=logs.append)
            self.assertEqual(s.get("a"), 1)
            self.assertTrue((Path(tmp) / "settings.json.corrupt").exists())
            self.assertTrue(logs)

    def test_non_serializable_value_rejected_without_state_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Settings(Path(tmp) / "s.json")
            with self.assertRaises(TypeError):
                s.set("x", object())
            self.assertIsNone(s.get("x"))

    def test_ctx_settings_lives_in_data_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = ModContext(mod_dir=Path(tmp) / "m", data_dir=Path(tmp) / "data")
            ctx.settings.set("k", 1)
            self.assertEqual(json.loads((Path(tmp) / "data" / "settings.json").read_text(encoding="utf-8")), {"k": 1})


class FakeComError(Exception):
    pass


FakeComError.__name__ = "com_error"  # com_errors() узнаёт pywintypes.com_error по имени класса


class ComErrorTests(unittest.TestCase):
    def test_translates_known_hresult(self):
        with self.assertRaises(KompasError) as cm:
            with com_errors("открытие файла"):
                raise FakeComError(-2147418111, "Вызов отклонён", None, None)
        self.assertIn("открытие файла", str(cm.exception))
        self.assertIn("занят", str(cm.exception))
        self.assertIn("0x80010001", str(cm.exception))

    def test_unknown_code_keeps_text(self):
        self.assertIn("странная ошибка", describe_com_error(FakeComError(-1, "странная ошибка")))

    def test_other_exceptions_pass_through(self):
        with self.assertRaises(ZeroDivisionError):
            with com_errors("x"):
                1 / 0


class CliFakeKompasTests(unittest.TestCase):
    def _run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def test_run_dev_template_with_fake_kompas(self):
        with tempfile.TemporaryDirectory() as tmp:
            import os
            old = os.environ.get("MKGA_HOME")
            os.environ["MKGA_HOME"] = tmp  # данные мода не должны попасть в настоящий %APPDATA%
            try:
                rc, out, err = self._run("run-dev", str(ROOT / "mods" / "_template"), "--fake-kompas")
            finally:
                if old is None:
                    os.environ.pop("MKGA_HOME")
                else:
                    os.environ["MKGA_HOME"] = old
        self.assertEqual(rc, 0, err)
        self.assertIn("Фейковый документ.m3d", out)
        self.assertIn("24.0.3.0", out)

    def test_mod_crash_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = Path(tmp) / "boom"
            mod.mkdir()
            (mod / "mkga-mod.json").write_text(json.dumps({
                "id": "boom", "name": "B", "version": "0.0.1", "description": "d",
                "author": "a", "license": "MIT", "kind": "macro", "entry": "main.py",
            }), encoding="utf-8")
            (mod / "main.py").write_text("def run(ctx):\n    raise RuntimeError('мод сломался')\n", encoding="utf-8")
            import os
            old = os.environ.get("MKGA_HOME")
            os.environ["MKGA_HOME"] = tmp
            try:
                rc, out, err = self._run("run-dev", str(mod))
            finally:
                if old is None:
                    os.environ.pop("MKGA_HOME")
                else:
                    os.environ["MKGA_HOME"] = old
        self.assertEqual(rc, 2)
        self.assertIn("мод сломался", err)

    def test_check_command(self):
        rc, out, _ = self._run("check", str(ROOT / "mods"))
        self.assertEqual(rc, 0)
        self.assertIn("Нарушений: 0", out)


if __name__ == "__main__":
    unittest.main()
