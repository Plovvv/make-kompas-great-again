"""ЖИВАЯ проверка слоя построения моделей: тела сверяются по массе/объёму с расчётом по формуле.

    $env:MKGA_LIVE_KOMPAS = "1"; python -m unittest tests.test_live_model3d -v

Пропускается без MKGA_LIVE_KOMPAS=1. Нужен запущенный КОМПАС. Каждый тест создаёт свой скрытый документ-деталь
и закрывает его без сохранения; документы пользователя не трогаются. Проверено на КОМПАС-3D v24.
"""

import math
import os
import unittest

LIVE = os.environ.get("MKGA_LIVE_KOMPAS") == "1"
TOL = 1e-6


@unittest.skipUnless(LIVE, "живая проверка: задайте MKGA_LIVE_KOMPAS=1 и запустите КОМПАС")
class LiveModel3dTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from mkga.core.kompas import connect
        cls.k = connect()

    def setUp(self):
        from mkga.core.model3d import Part
        self.count = self.k.app7.Documents.Count
        self.part = Part.new(self.k)

    def tearDown(self):
        self.part.close()
        self.assertEqual(self.k.app7.Documents.Count, self.count)   # тест не оставил документов

    # --- вспомогательное -------------------------------------------------------------------------
    def disc(self, r=10.0, plane="XOY"):
        with self.part.sketch(plane) as sk:
            sk.circle(0, 0, r)
        return sk

    # --- выдавливание ------------------------------------------------------------------------------
    def test_cylinder(self):
        self.part.extrude(self.disc(10), 20)
        self.part.verify_volume(math.pi * 10 ** 2 * 20, TOL)

    def test_through_hole_cut_both_directions(self):
        self.part.extrude(self.disc(10), 20)
        self.part.cut_extrude(self.disc(3), direction="both")           # сквозь всё в обе стороны
        self.part.verify_volume(math.pi * (10 ** 2 - 3 ** 2) * 20, TOL)

    def test_blind_cut_from_the_sketch_plane(self):
        self.part.extrude(self.disc(10), 20)
        self.part.cut_extrude(self.disc(3), 5)                           # слепое отверстие глубиной 5 от z=0 по нормали (в тело)
        self.part.verify_volume(math.pi * 10 ** 2 * 20 - math.pi * 3 ** 2 * 5, TOL)

    def test_through_all_cut_along_the_normal(self):
        self.part.extrude(self.disc(10), 20)
        self.part.cut_extrude(self.disc(3))                              # сквозной вырез в одну сторону по нормали
        self.part.verify_volume(math.pi * (10 ** 2 - 3 ** 2) * 20, TOL)

    def test_reverse_body_and_reverse_blind_cut(self):
        self.part.extrude(self.disc(10), 20, direction="reverse")        # тело ниже плоскости (z от -20 до 0)
        self.part.verify_volume(math.pi * 10 ** 2 * 20, TOL)
        self.part.cut_extrude(self.disc(3), 5, direction="reverse")      # режет против нормали, внутрь тела
        self.part.verify_volume(math.pi * 10 ** 2 * 20 - math.pi * 3 ** 2 * 5, TOL)

    def test_symmetric_cut_total_thickness(self):
        self.part.extrude(self.disc(10), 20, direction="middle")
        self.part.cut_extrude(self.disc(3), 6, direction="middle")
        self.part.verify_volume(math.pi * 10 ** 2 * 20 - math.pi * 3 ** 2 * 6, TOL)

    def test_hexagon_prism_across_flats(self):
        with self.part.sketch() as sk:
            sk.regular_polygon(6, across_flats=17)
        self.part.extrude(sk, 8)
        self.part.verify_volume(math.sqrt(3) / 2 * 17 ** 2 * 8, TOL)

    def test_rectangle_prism(self):
        with self.part.sketch("XOZ") as sk:
            sk.rect(0, 0, 30, 12)
        self.part.extrude(sk, 5)
        self.part.verify_volume(30 * 12 * 5, TOL)

    def test_bolt_hex_head_plus_shank_boss_reverse(self):
        with self.part.sketch() as head:
            head.regular_polygon(6, across_flats=17)
        self.part.extrude(head, 8)                                       # основание: головка вверх
        self.part.extrude(self.disc(5), 30, direction="reverse")         # приклеивание: стержень вниз
        hexagon = math.sqrt(3) / 2 * 17 ** 2 * 8
        self.part.verify_volume(hexagon + math.pi * 5 ** 2 * 30, TOL)

    def test_direction_both_with_different_depths(self):
        self.part.extrude(self.disc(10), 10, direction="both", depth2=4)
        self.part.verify_volume(math.pi * 10 ** 2 * 14, TOL)

    def test_direction_middle_plane_depth_is_total_thickness(self):
        self.part.extrude(self.disc(10), 12, direction="middle")
        self.part.verify_volume(math.pi * 10 ** 2 * 12, TOL)

    # --- вращение ------------------------------------------------------------------------------------
    def test_revolved_stepped_profile(self):
        with self.part.sketch() as sk:
            sk.polyline([(0, 0), (8, 0), (8, 6), (4, 6), (4, 26), (0, 26)])
        self.part.revolve(sk, axis="OY")
        self.part.verify_volume(math.pi * 8 ** 2 * 6 + math.pi * 4 ** 2 * 20, TOL)

    def test_revolve_half_turn(self):
        with self.part.sketch() as sk:
            sk.rect(0, 0, 10, 20)
        self.part.revolve(sk, angle=180)
        self.part.verify_volume(math.pi * 10 ** 2 * 20 / 2, TOL)

    def test_revolved_groove_cut(self):
        with self.part.sketch() as body:
            body.rect(0, 0, 10, 30)
        self.part.revolve(body)                                           # цилиндр R10 H30
        with self.part.sketch() as groove:
            groove.rect(8, 10, 2, 5)                                      # канавка глубиной 2, шириной 5
        self.part.revolve(groove, cut=True)
        self.part.verify_volume(math.pi * 10 ** 2 * 30 - math.pi * (10 ** 2 - 8 ** 2) * 5, TOL)

    # --- свойства -------------------------------------------------------------------------------------
    def test_properties_and_material_change_mass(self):
        self.part.extrude(self.disc(10), 20)
        self.part.set_properties(name="Тестовый цилиндр", marking="СНАБ.000000.001", material="Сталь 45", density=7.85)
        self.assertEqual((self.part.top.Name, self.part.top.Marking), ("Тестовый цилиндр", "СНАБ.000000.001"))
        self.assertAlmostEqual(self.part.density, 7.85)
        self.assertAlmostEqual(self.part.mass_g, math.pi * 10 ** 2 * 20 / 1000 * 7.85, places=6)

    # --- ошибки КОМПАСа становятся понятными -------------------------------------------------------------
    def test_save_as_of_a_built_part_roundtrip(self):
        import tempfile
        from pathlib import Path
        from mkga.core.safe_io import BackupStore
        self.part.extrude(self.disc(10), 20)
        with tempfile.TemporaryDirectory() as tmp:
            store = BackupStore(Path(tmp) / "b", trash=lambda p: p.unlink())
            target = Path(tmp) / "цилиндр.m3d"
            with store.begin("live", "сохранить деталь") as s:
                self.part.save_as(s, target)
                sid = s.info.id
            self.assertGreater(target.stat().st_size, 1000)
            self.assertTrue(store.undo(sid).ok)
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
