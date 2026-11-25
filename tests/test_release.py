import contextlib
import io
import json
import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from mkga import release, verify
from mkga.__main__ import main
from mkga.installer import InstallError, install_zip, sha256_file
from mkga.registry import RegistryEntry, parse_registry
from mkga.release import ReleaseError, add_to_registry, build_release, registry_entry
from tests.helpers import good_manifest

ROOT = Path(__file__).resolve().parent.parent
MAIN_OK = "def run(ctx):\n    ctx.log('привет')\n"


def make_mod(base: Path, mod_id="demo-mod", version="1.2.3", main_py=MAIN_OK, **manifest) -> Path:
    d = base / mod_id
    d.mkdir(parents=True)
    (d / "mkga-mod.json").write_text(
        json.dumps(good_manifest(id=mod_id, version=version, **manifest), ensure_ascii=False), encoding="utf-8")
    (d / "main.py").write_text(main_py, encoding="utf-8")
    return d


def entry_for(info, repo="o/r") -> RegistryEntry:
    return parse_registry({"schema": 1, "mods": [registry_entry(info, repo)]})[0]


class BuildTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_archive_name_layout_and_installability(self):
        mod = make_mod(self.tmp)
        (mod / "data").mkdir()
        (mod / "data" / "table.json").write_text("{}", encoding="utf-8")
        info = build_release(mod, self.tmp / "dist")
        self.assertEqual((info.path.name, info.tag), ("demo-mod-v1.2.3.zip", "v1.2.3"))   # имя, по которому хаб ищет релиз
        with zipfile.ZipFile(info.path) as zf:
            self.assertEqual(sorted(zf.namelist()), ["data/table.json", "main.py", "mkga-mod.json"])  # манифест в корне
        installed = install_zip(info.path, self.tmp / "mods", expected_id="demo-mod", expected_sha256=info.sha256)
        self.assertEqual(installed.version, "1.2.3")

    def test_build_is_reproducible_and_ignores_mtime_and_location(self):
        a = make_mod(self.tmp / "a")
        b = make_mod(self.tmp / "b")
        for f in b.iterdir():
            os.utime(f, (time.time() - 99999, time.time() - 99999))   # другое время изменения
        self.assertEqual(build_release(a, self.tmp / "da").sha256, build_release(b, self.tmp / "db").sha256)

    def test_junk_is_excluded(self):
        mod = make_mod(self.tmp)
        for rel, text in (("__pycache__/m.cpython-313.pyc", "x"), ("tests/test_x.py", "x"), (".git/config", "x"),
                          (".gitignore", "x"), ("old.pyc", "x"), ("Thumbs.db", "x"), (".idea/w.xml", "x")):
            p = mod / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        info = build_release(mod, self.tmp / "dist")
        with zipfile.ZipFile(info.path) as zf:
            self.assertEqual(sorted(zf.namelist()), ["main.py", "mkga-mod.json"])
        self.assertEqual(info.files, 2)

    def test_tag_must_match_manifest_version(self):
        mod = make_mod(self.tmp, version="1.2.3")
        self.assertEqual(build_release(mod, self.tmp / "d", tag="v1.2.3").tag, "v1.2.3")
        self.assertEqual(build_release(mod, self.tmp / "d", tag="1.2.3").path.name, "demo-mod-1.2.3.zip")
        for bad in ("v1.2.4", "latest", "v1.2"):
            with self.assertRaises(ReleaseError, msg=bad):
                build_release(mod, self.tmp / "d", tag=bad)

    def test_refuses_broken_or_missing_manifest_and_entry(self):
        with self.assertRaises(ReleaseError):
            build_release(self.tmp, self.tmp / "d")                       # нет манифеста
        mod = make_mod(self.tmp / "m")
        (mod / "main.py").unlink()
        with self.assertRaises(ReleaseError) as cm:
            build_release(mod, self.tmp / "d")
        self.assertIn("entry", str(cm.exception))
        bad = make_mod(self.tmp / "n", kind="nonsense")
        with self.assertRaises(ReleaseError):
            build_release(bad, self.tmp / "d")

    def test_guard_violation_blocks_the_release(self):
        mod = make_mod(self.tmp, main_py="import os\ndef run(ctx):\n    os.remove('a.txt')\n")
        with self.assertRaises(ReleaseError) as cm:
            build_release(mod, self.tmp / "dist")
        self.assertIn("ctx.session", str(cm.exception))
        self.assertFalse((self.tmp / "dist" / "demo-mod-v1.2.3.zip").exists())

    def test_guard_allow_marker_does_not_block(self):
        code = "import os\ndef run(ctx):\n    os.remove('a')  # mkga: allow-unsafe-io (временный файл мода)\n"
        build_release(make_mod(self.tmp, main_py=code), self.tmp / "dist")

    def test_size_limit(self):
        mod = make_mod(self.tmp)
        with mock.patch.object(release, "MAX_BYTES", 10):
            with self.assertRaises(ReleaseError) as cm:
                build_release(mod, self.tmp / "dist")
        self.assertIn("слишком большой", str(cm.exception))

    def test_failed_build_leaves_no_partial_files(self):
        mod = make_mod(self.tmp)
        with mock.patch.object(release.zipfile.ZipFile, "writestr", side_effect=OSError("диск полон")):
            with self.assertRaises(OSError):
                build_release(mod, self.tmp / "dist")
        self.assertEqual(list((self.tmp / "dist").iterdir()), [])         # ни архива, ни .tmp

    def test_repo_template_builds(self):
        info = build_release(ROOT / "mods" / "_template", self.tmp / "dist")
        self.assertEqual(info.manifest.id, "hello-kompas")


class RegistryEditTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.reg = self.tmp / "registry.json"
        self.reg.write_text('{"schema": 1, "mods": []}', encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def entry(self, mod_id, tag="v1.0.0"):
        return {"id": mod_id, "name": "Имя", "description": "Описание", "repo": "o/r", "tag": tag,
                "sha256": "a" * 64, "tags": ["t"]}

    def test_add_update_and_sort(self):
        self.assertEqual(add_to_registry(self.reg, self.entry("zz-mod")), "добавлено")
        self.assertEqual(add_to_registry(self.reg, self.entry("aa-mod")), "добавлено")
        self.assertEqual(add_to_registry(self.reg, self.entry("zz-mod", "v2.0.0")), "обновлено")
        data = json.loads(self.reg.read_text(encoding="utf-8"))
        self.assertEqual([(m["id"], m["tag"]) for m in data["mods"]], [("aa-mod", "v1.0.0"), ("zz-mod", "v2.0.0")])
        self.assertIn("Описание", self.reg.read_text(encoding="utf-8"))   # кириллица не экранируется
        self.assertEqual(len(parse_registry(data)), 2)

    def test_invalid_entry_is_rejected_and_file_untouched(self):
        before = self.reg.read_text(encoding="utf-8")
        bad = self.entry("good-mod")
        bad["sha256"] = "xyz"
        with self.assertRaises(ReleaseError):
            add_to_registry(self.reg, bad)
        self.assertEqual(self.reg.read_text(encoding="utf-8"), before)

    def test_registry_entry_validates_repo(self):
        mod = make_mod(self.tmp / "m")
        info = build_release(mod, self.tmp / "d")
        self.assertEqual(registry_entry(info, "me/demo")["sha256"], info.sha256)
        with self.assertRaises(ReleaseError):
            registry_entry(info, "not a repo")


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.info = build_release(make_mod(self.tmp / "m"), self.tmp / "dist")
        self.entry = entry_for(self.info)

    def tearDown(self):
        self._tmp.cleanup()

    def forge(self, name="forged.zip", files=None, manifest=None) -> Path:
        """Собрать архив ВРУЧНУЮ (в обход pack), как это мог бы сделать недобросовестный автор."""
        path = self.tmp / name
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("mkga-mod.json", json.dumps(manifest or good_manifest(), ensure_ascii=False))
            for n, c in (files if files is not None else {"main.py": MAIN_OK}).items():
                zf.writestr(n, c)
        return path

    def entry_of(self, path: Path, **changes) -> RegistryEntry:
        raw = dict(registry_entry(self.info, "o/r"))
        raw["sha256"] = sha256_file(path)
        raw.update(changes)
        return parse_registry({"schema": 1, "mods": [raw]})[0]

    def test_good_archive_passes(self):
        report = verify.verify_archive(self.info.path, self.entry)
        self.assertTrue(report.ok, report.problems)
        self.assertEqual((report.problems, report.warnings), ([], []))

    def test_wrong_hash_stops_everything(self):
        bad = RegistryEntry(**{**self.entry.__dict__, "sha256": "0" * 64})
        report = verify.verify_archive(self.info.path, bad)
        self.assertFalse(report.ok)
        self.assertIn("хеш", report.problems[0])
        self.assertEqual(len(report.problems), 1)       # содержимому не доверяем, дальше не смотрим

    def test_id_and_version_must_match_the_entry(self):
        path = self.forge()
        report = verify.verify_archive(path, self.entry_of(path, id="other-mod"))
        self.assertTrue(any("id в манифесте" in p for p in report.problems))
        report = verify.verify_archive(path, self.entry_of(path, tag="v9.9.9"))
        self.assertTrue(any("версия в манифесте" in p for p in report.problems))

    def test_guard_violation_in_a_forged_archive_is_found(self):
        path = self.forge(files={"main.py": "import shutil\ndef run(ctx):\n    shutil.rmtree('x')\n"})
        report = verify.verify_archive(path, self.entry_of(path))
        self.assertFalse(report.ok)
        self.assertTrue(any("страж правил" in p and "shutil" in p for p in report.problems))

    def test_hostile_archives_are_rejected_not_extracted(self):
        slip = self.tmp / "slip.zip"
        with zipfile.ZipFile(slip, "w") as zf:
            zf.writestr("../evil.py", "x")
        report = verify.verify_archive(slip, self.entry_of(slip))
        self.assertFalse(report.ok)
        self.assertFalse((self.tmp.parent / "evil.py").exists())
        notzip = self.tmp / "n.zip"
        notzip.write_bytes(b"not a zip")
        self.assertIn("не является zip", verify.verify_archive(notzip, self.entry_of(notzip)).problems[0])
        bomb = self.forge("bomb.zip")
        with mock.patch("mkga.installer.MAX_UNCOMPRESSED", 10):
            report = verify.verify_archive(bomb, self.entry_of(bomb))
        self.assertTrue(any("слишком большой" in p for p in report.problems))

    def test_missing_entry_file_and_name_warnings(self):
        path = self.forge(files={"other.py": MAIN_OK})
        report = verify.verify_archive(path, self.entry_of(path, name="Другое имя"))
        self.assertTrue(any("entry" in p for p in report.problems))
        self.assertTrue(any("название" in w for w in report.warnings))

    def test_verify_entry_downloads_from_the_registry_url(self):
        calls = []

        def fetch(url, dest):
            calls.append(url)
            dest.write_bytes(self.info.path.read_bytes())

        report = verify.verify_entry(self.entry, fetch)
        self.assertTrue(report.ok)
        self.assertEqual(calls, ["https://github.com/o/r/releases/download/v1.2.3/demo-mod-v1.2.3.zip"])

    def test_download_failure_is_a_problem_not_a_crash(self):
        def fetch(url, dest):
            raise OSError("404 Not Found")
        report = verify.verify_entry(self.entry, fetch)
        self.assertFalse(report.ok)
        self.assertIn("не удалось скачать", report.problems[0])

    def test_verify_registry_over_a_local_file_with_only_filter(self):
        reg = self.tmp / "reg.json"
        other = registry_entry(self.info, "o/r")
        other["id"] = "second-mod"
        reg.write_text(json.dumps({"schema": 1, "mods": [registry_entry(self.info, "o/r"), other]}), encoding="utf-8")
        fetched = []

        def fetch(url, dest):
            fetched.append(url)
            dest.write_bytes(self.info.path.read_bytes())

        reports = verify.verify_registry(reg, only={"demo-mod"}, fetch=fetch)
        self.assertEqual([r.entry.id for r in reports], ["demo-mod"])
        self.assertEqual(len(fetched), 1)
        self.assertTrue(reports[0].ok)


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def test_pack_prints_hash_entry_and_updates_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            mod = make_mod(tmp / "m")
            reg = tmp / "registry.json"
            reg.write_text('{"schema": 1, "mods": []}', encoding="utf-8")
            rc, out, err = self.run_cli("pack", str(mod), "--out", str(tmp / "dist"), "--repo", "me/demo",
                                        "--add-to-registry", str(reg))
            self.assertEqual(rc, 0, err)
            self.assertIn("demo-mod-v1.2.3.zip", out)
            data = json.loads(reg.read_text(encoding="utf-8"))
            self.assertEqual(data["mods"][0]["sha256"], sha256_file(tmp / "dist" / "demo-mod-v1.2.3.zip"))
            self.assertIn(data["mods"][0]["sha256"], out)

    def test_pack_errors_are_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            mod = make_mod(tmp / "m")
            self.assertEqual(self.run_cli("pack", str(mod), "--tag", "v9.9.9")[0], 1)
            rc, _, err = self.run_cli("pack", str(mod), "--add-to-registry", str(tmp / "r.json"))
            self.assertEqual(rc, 1)
            self.assertIn("--repo", err)
            rc, _, err = self.run_cli("pack", str(tmp / "missing"))
            self.assertEqual(rc, 1)
            self.assertIn("Ошибка", err)

    def test_verify_registry_exit_codes(self):
        entry = parse_registry({"schema": 1, "mods": [{"id": "demo-mod", "name": "Демо", "description": "д",
                                                       "repo": "o/r", "tag": "v1.0.0", "sha256": "0" * 64}]})[0]
        bad = verify.Report(entry, problems=["хеш не совпал"])
        good = verify.Report(entry)
        with mock.patch("mkga.verify.verify_registry", return_value=[bad]):
            rc, out, _ = self.run_cli("verify-registry")
        self.assertEqual(rc, 1)
        self.assertIn("хеш не совпал", out)
        with mock.patch("mkga.verify.verify_registry", return_value=[good]):
            self.assertEqual(self.run_cli("verify-registry")[0], 0)

    def test_empty_repo_registry_verifies_cleanly(self):
        rc, out, _ = self.run_cli("--registry", str(ROOT / "registry" / "registry.json"), "verify-registry")
        self.assertEqual(rc, 0)
        self.assertIn("проверено: 0", out)


class EndToEndTests(unittest.TestCase):
    def test_pack_then_install_then_run_the_template(self):
        """Сквозной путь автора и пользователя: собрать шаблон, проверить, поставить, запустить."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            info = build_release(ROOT / "mods" / "_template", tmp / "dist")
            report = verify.verify_archive(info.path, entry_for(info))
            self.assertTrue(report.ok, report.problems)
            mods = tmp / "mods"
            install_zip(info.path, mods, expected_id="hello-kompas", expected_sha256=info.sha256)
            old = os.environ.get("MKGA_HOME")
            os.environ["MKGA_HOME"] = str(tmp)
            try:
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    rc = main(["--mods-dir", str(mods), "run", "hello-kompas", "--fake-kompas"])
            finally:
                if old is None:
                    os.environ.pop("MKGA_HOME")
                else:
                    os.environ["MKGA_HOME"] = old
            self.assertEqual(rc, 0, err.getvalue())
            self.assertIn("Фейковый документ.m3d", out.getvalue())


if __name__ == "__main__":
    unittest.main()
