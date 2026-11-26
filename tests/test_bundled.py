"""Моды в поставке (папка bundled рядом с exe): индекс, проверка хеша, слияние с каталогом, установка без сети."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mkga import bundled as B
from mkga.__main__ import main
from mkga.installer import list_installed
from mkga.registry import RegistryEntry

ROOT = Path(__file__).resolve().parent.parent


def make_bundle(tmp: Path) -> Path:
    out = tmp / "bundled"
    B.write_bundle([ROOT / "mods" / "_template"], out)
    return out


class BundleFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_write_and_load_roundtrip(self):
        out = make_bundle(self.tmp)
        mods, problems = B.load_bundled(out)
        self.assertEqual(problems, [])
        self.assertEqual(len(mods), 1)
        self.assertTrue(mods[0].path.is_file())
        self.assertEqual(len(mods[0].sha256), 64)

    def test_missing_directory_or_index_is_empty_not_an_error(self):
        self.assertEqual(B.load_bundled(self.tmp / "none"), ([], []))
        (self.tmp / "empty").mkdir()
        self.assertEqual(B.load_bundled(self.tmp / "empty"), ([], []))

    def test_tampered_archive_is_skipped_with_a_message(self):
        out = make_bundle(self.tmp)
        archive = next(out.glob("*.zip"))
        archive.write_bytes(archive.read_bytes() + b"x")
        mods, problems = B.load_bundled(out)
        self.assertEqual(mods, [])
        self.assertTrue(any("хеш" in p for p in problems))

    def test_index_cannot_point_outside_the_folder(self):
        out = make_bundle(self.tmp)
        index = json.loads((out / "index.json").read_text(encoding="utf-8"))
        index["mods"][0]["file"] = "../evil.zip"
        (out / "index.json").write_text(json.dumps(index), encoding="utf-8")
        mods, problems = B.load_bundled(out)
        self.assertEqual((mods, len(problems)), ([], 1))

    def test_broken_index_is_reported(self):
        out = self.tmp / "b"
        out.mkdir()
        (out / "index.json").write_text("{oops", encoding="utf-8")
        mods, problems = B.load_bundled(out)
        self.assertEqual(mods, [])
        self.assertTrue(problems)

    def test_env_override_and_default(self):
        with mock.patch.dict(os.environ, {"MKGA_BUNDLED": str(self.tmp)}):
            self.assertEqual(B.bundled_dir(), self.tmp)
        env = {k: v for k, v in os.environ.items() if k != "MKGA_BUNDLED"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertIsNone(B.bundled_dir())                       # из исходников поставки нет


class Merge(unittest.TestCase):
    def entry(self, tag, repo="o/r"):
        return RegistryEntry("m", "Мод", "описание", repo, tag, "0" * 64, ())

    def bundle(self, version):
        return B.BundledMod("m", "Мод из поставки", "d", version, (), Path("x.zip"), "1" * 64)

    def test_bundled_fills_an_empty_catalog(self):
        (e,) = B.merge_entries([], [self.bundle("0.5.0")])
        self.assertEqual((e.id, e.tag, e.repo), ("m", "v0.5.0", B.BUNDLED_REPO))

    def test_newer_wins_and_catalog_wins_a_tie(self):
        (e,) = B.merge_entries([self.entry("v0.4.0")], [self.bundle("0.5.0")])
        self.assertEqual(e.repo, B.BUNDLED_REPO)
        (e,) = B.merge_entries([self.entry("v0.6.0")], [self.bundle("0.5.0")])
        self.assertEqual(e.repo, "o/r")
        (e,) = B.merge_entries([self.entry("v0.5.0")], [self.bundle("0.5.0")])
        self.assertEqual(e.repo, "o/r")


class InstallFromBundle(unittest.TestCase):
    def test_cli_install_falls_back_to_the_bundle_when_the_registry_is_unreachable(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        out = make_bundle(tmp)
        (mod,) = B.load_bundled(out)[0]
        mods_dir = tmp / "mods"
        with mock.patch.dict(os.environ, {"MKGA_BUNDLED": str(out)}):
            code = main(["--registry", str(tmp / "no-such-registry.json"), "--mods-dir", str(mods_dir), "install", mod.id])
        self.assertEqual(code, 0)
        self.assertEqual([m.id for m in list_installed(mods_dir)], [mod.id])

    def test_cli_install_unknown_id_fails_cleanly(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        with mock.patch.dict(os.environ, {"MKGA_BUNDLED": str(tmp)}):
            code = main(["--registry", str(tmp / "no.json"), "--mods-dir", str(tmp / "mods"), "install", "nope"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
