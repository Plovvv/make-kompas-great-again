import json
import tempfile
import unittest
from pathlib import Path

from mkga.registry import RegistryError, load_registry, parse_registry, search

H = "a" * 64


def entry(**kw):
    d = {"id": "fasteners", "name": "Метизы", "description": "Винты и гайки DIN",
         "repo": "owner/repo", "tag": "v0.1.0", "sha256": H, "tags": ["catalog"]}
    d.update(kw)
    return d


class RegistryTests(unittest.TestCase):
    def test_parse_and_url(self):
        (e,) = parse_registry({"schema": 1, "mods": [entry()]})
        self.assertEqual(e.asset_name, "fasteners-v0.1.0.zip")
        self.assertEqual(e.download_url,
                         "https://github.com/owner/repo/releases/download/v0.1.0/fasteners-v0.1.0.zip")

    def test_bad_schema(self):
        for bad in ({"schema": 2, "mods": []}, {"mods": []}, [], {"schema": 1, "mods": {}}):
            with self.assertRaises(RegistryError):
                parse_registry(bad)

    def test_bad_entries(self):
        for kw in ({"sha256": "xyz"}, {"sha256": H.upper()}, {"repo": "no-slash"}, {"id": "Bad"},
                   {"tag": ""}, {"tags": "catalog"}):
            with self.assertRaises(RegistryError, msg=str(kw)):
                parse_registry({"schema": 1, "mods": [entry(**kw)]})

    def test_duplicate_id(self):
        with self.assertRaises(RegistryError):
            parse_registry({"schema": 1, "mods": [entry(), entry()]})

    def test_search(self):
        entries = parse_registry({"schema": 1, "mods": [
            entry(), entry(id="converter", name="Конвертер v22", description="Перевод в старую версию", tags=[])]})
        self.assertEqual([e.id for e in search(entries, "")], ["fasteners", "converter"])
        self.assertEqual([e.id for e in search(entries, "винты din")], ["fasteners"])
        self.assertEqual([e.id for e in search(entries, "КОНВЕРТЕР")], ["converter"])
        self.assertEqual(search(entries, "нет такого"), [])

    def test_load_file_and_bad_json(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "r.json"
            p.write_text(json.dumps({"schema": 1, "mods": [entry()]}), encoding="utf-8")
            self.assertEqual(len(load_registry(p)), 1)
            p.write_text("{oops", encoding="utf-8")
            with self.assertRaises(RegistryError):
                load_registry(p)

    def test_repo_registry_is_valid(self):
        root = Path(__file__).resolve().parent.parent
        load_registry(root / "registry" / "registry.json")


if __name__ == "__main__":
    unittest.main()
