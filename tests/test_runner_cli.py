import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mkga.__main__ import main
from mkga.core.fake import make_fake_kompas
from mkga.installer import install_zip
from mkga.runner import ModContext, run_mod
from tests.helpers import good_manifest, make_zip

ROOT = Path(__file__).resolve().parent.parent


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.mods = self.tmp / "mods"

    def tearDown(self):
        self._tmp.cleanup()

    def test_run_calls_run_with_lazy_kompas(self):
        code = "def run(ctx):\n    k = ctx.kompas()\n    ctx.log('hi')\n    return (k, ctx.kompas() is k)\n"
        install_zip(make_zip(self.tmp / "a.zip", good_manifest(), main_py=code), self.mods)
        logs = []
        calls = []
        fake = make_fake_kompas(version=(24, 0, 3, 0))
        ctx = ModContext(mod_dir=self.mods / "demo-mod", data_dir=self.tmp / "data",
                         log=logs.append, connect=lambda: calls.append(1) or fake)
        self.assertEqual(run_mod(self.mods, "demo-mod", ctx), (fake, True))
        self.assertIn("hi", logs)  # плюс строка о версии КОМПАСа от сверки с манифестом
        self.assertEqual(len(calls), 1)  # подключение создаётся один раз

    def test_missing_run(self):
        install_zip(make_zip(self.tmp / "a.zip", good_manifest(), main_py="x = 1\n"), self.mods)
        ctx = ModContext(mod_dir=self.mods / "demo-mod", data_dir=self.tmp / "d")
        with self.assertRaises(AttributeError):
            run_mod(self.mods, "demo-mod", ctx)

    def test_repo_template_mod_runs_on_the_fake_kompas(self):
        # окно мода fasteners здесь не открываем (это mainloop): его проверяет tests/test_fasteners.py
        from mkga.core.fake import make_fake_kompas
        logs = []
        ctx = ModContext(mod_dir=ROOT / "mods" / "_template", data_dir=self.tmp / "d", log=logs.append,
                         connect=make_fake_kompas)
        run_mod(ROOT / "mods", "_template", ctx)
        self.assertTrue(logs)

    def test_template_without_kompas_gives_clear_error(self):
        from mkga.core.kompas import KompasNotAvailable
        ctx = ModContext(mod_dir=ROOT / "mods" / "_template", data_dir=self.tmp / "d")
        # Прячем pywin32, чтобы тест не подключался к настоящему КОМПАСу,
        # если он установлен на машине разработчика.
        hidden = {"pythoncom": None, "win32com": None, "win32com.client": None}
        with mock.patch.dict(sys.modules, hidden):
            with self.assertRaises(KompasNotAvailable):
                run_mod(ROOT / "mods", "_template", ctx)


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_validate_and_install_zip_flow(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            code, out, _ = self.run_cli("validate", str(ROOT / "mods" / "fasteners"))
            self.assertEqual(code, 0)
            self.assertIn("fasteners", out)
            z = make_zip(t / "a.zip", good_manifest())
            self.assertEqual(self.run_cli("--mods-dir", str(t / "m"), "install-zip", str(z))[0], 0)
            code, out, _ = self.run_cli("--mods-dir", str(t / "m"), "list")
            self.assertIn("demo-mod", out)
            code, out, _ = self.run_cli("--mods-dir", str(t / "m"), "uninstall", "demo-mod")
            self.assertIn("Удалено", out)

    def test_validate_error_returns_1(self):
        with tempfile.TemporaryDirectory() as t:
            code, _, err = self.run_cli("validate", t)
            self.assertEqual(code, 1)
            self.assertIn("Ошибка", err)

    def test_search_empty_registry(self):
        code, out, _ = self.run_cli("--registry", str(ROOT / "registry" / "registry.json"), "search", "винт")
        self.assertEqual(code, 0)
        self.assertIn("Ничего не найдено", out)

    def test_install_unknown_id(self):
        code, _, err = self.run_cli("--registry", str(ROOT / "registry" / "registry.json"), "install", "nope")
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
