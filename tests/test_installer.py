import tempfile
import unittest
import zipfile
from pathlib import Path

from mkga.installer import (
    InstallError, install_zip, list_installed, sha256_file, uninstall,
)
from tests.helpers import good_manifest, make_zip


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.mods = self.tmp / "mods"

    def tearDown(self):
        self._tmp.cleanup()

    def test_install_list_uninstall(self):
        z = make_zip(self.tmp / "a.zip", good_manifest())
        m = install_zip(z, self.mods, expected_id="demo-mod", expected_sha256=sha256_file(z))
        self.assertEqual(m.id, "demo-mod")
        self.assertTrue((self.mods / "demo-mod" / "main.py").is_file())
        self.assertEqual([x.id for x in list_installed(self.mods)], ["demo-mod"])
        self.assertTrue(uninstall("demo-mod", self.mods))
        self.assertEqual(list_installed(self.mods), [])
        self.assertFalse(uninstall("demo-mod", self.mods))

    def test_single_top_folder(self):
        z = make_zip(self.tmp / "a.zip", good_manifest(), prefix="demo-mod-v1/")
        install_zip(z, self.mods)
        self.assertTrue((self.mods / "demo-mod" / "mkga-mod.json").is_file())

    def test_update_replaces_old_version(self):
        install_zip(make_zip(self.tmp / "a.zip", good_manifest(), extra={"old.txt": "x"}), self.mods)
        install_zip(make_zip(self.tmp / "b.zip", good_manifest(version="2.0.0")), self.mods)
        self.assertFalse((self.mods / "demo-mod" / "old.txt").exists())
        self.assertEqual(list_installed(self.mods)[0].version, "2.0.0")
        self.assertEqual([p.name for p in self.mods.iterdir()], ["demo-mod"])  # без временных папок

    def test_wrong_hash(self):
        z = make_zip(self.tmp / "a.zip", good_manifest())
        with self.assertRaisesRegex(InstallError, "хеш"):
            install_zip(z, self.mods, expected_sha256="0" * 64)
        self.assertFalse((self.mods / "demo-mod").exists())

    def test_wrong_id(self):
        z = make_zip(self.tmp / "a.zip", good_manifest())
        with self.assertRaisesRegex(InstallError, "id"):
            install_zip(z, self.mods, expected_id="other")

    def test_zip_slip_rejected(self):
        z = make_zip(self.tmp / "a.zip", good_manifest(), extra={"../evil.txt": "x"})
        with self.assertRaisesRegex(InstallError, "небезопасный"):
            install_zip(z, self.mods)
        self.assertFalse((self.tmp / "evil.txt").exists())

    def test_absolute_path_rejected(self):
        z = make_zip(self.tmp / "a.zip", good_manifest(), extra={"/abs.txt": "x"})
        with self.assertRaises(InstallError):
            install_zip(z, self.mods)

    def test_missing_entry_and_manifest(self):
        z = self.tmp / "a.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("readme.txt", "no manifest")
        with self.assertRaises(InstallError):
            install_zip(z, self.mods)
        z2 = self.tmp / "b.zip"
        import json
        with zipfile.ZipFile(z2, "w") as zf:
            zf.writestr("mkga-mod.json", json.dumps(good_manifest()))
        with self.assertRaisesRegex(InstallError, "entry"):
            install_zip(z2, self.mods)

    def test_not_a_zip(self):
        p = self.tmp / "a.zip"
        p.write_text("not a zip")
        with self.assertRaisesRegex(InstallError, "zip"):
            install_zip(p, self.mods)


if __name__ == "__main__":
    unittest.main()
