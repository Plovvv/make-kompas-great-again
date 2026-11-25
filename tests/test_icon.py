import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mkga.console import ensure_utf8_output
from mkga.ui import icon
from mkga.ui.theme import LIGHT


class IconTests(unittest.TestCase):
    def test_drawing_has_rounded_transparent_corners_and_a_nut(self):
        img = icon.draw_icon(128)
        self.assertEqual(img.alpha_at(0, 0), 0.0)                     # скруглённый угол прозрачен
        self.assertEqual(img.alpha_at(64, 4), 1.0)                    # фон закрашен
        r, g, b, a = img.rgba_at(64, 6)
        self.assertEqual((r, g, b), tuple(int(LIGHT.accent[i:i + 2], 16) for i in (1, 3, 5)))   # фон цвета акцента
        # на радиусе гайки (0.31 * 128 ≈ 40) есть белая обводка: в центре правой грани
        white = [img.rgba_at(64 + dx, 64)[:3] == (255, 255, 255) for dx in range(30, 48)]
        self.assertTrue(any(white))
        self.assertEqual(img.rgba_at(64, 64)[:3], tuple(int(LIGHT.accent[i:i + 2], 16) for i in (1, 3, 5)))  # отверстие

    def test_ico_structure(self):
        data = icon.ico_bytes()
        reserved, kind, count = struct.unpack("<HHH", data[:6])
        self.assertEqual((reserved, kind, count), (0, 1, len(icon.ICO_SIZES)))
        seen = []
        for i in range(count):
            w, h, _, _, planes, bits, size, offset = struct.unpack("<BBBBHHII", data[6 + 16 * i:22 + 16 * i])
            self.assertEqual(data[offset:offset + 8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(len(data[offset:offset + size]), size)
            seen.append(w or 256)                                     # 0 в заголовке значит 256
        self.assertEqual(seen, list(icon.ICO_SIZES))

    def test_write_ico(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = icon.write_ico(Path(tmp) / "sub" / "mkga.ico")
            self.assertTrue(path.exists())
            self.assertGreater(path.stat().st_size, 1000)


class WindowlessStreamsTests(unittest.TestCase):
    def test_missing_streams_are_replaced_so_print_and_argparse_do_not_crash(self):
        # exe без консоли, запущенный двойным щелчком: sys.stdout и sys.stderr равны None
        with mock.patch.object(sys, "stdout", None), mock.patch.object(sys, "stderr", None):
            ensure_utf8_output()
            self.assertIsNotNone(sys.stdout)
            self.assertIsNotNone(sys.stderr)
            print("русский текст в никуда")                          # не падает
            sys.stderr.write("ошибка\n")


if __name__ == "__main__":
    unittest.main()
