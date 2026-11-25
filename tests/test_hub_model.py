import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from mkga.core.safe_io import BackupStore
from mkga.hub_model import (
    AVAILABLE, INSTALLED, LOCAL, UPDATE, build_rows, filter_rows, history_rows, missing_requirements, parse_version,
)
from mkga.launcher import mod_command, start_mod
from mkga.manifest import parse_manifest
from mkga.registry import RegistryEntry
from tests.helpers import good_manifest


def entry(mod_id="demo-mod", tag="v1.2.3", **kw):
    return RegistryEntry(id=mod_id, name=kw.get("name", "Демо"), description=kw.get("description", "Тестовый мод"),
                         repo="o/r", tag=tag, sha256="0" * 64, tags=kw.get("tags", ()))


def manifest(mod_id="demo-mod", version="1.2.3", **kw):
    return parse_manifest(good_manifest(id=mod_id, version=version, **kw))


class VersionTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(parse_version("0.10.0"), (0, 10, 0))
        self.assertIsNone(parse_version("nightly"))


class RowsTests(unittest.TestCase):
    def test_states(self):
        rows = {r.id: r for r in build_rows(
            [entry("a-mod", "v1.0.0"), entry("b-mod", "v2.0.0"), entry("c-mod", "v1.0.0")],
            [manifest("b-mod", "1.0.0"), manifest("c-mod", "1.0.0"), manifest("d-mod", "0.1.0")],
        )}
        self.assertEqual(rows["a-mod"].state, AVAILABLE)    # только в каталоге
        self.assertEqual(rows["b-mod"].state, UPDATE)       # в каталоге новее
        self.assertEqual(rows["c-mod"].state, INSTALLED)    # актуальна
        self.assertEqual(rows["d-mod"].state, LOCAL)        # нет в каталоге
        self.assertTrue(rows["a-mod"].can_install and rows["b-mod"].can_install)
        self.assertFalse(rows["c-mod"].can_install or rows["d-mod"].can_install)
        self.assertEqual(rows["b-mod"].version_text, "1.0.0")   # показываем установленную версию
        self.assertEqual(rows["a-mod"].version_text, "1.0.0")   # для неустановленного: версия из каталога

    def test_installed_newer_than_catalog_is_not_an_update(self):
        (row,) = build_rows([entry(tag="v1.0.0")], [manifest(version="1.5.0")])
        self.assertEqual(row.state, INSTALLED)

    def test_unparseable_tag_compares_as_text(self):
        (row,) = build_rows([entry(tag="nightly")], [manifest(version="1.0.0")])
        self.assertEqual(row.state, UPDATE)

    def test_sorted_by_name_and_empty(self):
        self.assertEqual(build_rows([], []), [])
        rows = build_rows([entry("z-mod", name="Яблоко"), entry("y-mod", name="Арбуз")], [])
        self.assertEqual([r.name for r in rows], ["Арбуз", "Яблоко"])

    def test_filter(self):
        rows = build_rows([entry("fasteners", name="Метизы", description="Винты и гайки", tags=("catalog",)),
                           entry("converter", name="Конвертер", description="КОМПАС в v22")],
                          [manifest("converter", "1.2.3")])
        self.assertEqual([r.id for r in filter_rows(rows, "винты гайки")], ["fasteners"])   # все слова
        self.assertEqual([r.id for r in filter_rows(rows, "CATALOG")], ["fasteners"])       # теги, регистр
        self.assertEqual([r.id for r in filter_rows(rows, "", only_installed=True)], ["converter"])
        self.assertEqual(len(filter_rows(rows, "")), 2)


class HistoryTests(unittest.TestCase):
    def test_rows_and_undo_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            store = BackupStore(tmp / "s", trash=lambda p: p.unlink())
            f = tmp / "a.txt"
            f.write_text("1", encoding="utf-8")
            with store.begin("m1", "Правка") as s:
                s.write_text(f, "2")
                first = s.info.id
            store.undo(first)
            with store.begin("m2", "Ещё правка") as s:
                s.write_text(f, "3")
            rows = history_rows(store)
            self.assertEqual([(r.mod_id, r.status_label, r.files, r.can_undo) for r in rows],
                             [("m2", "Применено", 1, True), ("m1", "Откачено", 1, False)])
            self.assertRegex(rows[0].when, r"^\d\d\.\d\d\.\d{4} \d\d:\d\d$")


class RequirementsTests(unittest.TestCase):
    def test_source_install_never_reports_missing_packages(self):
        self.assertEqual(missing_requirements(manifest(requires=["numpy"]), frozen=False), [])

    def test_frozen_build_lists_only_unbundled_packages(self):
        m = manifest(requires=["pywin32", "PyWin32>=306", "numpy>=1.26", "some_pkg[extra]==1.0", "pywin32; sys_platform == 'win32'"])
        self.assertEqual(missing_requirements(m, frozen=True), ["numpy>=1.26", "some_pkg[extra]==1.0"])

    def test_default_follows_sys_frozen(self):
        m = manifest(requires=["numpy"])
        with mock.patch.object(sys, "frozen", True, create=True):
            self.assertEqual(missing_requirements(m), ["numpy"])
        self.assertEqual(missing_requirements(m), [])


class FrozenLaunchTests(unittest.TestCase):
    def test_frozen_command_runs_the_exe_itself_not_python_dash_m(self):
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(sys, "executable", r"C:\MKGA\MKGA.exe"):
            cmd = mod_command(r"C:\m", "demo-mod")
        self.assertEqual(cmd, [r"C:\MKGA\MKGA.exe", "--mods-dir", r"C:\m", "run", "demo-mod"])

    def test_source_command_uses_python_dash_m_mkga(self):
        cmd = mod_command(r"C:\m", "demo-mod")
        self.assertEqual(cmd[1:3], ["-m", "mkga"])


class LauncherTests(unittest.TestCase):
    def _mods(self, tmp: Path, code: str) -> Path:
        mods = tmp / "mods"
        mod = mods / "demo-mod"
        mod.mkdir(parents=True)
        (mod / "mkga-mod.json").write_text(json.dumps(good_manifest(kind="macro", kompas_versions=[])), encoding="utf-8")
        (mod / "main.py").write_text(code, encoding="utf-8")
        return mods

    def _run(self, mods: Path):
        lines, done, code = [], threading.Event(), []
        start_mod(mods, "demo-mod", lines.append, lambda c: (code.append(c), done.set()))
        self.assertTrue(done.wait(60), "мод не завершился")
        return lines, code[0]

    def test_command_has_mods_dir_and_id(self):
        cmd = mod_command("C:/m", "demo-mod")
        self.assertEqual(cmd[-4:], ["--mods-dir", "C:/m", "run", "demo-mod"][-4:])
        self.assertIn("demo-mod", cmd)

    def test_output_with_russian_text_comes_back_through_pipe(self):
        with tempfile.TemporaryDirectory() as tmp:
            mods = self._mods(Path(tmp), "def run(ctx):\n    ctx.log('Привет из мода')\n")
            import os
            old = os.environ.get("MKGA_HOME")
            os.environ["MKGA_HOME"] = tmp
            try:
                lines, code = self._run(mods)
            finally:
                if old is None:
                    os.environ.pop("MKGA_HOME")
                else:
                    os.environ["MKGA_HOME"] = old
        self.assertEqual(code, 0, lines)
        self.assertIn("Привет из мода", lines)

    def test_crashing_mod_gives_exit_code_and_traceback_without_hurting_the_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            mods = self._mods(Path(tmp), "def run(ctx):\n    raise RuntimeError('мод сломался')\n")
            import os
            old = os.environ.get("MKGA_HOME")
            os.environ["MKGA_HOME"] = tmp
            try:
                lines, code = self._run(mods)
            finally:
                if old is None:
                    os.environ.pop("MKGA_HOME")
                else:
                    os.environ["MKGA_HOME"] = old
        self.assertEqual(code, 2)
        self.assertTrue(any("мод сломался" in line for line in lines), lines)


if __name__ == "__main__":
    unittest.main()
