"""Регресс: на Windows в CI вывод русского текста в трубу падал с UnicodeEncodeError (cp1252)."""

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONIOENCODING="cp1252")  # как в консоли GitHub Actions на Windows
    return subprocess.run([sys.executable, *args], cwd=ROOT, env=env, capture_output=True)


class ConsoleEncodingTests(unittest.TestCase):
    def test_validate_registry_prints_russian_into_pipe(self):
        r = run("tools/validate_registry.py")
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
        self.assertIn("записей".encode("utf-8"), r.stdout)

    def test_cli_prints_russian_into_pipe(self):
        r = run("-m", "mkga", "check", "mods")
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
        self.assertIn("Нарушений".encode("utf-8"), r.stdout)

    def test_ensure_utf8_output_survives_streams_without_reconfigure(self):
        import io
        from unittest import mock
        from mkga.console import ensure_utf8_output
        with mock.patch.object(sys, "stdout", io.StringIO()), mock.patch.object(sys, "stderr", None):
            ensure_utf8_output()  # не падает


if __name__ == "__main__":
    unittest.main()
