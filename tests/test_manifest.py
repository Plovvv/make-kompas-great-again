import unittest
from pathlib import Path

from mkga.manifest import ManifestError, load_manifest, parse_manifest
from tests.helpers import good_manifest

ROOT = Path(__file__).resolve().parent.parent


class ManifestTests(unittest.TestCase):
    def test_valid(self):
        m = parse_manifest(good_manifest())
        self.assertEqual(m.id, "demo-mod")
        self.assertEqual(m.kompas_versions, (23, 24))

    def test_missing_required(self):
        for key in ("id", "name", "version", "description", "author", "license", "kind", "entry"):
            data = good_manifest()
            del data[key]
            with self.assertRaises(ManifestError, msg=key):
                parse_manifest(data)

    def test_bad_id(self):
        for bad in ("Demo", "1demo", "demo-", "d", "demo mod", "demo_mod", "a" * 50):
            with self.assertRaises(ManifestError, msg=bad):
                parse_manifest(good_manifest(id=bad))

    def test_bad_version(self):
        for bad in ("1.0", "v1.0.0", "1.0.0-beta", ""):
            with self.assertRaises(ManifestError, msg=bad):
                parse_manifest(good_manifest(version=bad))

    def test_bad_kind(self):
        with self.assertRaises(ManifestError):
            parse_manifest(good_manifest(kind="plugin"))

    def test_entry_must_be_safe_relative_py(self):
        for bad in ("../evil.py", "/abs/main.py", "C:/main.py", "a/../../b.py", "main.exe", ""):
            with self.assertRaises(ManifestError, msg=bad):
                parse_manifest(good_manifest(entry=bad))

    def test_kompas_versions(self):
        for bad in ([10], ["24"], [True], "24"):
            with self.assertRaises(ManifestError, msg=str(bad)):
                parse_manifest(good_manifest(kompas_versions=bad))

    def test_not_object(self):
        with self.assertRaises(ManifestError):
            parse_manifest([])

    def test_repo_mods_have_valid_manifests(self):
        mods = ROOT / "mods"
        found = 0
        for d in sorted(mods.iterdir()):
            if d.is_dir():
                load_manifest(d)
                found += 1
        self.assertGreaterEqual(found, 2)


if __name__ == "__main__":
    unittest.main()
