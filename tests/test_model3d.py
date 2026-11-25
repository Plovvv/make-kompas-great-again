"""Слой построения моделей на фейковой детали: проверяется соответствие параметров и порядок вызовов.
Настоящая геометрия проверяется живыми тестами (tests/test_live_model3d.py)."""

import math
import unittest

from mkga.core import constants as C
from mkga.core.fake import make_fake_kompas
from mkga.core.model3d import ModelError, Part


def new_part():
    k = make_fake_kompas()
    return k, Part.new(k)


class SketchTests(unittest.TestCase):
    def test_circle_and_lines_are_recorded_and_sketch_is_closed(self):
        k, part = new_part()
        with part.sketch("XOZ") as sk:
            sk.circle(1, 2, 5)
            sk.rect(0, 0, 4, 3)
        (raw,) = part.top.sketches
        self.assertEqual(raw.Plane, ("default-object", C.o3d_planeXOZ))
        self.assertTrue(raw.began and raw.ended)
        (circle,) = part.top.features("circle")
        self.assertEqual((circle.Xc, circle.Yc, circle.Radius, circle.Style), (1.0, 2.0, 5.0, 1))
        self.assertEqual(len(part.top.features("line")), 4)

    def test_hexagon_across_flats_has_correct_circumradius(self):
        k, part = new_part()
        with part.sketch() as sk:
            sk.regular_polygon(6, across_flats=17)
        lines = part.top.features("line")
        self.assertEqual(len(lines), 6)
        r = 17 / math.sqrt(3)
        for l in lines:
            self.assertAlmostEqual(math.hypot(l.X1, l.Y1), r, places=9)      # вершины на окружности R
            self.assertAlmostEqual(math.hypot(l.X2 - l.X1, l.Y2 - l.Y1), r, places=9)  # у шестиугольника сторона = R
        self.assertAlmostEqual(lines[0].X1, r)                                # первая вершина на оси X

    def test_sketch_is_closed_even_when_the_body_raises(self):
        k, part = new_part()
        with self.assertRaises(RuntimeError):
            with part.sketch() as sk:
                sk.circle(0, 0, 1)
                raise RuntimeError("сбой в моде")
        self.assertTrue(part.top.sketches[0].ended)

    def test_empty_sketch_and_shapes_outside_with_are_rejected(self):
        k, part = new_part()
        with self.assertRaises(ModelError):
            with part.sketch():
                pass
        sk = part.sketch()
        with self.assertRaises(ModelError):
            sk.circle(0, 0, 1)             # эскиз не открыт

    def test_invalid_shapes(self):
        k, part = new_part()
        with part.sketch() as sk:
            sk.circle(0, 0, 1)
            for bad in (lambda: sk.circle(0, 0, 0), lambda: sk.line(1, 1, 1, 1), lambda: sk.rect(0, 0, -1, 2),
                        lambda: sk.regular_polygon(2, circumradius=1), lambda: sk.regular_polygon(6),
                        lambda: sk.regular_polygon(6, circumradius=1, across_flats=1),
                        lambda: sk.polyline([(0, 0), (1, 1)])):
                with self.assertRaises(ModelError):
                    bad()
        with self.assertRaises(ModelError):
            part.sketch("ABC")


def circle_sketch(part, r=5.0, plane="XOY"):
    with part.sketch(plane) as sk:
        sk.circle(0, 0, r)
    return sk


class ExtrusionTests(unittest.TestCase):
    def test_first_is_base_then_boss(self):
        k, part = new_part()
        part.extrude(circle_sketch(part), 20)
        part.extrude(circle_sketch(part, 3), 5, direction="reverse")
        base, boss = part.top.features("extrusion")
        self.assertEqual((base.args, boss.args), ((C.o3d_baseExtrusion,), (C.o3d_bossExtrusion,)))
        self.assertEqual((base.Direction, boss.Direction), (C.dtNormal, C.dtReverse))
        self.assertEqual(base.calls[0], ("SetSideParameters", (True, C.etBlind, 20.0, 0.0, False, None)))
        # reverse: глубина уходит в параметры ОБРАТНОЙ стороны (так читает КОМПАС, проверено на v24)
        self.assertEqual([c for c in boss.calls if isinstance(c, tuple)],
                         [("SetSideParameters", (False, C.etBlind, 5.0, 0.0, False, None))])
        self.assertIs(base.Sketch, part.top.sketches[0])

    def test_direction_both_sets_both_sides(self):
        k, part = new_part()
        part.extrude(circle_sketch(part), 10, direction="both", depth2=4)
        (ext,) = part.top.features("extrusion")
        sides = [c[1] for c in ext.calls if isinstance(c, tuple)]
        self.assertEqual(sides, [(True, C.etBlind, 10.0, 0.0, False, None), (False, C.etBlind, 4.0, 0.0, False, None)])

    def test_cut_through_all_and_blind(self):
        k, part = new_part()
        part.extrude(circle_sketch(part, 10), 20)
        part.cut_extrude(circle_sketch(part, 3), direction="both")
        part.cut_extrude(circle_sketch(part, 1), 5)
        _, through, blind = part.top.features("extrusion")
        self.assertEqual(through.args, (C.o3d_cutExtrusion,))
        self.assertEqual([c[1][:3] for c in through.calls if isinstance(c, tuple)],
                         [(True, C.etThroughAll, 0.0), (False, C.etThroughAll, 0.0)])
        # normal для выреза: КОМПАС трактует направление наоборот, поэтому уходит reverse с глубиной на обратной стороне
        self.assertEqual(blind.Direction, C.dtReverse)
        self.assertEqual(blind.calls[0][1][:3], (False, C.etBlind, 5.0))

    def test_cut_reverse_maps_to_kompas_normal(self):
        k, part = new_part()
        part.extrude(circle_sketch(part, 10), 20, direction="reverse")
        part.cut_extrude(circle_sketch(part, 3), 4, direction="reverse")
        _, cut = part.top.features("extrusion")
        self.assertEqual(cut.Direction, C.dtNormal)
        self.assertEqual(cut.calls[0][1][:3], (True, C.etBlind, 4.0))

    def test_middle_plane_uses_total_thickness_on_the_normal_side(self):
        k, part = new_part()
        part.extrude(circle_sketch(part), 12, direction="middle")
        (ext,) = part.top.features("extrusion")
        self.assertEqual(ext.Direction, C.dtMiddlePlane)
        self.assertEqual([c[1][:3] for c in ext.calls if isinstance(c, tuple)], [(True, C.etBlind, 12.0)])

    def test_validation(self):
        k, part = new_part()
        sk = circle_sketch(part)
        for bad in (lambda: part.extrude(sk, 0), lambda: part.extrude(sk, None), lambda: part.extrude(sk, -3),
                    lambda: part.extrude(sk, 5, direction="sideways"),
                    lambda: part.cut_extrude(sk)):                     # ещё нечего вырезать
            with self.assertRaises(ModelError):
                bad()
        self.assertEqual(part.top.features("extrusion"), [])           # ничего лишнего не построено

    def test_kompas_refusal_becomes_model_error(self):
        k, part = new_part()
        part.top.update_result = False
        with self.assertRaises(ModelError) as cm:
            part.extrude(circle_sketch(part), 5)
        self.assertIn("выдавливание", str(cm.exception))


class RevolveTests(unittest.TestCase):
    def test_base_boss_cut_kinds_and_indexed_properties(self):
        k, part = new_part()
        part.revolve(circle_sketch(part), axis="OY")
        part.revolve(circle_sketch(part), axis="OX", angle=90)
        part.revolve(circle_sketch(part), cut=True)
        base, boss, cut = part.top.features("rotated")
        self.assertEqual((base.args, boss.args, cut.args),
                         ((C.o3d_baseRotated,), (C.o3d_bossRotated,), (C.o3d_cutRotated,)))
        self.assertEqual(base.Axis, ("default-object", C.o3d_axisOY))
        self.assertEqual(boss.Axis, ("default-object", C.o3d_axisOX))
        self.assertEqual([c for c in base.calls if c[0] == "put"],
                         [("put", "RotatedType", (True, C.ksRTAngle)), ("put", "Angle", (True, 360.0))])
        self.assertEqual([c for c in boss.calls if c[0] == "put"][1], ("put", "Angle", (True, 90.0)))

    def test_validation(self):
        k, part = new_part()
        sk = circle_sketch(part)
        for bad in (lambda: part.revolve(sk, axis="OW"), lambda: part.revolve(sk, angle=0),
                    lambda: part.revolve(sk, angle=361), lambda: part.revolve(sk, cut=True)):
            with self.assertRaises(ModelError):
                bad()


class PropertiesAndMeasureTests(unittest.TestCase):
    def test_set_properties(self):
        k, part = new_part()
        part.set_properties(name="Втулка", marking="СНАБ.123456.001", material="Сталь 45", density=7.85)
        self.assertEqual((part.top.Name, part.top.Marking, part.top.Material, part.top.Density),
                         ("Втулка", "СНАБ.123456.001", "Сталь 45", 7.85))
        for bad in (dict(material="Сталь"), dict(density=7.8)):
            with self.assertRaises(ModelError):
                part.set_properties(**bad)
        part.top.material_accepted = False
        with self.assertRaises(ModelError):
            part.set_properties(material="Неизвестный", density=1.0)

    def test_volume_from_mass_and_density(self):
        k, part = new_part()
        part.top.Density = 7.856
        part.top.fake_mass_g = 49.36070377320305           # цилиндр R10 H20 из живой проверки
        self.assertAlmostEqual(part.volume_mm3, math.pi * 10 ** 2 * 20, places=6)

    def test_verify_volume_passes_and_fails(self):
        k, part = new_part()
        part.top.Density = 7.856
        part.top.fake_mass_g = 49.36070377320305
        expected = math.pi * 10 ** 2 * 20
        self.assertAlmostEqual(part.verify_volume(expected), expected, places=6)
        with self.assertRaises(ModelError) as cm:
            part.verify_volume(expected * 1.01)
        self.assertIn("отличается от расчётного", str(cm.exception))
        with self.assertRaises(ModelError):
            part.verify_volume(0)

    def test_zero_density_is_an_error_not_a_division(self):
        k, part = new_part()
        part.top.Density = 0.0
        with self.assertRaises(ModelError):
            part.volume_mm3


class LifecycleTests(unittest.TestCase):
    def test_context_manager_closes_without_saving(self):
        k = make_fake_kompas()
        before = k.app7.Documents.Count
        with Part.new(k) as part:
            self.assertEqual(k.app7.Documents.Count, before + 1)
            doc = part.doc
        self.assertEqual(k.app7.Documents.Count, before)
        self.assertEqual(doc.closed_with, 0)       # kdDoNotSaveChanges

    def test_closed_even_when_building_fails(self):
        k = make_fake_kompas()
        before = k.app7.Documents.Count
        with self.assertRaises(ModelError):
            with Part.new(k) as part:
                part.extrude(circle_sketch(part), 0)
        self.assertEqual(k.app7.Documents.Count, before)

    def test_save_as_goes_through_the_session(self):
        import tempfile
        from pathlib import Path
        from mkga.core.safe_io import BackupStore
        k = make_fake_kompas()
        with tempfile.TemporaryDirectory() as tmp, Part.new(k) as part:
            store = BackupStore(Path(tmp) / "b", trash=lambda p: p.unlink())
            target = Path(tmp) / "деталь.m3d"
            with store.begin("t", "сохранить") as s:
                part.save_as(s, target)
                sid = s.info.id
            self.assertTrue(target.exists())
            self.assertTrue(store.undo(sid).ok)
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
