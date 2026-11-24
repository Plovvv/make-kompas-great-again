import tempfile
import unittest
from pathlib import Path

from mkga.guard import check_path, check_source, violations

ROOT = Path(__file__).resolve().parent.parent


def bad(src: str) -> list[str]:
    return [f.message for f in violations(check_source(src))]


class GuardTests(unittest.TestCase):
    # --- должно ловиться ---------------------------------------------------------
    def test_open_for_write_variants(self):
        self.assertTrue(bad("open('a.txt', 'w')"))
        self.assertTrue(bad("open('a.txt', mode='a')"))
        self.assertTrue(bad("open('a.bin', 'rb+')"))
        self.assertTrue(bad("import io\nio.open('a', 'x')"))
        self.assertTrue(bad("from pathlib import Path\nPath('a').open('w')"))

    def test_open_with_unknown_mode_is_flagged(self):
        self.assertTrue(bad("m = 'w'\nopen('a', m)"))

    def test_os_and_shutil_and_subprocess(self):
        self.assertTrue(bad("import os\nos.remove('a')"))
        self.assertTrue(bad("import os\nos.unlink('a')"))
        self.assertTrue(bad("import os\nos.system('del a')"))
        self.assertTrue(bad("import shutil\nshutil.rmtree('d')"))
        self.assertTrue(bad("import shutil\nshutil.copy('a', 'b')"))
        self.assertTrue(bad("import subprocess\nsubprocess.run(['x'])"))

    def test_aliases_are_resolved(self):
        self.assertTrue(bad("import os as o\no.remove('a')"))
        self.assertTrue(bad("from os import remove as rm\nrm('a')"))
        self.assertTrue(bad("from shutil import rmtree\nrmtree('d')"))

    def test_path_methods(self):
        for call in ("p.write_text('x')", "p.write_bytes(b'x')", "p.unlink()", "p.rmdir()",
                     "p.rename('b')", "p.touch()"):
            self.assertTrue(bad(f"p = object()\n{call}"), call)

    def test_kompas_direct_save(self):
        for call in ("doc.Save()", "doc.SaveAs('a.m3d')", "doc.SaveAsEx('a')",
                     "api5.ksSaveDocument('a')", "doc.SaveAsToRasterFormat('a')"):
            self.assertTrue(bad(call), call)

    # --- не должно ловиться ----------------------------------------------------------
    def test_reading_is_fine(self):
        self.assertEqual(bad("open('a.txt')\nopen('a.bin', 'rb')\nopen('a', mode='r')"), [])
        self.assertEqual(bad("import os\nos.path.join('a', 'b')\nos.listdir('.')"), [])
        self.assertEqual(bad("from pathlib import Path\nPath('a').read_text()\nPath('a').exists()"), [])

    def test_unrelated_calls_are_fine(self):
        self.assertEqual(bad("s = 'abc'.replace('a', 'b')\nwebbrowser.open('https://example.com')"), [])
        self.assertEqual(bad("ctx.log('Saved')\nd = {}\nd.get('Save')"), [])

    def test_session_api_is_fine(self):
        src = (
            "def run(ctx):\n"
            "    with ctx.session('x') as s:\n"
            "        s.write_text(path, 'data')\n"
            "        s.delete(old)\n"
            "        k.save_as(s, doc, path)\n"
        )
        self.assertEqual(bad(src), [])

    def test_session_exemption_is_only_for_real_session_objects(self):
        # имя `s` не освобождает от проверки, если оно не получено из .session()/.begin()
        self.assertTrue(bad("s = Path('a')\ns.write_text('x')"))
        # а присваивание сессии без with тоже считается
        self.assertEqual(bad("s = ctx.session('x')\ns.write_text(p, 'x')"), [])

    # --- разрешение с причиной -------------------------------------------------------
    def test_allow_marker_moves_finding_to_review_list(self):
        src = "import os\nos.remove('a')  # mkga: allow-unsafe-io (временный файл мода)\n"
        findings = check_source(src)
        self.assertEqual(len(findings), 1)
        self.assertTrue(findings[0].allowed)
        self.assertEqual(violations(findings), [])

    def test_syntax_error_is_reported_not_crash(self):
        self.assertTrue(bad("def (:"))

    # --- сам репозиторий -----------------------------------------------------------------
    def test_repo_mods_are_clean(self):
        self.assertEqual([str(f) for f in violations(check_path(ROOT / "mods"))], [])

    def test_check_path_scans_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "ok.py").write_text("x = 1\n", encoding="utf-8")
            (Path(tmp) / "evil.py").write_text("import os\nos.remove('a')\n", encoding="utf-8")
            found = violations(check_path(tmp))
            self.assertEqual([Path(f.file).name for f in found], ["evil.py"])


if __name__ == "__main__":
    unittest.main()
