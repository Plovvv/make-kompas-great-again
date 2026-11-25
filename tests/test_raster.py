import struct
import unittest
import zlib

from mkga.ui.raster import Image, parse_color


class RasterTests(unittest.TestCase):
    def test_rounded_rect_corners_transparent_center_opaque(self):
        img = Image(40, 40)
        img.rrect(0, 0, 40, 40, radius=12, fill="#FFFFFF")
        self.assertEqual(img.alpha_at(0, 0), 0.0)          # угол срезан
        self.assertEqual(img.alpha_at(20, 20), 1.0)        # середина залита
        self.assertEqual(img.alpha_at(20, 0), 1.0)         # прямая часть края
        self.assertEqual(img.alpha_at(39, 39), 0.0)

    def test_edge_is_antialiased(self):
        img = Image(40, 40)
        img.circle(20, 20, 15, fill="#FF0000")
        partial = [img.alpha_at(x, 20) for x in range(40) if 0.0 < img.alpha_at(x, 20) < 1.0]
        self.assertTrue(partial)  # на границе есть промежуточные значения прозрачности

    def test_border_and_fill_colors(self):
        img = Image(30, 30)
        img.rrect(0, 0, 30, 30, radius=6, fill="#FFFFFF", border="#FF0000", border_w=2)
        self.assertEqual(img.rgba_at(15, 0)[:3], (255, 0, 0))     # рамка
        self.assertEqual(img.rgba_at(15, 15), (255, 255, 255, 255))  # заливка

    def test_transparent_fill_keeps_only_ring(self):
        img = Image(30, 30)
        img.rrect(0, 0, 30, 30, radius=6, fill=None, border="#000000", border_w=2)
        self.assertEqual(img.alpha_at(15, 15), 0.0)
        self.assertEqual(img.alpha_at(15, 0), 1.0)

    def test_polyline_draws_stroke(self):
        img = Image(20, 20)
        img.polyline([(4, 10), (8, 14), (16, 5)], width=2.5, color="#FFFFFF")
        self.assertGreater(img.alpha_at(8, 14), 0.9)
        self.assertEqual(img.alpha_at(1, 1), 0.0)

    def test_stretched_keeps_corners_and_grows_middle(self):
        small = Image(26, 26)
        small.rrect(0, 0, 26, 26, radius=12, fill="#FFFFFF", border="#FF0000", border_w=2)
        big = small.stretched(12, 140, 90)
        self.assertEqual((big.w, big.h), (140, 90))
        for (x, y), (sx, sy) in {(0, 0): (0, 0), (139, 0): (25, 0), (0, 89): (0, 25), (139, 89): (25, 25)}.items():
            self.assertEqual(big.rgba_at(x, y), small.rgba_at(sx, sy))   # углы как в исходнике
        self.assertEqual(big.rgba_at(70, 45), (255, 255, 255, 255))      # середина залита
        self.assertEqual(big.rgba_at(70, 0)[:3], (255, 0, 0))            # рамка тянется вдоль края
        self.assertEqual(big.rgba_at(70, 89)[:3], (255, 0, 0))

    def test_stretched_rejects_bad_arguments(self):
        small = Image(26, 26)
        with self.assertRaises(ValueError):
            small.stretched(13, 80, 80)    # нет середины
        with self.assertRaises(ValueError):
            small.stretched(12, 20, 80)    # уменьшать нельзя

    def test_png_is_valid(self):
        img = Image(5, 3)
        img.rrect(0, 0, 5, 3, radius=1, fill="#336699")
        png = img.to_png()
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        pos, chunks = 8, {}
        while pos < len(png):
            (length,) = struct.unpack(">I", png[pos:pos + 4])
            tag, data = png[pos + 4:pos + 8], png[pos + 8:pos + 8 + length]
            (crc,) = struct.unpack(">I", png[pos + 8 + length:pos + 12 + length])
            self.assertEqual(crc, zlib.crc32(tag + data) & 0xFFFFFFFF, tag)
            chunks[tag] = data
            pos += 12 + length
        self.assertEqual(struct.unpack(">II", chunks[b"IHDR"][:8]), (5, 3))
        raw = zlib.decompress(chunks[b"IDAT"])
        self.assertEqual(len(raw), 3 * (1 + 5 * 4))

    def test_color_parsing_and_errors(self):
        self.assertEqual(parse_color("#0A0b0C"), (10, 11, 12))
        with self.assertRaises(ValueError):
            parse_color("red")
        with self.assertRaises(ValueError):
            Image(0, 5)


if __name__ == "__main__":
    unittest.main()
