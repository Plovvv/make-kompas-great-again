"""Тесты мода «Каталог комплектующих» без КОМПАС: формулы, каталог, имена, чертежи, сборщик на фейке, окно.

Живую проверку построения (объём, резьба, свойства, файлы) делает tests/test_live_components.py.
"""

import gc
import json
import math
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

from tests.test_ui import display_available

MOD_DIR = Path(__file__).resolve().parent.parent / "mods" / "components"
DATA = MOD_DIR / "data"


def setUpModule():
    sys.path.insert(0, str(MOD_DIR))


def tearDownModule():
    sys.path.remove(str(MOD_DIR))
    for name in [n for n in sys.modules if n.startswith("mkga_components")]:
        del sys.modules[name]


def catalog(user=None):
    from mkga_components.catalog import load_catalog
    return load_catalog(DATA, user)


class ShapeMathTests(unittest.TestCase):
    def test_revolved_volume_of_a_cylinder_and_a_ring(self):
        from mkga_components.shapes import revolved_volume
        self.assertAlmostEqual(revolved_volume([(0, 0), (5, 0), (5, -10), (0, -10)]), math.pi * 25 * 10, places=9)
        self.assertAlmostEqual(revolved_volume([(3, 0), (5, 0), (5, -2), (3, -2)]), math.pi * (25 - 9) * 2, places=9)

    def test_hexagon_area(self):
        from mkga_components.shapes import hexagon_area
        self.assertAlmostEqual(hexagon_area(13), 6 * (13 / math.sqrt(3)) ** 2 * math.sqrt(3) / 4, places=9)

    def test_chamfer_volume_matches_a_brute_force_grid(self):
        from mkga_components.shapes import TAN30, hex_chamfer_volume
        s, dw = 13.0, 11.3
        n, ext = 500, 7.6                               # чистый Python (numpy в CI нет): сетка 500x500
        step = 2 * ext / n
        grid = 0.0
        for i in range(n):
            x = -ext + (i + 0.5) * step
            for j in range(n):
                z = -ext + (j + 0.5) * step
                if all(abs(x * math.cos(a) + z * math.sin(a)) <= s / 2 for a in (math.pi / 2, math.pi * 5 / 6, math.pi * 7 / 6)):
                    r = math.hypot(x, z)
                    if r > dw / 2:
                        grid += (r - dw / 2) * TAN30 * step * step
        self.assertAlmostEqual(hex_chamfer_volume(s, dw), grid, delta=grid * 1.5e-2)

    def test_chamfer_that_starts_beyond_the_corners_removes_nothing(self):
        from mkga_components.shapes import hex_chamfer_volume
        self.assertEqual(hex_chamfer_volume(13, 20), 0.0)

    def test_notch_area_integrates_the_hyperbola(self):
        from mkga_components.shapes import TAN30, hex_flat_notch_area
        a, r0, side = 6.5, 5.65, 13 / math.sqrt(3)
        n = 100000
        h = side / n
        brute = sum((math.hypot(a, -side / 2 + (i + 0.5) * h) - r0) * TAN30 * h for i in range(n))
        self.assertAlmostEqual(hex_flat_notch_area(13, 11.3), brute, places=6)

    def test_strip_area_of_the_washer_gap(self):
        from mkga_components.shapes import _strip_area
        r1, r2, gap = 4.05, 7.05, 2.0
        n = 200000
        h = gap / n
        brute = sum((math.sqrt(r2 ** 2 - z ** 2) - math.sqrt(r1 ** 2 - z ** 2)) * h
                    for z in (-gap / 2 + (i + 0.5) * h for i in range(n)))
        self.assertAlmostEqual(_strip_area(r1, r2, gap), brute, places=6)

    def test_spring_washer_volume_is_the_ring_minus_the_gap(self):
        from mkga_components.shapes import SHAPES, _strip_area
        dims = dict(d1=8.1, b=3, s=2)
        ring = math.pi * ((8.1 / 2 + 3) ** 2 - (8.1 / 2) ** 2) * 2
        self.assertLess(SHAPES["washer_spring"].volume(dims, None), ring)
        self.assertAlmostEqual(ring - SHAPES["washer_spring"].volume(dims, None), _strip_area(4.05, 7.05, 2) * 2, places=9)

    def test_flange_screw_rejects_a_flange_smaller_than_the_dome(self):
        from mkga_components.shapes import SHAPES, ShapeError
        good = dict(d=8, P=1.25, dk=13.2, dc=17.8, k=4.4, c=1.5, s=5, t=2.6)
        SHAPES["flange_button_screw"].check(good, 20)
        for bad in (dict(good, dc=12), dict(good, c=5), dict(good, s=12)):
            with self.assertRaises(ShapeError):
                SHAPES["flange_button_screw"].check(bad, 20)

    def test_hex_bolt_thread_length_follows_the_length_ranges(self):
        from mkga_components.shapes import hex_bolt_thread_length
        dims = dict(b=22, b2=28, b3=41)
        self.assertEqual(hex_bolt_thread_length(dims, 50), 22)
        self.assertEqual(hex_bolt_thread_length(dims, 125), 22)
        self.assertEqual(hex_bolt_thread_length(dims, 150), 28)
        self.assertEqual(hex_bolt_thread_length(dims, 250), 41)
        self.assertIsNone(hex_bolt_thread_length(dims, 20))          # b не меньше длины: резьба на всю длину
        self.assertIsNone(hex_bolt_thread_length({}, 50))            # DIN 933: резьба на всю длину

    def test_hex_bolt_and_nyloc_volumes_are_consistent(self):
        from mkga_components.shapes import SHAPES, hexagon_area, hex_chamfer_volume, internal_minor_diameter
        bolt = dict(d=8, P=1.25, s=13, k=5.3, dw=11.7)
        v = SHAPES["hex_bolt"].volume(bolt, 40)
        head = hexagon_area(13) * 5.3 - hex_chamfer_volume(13, 11.7)
        self.assertGreater(v, head + math.pi * 3.5 ** 2 * 38)       # стержень не короче 38 мм
        self.assertLess(v, head + math.pi * 4 ** 2 * 40)
        nut = dict(d=8, P=1.25, s=13, m=5.5, h=8, dw=11.7)
        plain = SHAPES["nut_hex"].volume(nut, None)          # та же гайка без буртика и с фаской с двух сторон
        collar = math.pi * (11.7 / 2) ** 2 * 2.5 - math.pi * (internal_minor_diameter(8, 1.25) / 2) ** 2 * 2.5
        self.assertAlmostEqual(SHAPES["nut_nyloc"].volume(nut, None), plain + hex_chamfer_volume(13, 11.7) + collar, places=6)

    def test_hex_bolt_and_nyloc_reject_inconsistent_sizes(self):
        from mkga_components.shapes import SHAPES, ShapeError
        with self.assertRaises(ShapeError):
            SHAPES["hex_bolt"].check(dict(d=8, P=1.25, s=13, k=5.3, dw=14), 40)
        with self.assertRaises(ShapeError):
            SHAPES["nut_nyloc"].check(dict(d=8, P=1.25, s=13, m=8, h=8, dw=11.7), None)

    def test_dome_pocket_correction_is_positive_and_small(self):
        from mkga_components.shapes import dome_pocket_correction
        v = dome_pocket_correction(5, 7.768)
        self.assertTrue(0 < v < 10)
        self.assertAlmostEqual(v, 4.9366, places=3)

    def test_internal_thread_bore(self):
        from mkga_components.shapes import internal_minor_diameter
        self.assertAlmostEqual(internal_minor_diameter(8, 1.25), 6.6469, places=3)

    def test_shapes_reject_impossible_sizes(self):
        from mkga_components.shapes import SHAPES, ShapeError
        good = dict(d=8, P=1.25, dk=13, k=8, s=6, t=4)
        SHAPES["cap_screw"].check(good, 25)
        for bad, length in ((dict(good, s=12), 25), (dict(good, t=9), 25), (good, None), (good, 1.0), (dict(good, d=-1), 25)):
            with self.assertRaises(ShapeError):
                SHAPES["cap_screw"].check(bad, length)
        with self.assertRaises(ShapeError):
            SHAPES["washer_flat"].check(dict(d1=10, d2=8, h=1), None)
        with self.assertRaises(ShapeError):
            SHAPES["nut_hex"].check(dict(d=8, P=1.25, s=13, m=6.5), None)     # нет dw


class NameOverrideTests(unittest.TestCase):
    def test_parse_and_serialize_roundtrip_ignores_junk(self):
        from mkga_components.catalog import parse_name_overrides, serialize_name_overrides
        data = parse_name_overrides('{"din-912": {"number": " ISO 4762 ", "x": "y", "kind_name": ""}, "bad": 5}')
        self.assertEqual(data, {"din-912": {"number": "ISO 4762"}})
        self.assertEqual(parse_name_overrides(serialize_name_overrides(data)), data)
        self.assertEqual(parse_name_overrides(""), {})
        with self.assertRaises(ValueError):
            parse_name_overrides("[1]")

    def test_catalog_applies_overrides_and_remembers_the_defaults(self):
        import tempfile
        from mkga_components.catalog import load_catalog
        with tempfile.TemporaryDirectory() as tmp:
            names = Path(tmp) / "names.json"
            names.write_text('{"din-912": {"number": "ISO 4762", "full_name": "Винт цилиндрический"}, "no-such": {"number": "X"}}',
                             encoding="utf-8")
            c = load_catalog(DATA, None, names)
        std = c.standards["din-912"]
        self.assertEqual((std.number, std.full_name, std.kind_name), ("ISO 4762", "Винт цилиндрический", "Винт"))
        self.assertEqual(std.defaults[0], "DIN 912")
        self.assertEqual(std.names("M8", 25).title, "Винт цилиндрический ISO 4762 - M8 x 25")
        self.assertNotIn("no-such", c.name_overrides)
        self.assertFalse(c.standards["din-934"].is_renamed)

    def test_broken_names_file_is_reported_but_does_not_break_the_catalog(self):
        import tempfile
        from mkga_components.catalog import load_catalog
        with tempfile.TemporaryDirectory() as tmp:
            names = Path(tmp) / "names.json"
            names.write_text("{oops", encoding="utf-8")
            c = load_catalog(DATA, None, names)
        self.assertTrue(any("свои имена" in p for p in c.problems))
        self.assertEqual(c.standards["din-912"].number, "DIN 912")

    def test_dialog_keeps_only_changed_fields(self):
        from mkga_components.names import changed_fields
        std = catalog().standards["din-912"]
        self.assertEqual(changed_fields(std, {"number": "DIN 912", "kind_name": "Болт", "full_name": "  "}), {"kind_name": "Болт"})

    def test_request_overrides_in_plan(self):
        import tempfile
        from mkga_components.builder import BuildError, Request, plan
        with tempfile.TemporaryDirectory() as tmp:
            std = catalog().standards["din-912"]
            p = plan(Request(std, "M8", 25, Path(tmp), file_stem="Свой: винт?.m3d", title="  Моё имя "))
            self.assertEqual(p.file_stem, "Свой_ винт_")
            self.assertEqual(p.title, "Моё имя")
            with self.assertRaises(BuildError):
                plan(Request(std, "M8", 25, Path(tmp), title="   "))
            with self.assertRaises(BuildError):
                plan(Request(std, "M8", 25, Path(tmp), file_stem="..."))


class CatalogTests(unittest.TestCase):
    def test_builtin_catalog_loads_without_problems(self):
        c = catalog()
        self.assertEqual(c.problems, [])
        for std_id in ("din-912", "iso-7380-1", "iso-7380-2", "din-7991", "din-125-a", "din-127-b", "din-934",
                       "din-933", "din-931", "din-9021", "din-439", "din-985", "din-7984", "din-913",
                       "din-914", "din-916", "iso-2338"):
            self.assertIn(std_id, c.standards)

    def test_every_size_and_length_of_every_standard_is_buildable(self):
        """Таблицы не должны содержать размеров, которые форма не может построить (проверка без КОМПАС)."""
        c = catalog()
        for std in c.standards.values():
            for size in std.size_labels:
                lengths = std.lengths_for(size) if std.has_length else [None]
                self.assertTrue(lengths, f"{std.id} {size}: нет ни одной длины")
                for length in (lengths[0], lengths[-1]):
                    std.shape_obj.check(std.dims(size), length)
                    self.assertGreater(std.volume(size, length), 0, f"{std.id} {size} {length}")

    def test_every_standard_states_its_source_and_is_not_marked_verified_by_default(self):
        for std in catalog().standards.values():
            self.assertTrue(std.source.strip(), std.id)
            self.assertFalse(std.verified, f"{std.id}: «сверено» ставит человек после сверки с оригиналом")

    def test_names_follow_the_users_scheme(self):
        std = catalog().standards["din-912"]
        n = std.names("M8", 25)
        self.assertEqual(n.file_stem, "Винт DIN 912 - M8 x 25")
        self.assertEqual(n.title, "Винт с цилиндрической головкой и шестигранным углублением под ключ DIN 912 - M8 x 25")
        self.assertEqual(std.section_name, "Стандартные изделия")
        self.assertEqual(std.names("M2.5", 12.5, "12.9").file_stem, "Винт DIN 912 - M2,5 x 12,5 - 12.9")
        self.assertEqual(catalog().standards["din-934"].names("M8").file_stem, "Гайка DIN 934 - M8")
        c = catalog()
        self.assertEqual(c.standards["iso-7380-1"].names("M4", 8).file_stem, "Винт ISO 7380-1 - M4 x 8")
        self.assertEqual(c.standards["iso-7380-2"].names("M4", 8).file_stem, "Винт ISO 7380-2 - M4 x 8")

    def test_file_names_never_contain_windows_forbidden_characters(self):
        from mkga_components.catalog import safe_filename
        self.assertEqual(safe_filename('a:b*c?"d<e>f|g'), "a_b_c__d_e_f_g")
        self.assertEqual(safe_filename("Фитинг G1/8"), "Фитинг G1⁄8")      # дробь: «⁄» вместо запрещённой «/»
        self.assertEqual(safe_filename("  имя. "), "имя")

    def test_lengths_are_limited_by_the_size_row(self):
        std = catalog().standards["din-912"]
        lengths = std.lengths_for("M8")
        self.assertEqual((lengths[0], lengths[-1]), (12, 120))
        self.assertNotIn(10, lengths)

    def test_washers_and_nuts_have_no_length(self):
        c = catalog()
        self.assertEqual(c.standards["din-125-a"].lengths_for("M8"), [])
        self.assertFalse(c.standards["din-934"].has_length)

    def test_search_by_number_alias_and_name(self):
        c = catalog()
        self.assertEqual([s.id for s in c.search("ISO 4762")], ["din-912"])
        self.assertIn("din-912", [s.id for s in c.search("ISO 4762")])
        self.assertIn("din-934", [s.id for s in c.search("гайка")])
        self.assertEqual(len(c.search("")), len(c.standards))

    def test_user_standard_is_loaded_and_marked(self):
        from mkga_components.custom import template_for
        c0 = catalog()
        name, text = template_for(c0.standards["din-934"])
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / name).write_text(text, encoding="utf-8")
            c = catalog(Path(tmp))
        self.assertEqual(c.problems, [])
        mine = c.standards["my-din-934"]
        self.assertEqual((mine.origin, mine.number), ("user", "DIN 934 (моё)"))
        self.assertFalse(mine.verified)

    def test_broken_user_files_are_reported_but_do_not_break_the_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "bad.json").write_text("{не json", encoding="utf-8")
            (Path(tmp) / "empty.json").write_text("{}", encoding="utf-8")
            (Path(tmp) / "shape.json").write_text(json.dumps({
                "id": "x-1", "category": "other", "number": "X", "kind_name": "К", "full_name": "К", "section": "other",
                "shape": "нет-такой", "source": "s", "sizes": {"M1": {"d": 1}}}), encoding="utf-8")
            c = catalog(Path(tmp))
        self.assertEqual(len(c.problems), 3)
        self.assertIn("din-912", c.standards)

    def test_user_standard_may_replace_a_builtin_one_with_a_note(self):
        data = json.loads((DATA / "standards" / "din-125-a.json").read_text(encoding="utf-8"))
        data["sizes"]["M8"]["h"] = 1.7
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "fix.json").write_text(json.dumps(data), encoding="utf-8")
            c = catalog(Path(tmp))
        self.assertEqual(c.standards["din-125-a"].sizes["M8"]["h"], 1.7)
        self.assertTrue(any("заменяет" in p for p in c.problems))

    def test_validate_explains_mistakes(self):
        from mkga_components.catalog import validate
        base = json.loads((DATA / "standards" / "din-934.json").read_text(encoding="utf-8"))
        self.assertEqual(validate(base), [])
        self.assertTrue(validate([]))
        broken = dict(base, id="Плохой id", section="xxx", source="  ")
        text = "; ".join(validate(broken))
        for fragment in ("id", "section", "source"):
            self.assertIn(fragment, text)
        row = dict(base, sizes={"M8": {"d": 8, "P": "1,25", "s": 13, "m": 6.5, "dw": 11.3}})
        self.assertIn("числами", "; ".join(validate(row)))
        no_len = json.loads((DATA / "standards" / "din-912.json").read_text(encoding="utf-8"))
        no_len["lengths"] = [10, 5]
        self.assertIn("lengths", "; ".join(validate(no_len)))

    def test_categories_cover_all_standards(self):
        c = catalog()
        known = {cid for cid, _ in c.categories}
        for std in c.standards.values():
            self.assertIn(std.category, known)


class DrawingTests(unittest.TestCase):
    def test_every_standard_has_a_finite_drawing_and_a_valid_svg(self):
        from mkga_components import drawing
        for std in catalog().standards.values():
            size = "M8" if "M8" in std.sizes else std.size_labels[0]
            lengths = std.lengths_for(size)
            length = lengths[len(lengths) // 2] if lengths else None
            d = drawing.draw(std.shape, std.dims(size), length)
            self.assertTrue(d.prims, std.id)
            self.assertTrue(d.width > 0 and d.height > 0 and all(math.isfinite(v) for v in d.bounds), std.id)
            ET.fromstring(drawing.to_svg(d))     # корректный XML
            rows = drawing.legend(std.shape, std.dims(size), length)
            self.assertTrue(rows and all(v for _s, _m, v in rows if _s != "b"), std.id)

    def test_partial_thread_shows_the_b_dimension_and_full_thread_does_not(self):
        from mkga_components import drawing
        std = catalog().standards["din-912"]
        long_ = drawing.draw(std.shape, std.dims("M8"), 60)
        short = drawing.draw(std.shape, std.dims("M8"), 20)
        texts = lambda d: [p.text for p in d.prims if isinstance(p, drawing.Text)]
        self.assertIn("b 28", texts(long_))
        self.assertNotIn("b 28", texts(short))
        self.assertIn("l 60", texts(long_))

    def test_dimension_labels_show_the_values_from_the_table(self):
        from mkga_components import drawing
        std = catalog().standards["din-934"]
        texts = [p.text for p in drawing.draw(std.shape, std.dims("M10"), None).prims if isinstance(p, drawing.Text)]
        self.assertEqual(sorted(texts), ["d 10", "m 8", "s 17"])

    def test_unknown_shape_is_an_error(self):
        from mkga_components import drawing
        with self.assertRaises(KeyError):
            drawing.draw("нет", {}, None)

    def test_dome_points_start_at_the_apex_and_end_at_the_rim(self):
        from mkga_components.drawing import _dome_points
        pts = _dome_points(14, 4.4)
        self.assertAlmostEqual(pts[0][0], 0, places=9)
        self.assertAlmostEqual(pts[0][1], 0, places=9)
        self.assertAlmostEqual(pts[-1][0], 7, places=9)
        self.assertAlmostEqual(pts[-1][1], -4.4, places=9)


def make_ctx(tmp: Path):
    from mkga.core.fake import make_fake_kompas
    from mkga.core.safe_io import BackupStore
    from mkga.runner import ModContext
    kompas = make_fake_kompas()
    ctx = ModContext(mod_dir=MOD_DIR, data_dir=tmp / "data", connect=lambda: kompas, mod_id="components",
                     backups=BackupStore(tmp / "store"))
    return ctx, kompas


class BuilderTests(unittest.TestCase):
    def setUp(self):
        from mkga.core.model3d import Part
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.folder = self.tmp / "parts"
        self.folder.mkdir()
        self.ctx, self.kompas = make_ctx(self.tmp)
        # на фейке нет расчёта массы: объём «совпадает» всегда, остальное (имена, свойства, файл, резьба) проверяется
        for name in ("verify_volume", "verify_planar_area"):
            patcher = mock.patch.object(Part, name, lambda self_, expected, tol=1e-6: expected)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)
        self.c = catalog()

    def request(self, std_id="din-912", size="M8", length=25, **kw):
        from mkga_components.builder import Request
        kw.setdefault("open_after", False)
        return Request(self.c.standards[std_id], size, length, self.folder, **kw)

    def test_plan_gives_names_path_and_section(self):
        from mkga_components.builder import plan
        p = plan(self.request())
        self.assertEqual(p.path, self.folder / "Винт DIN 912 - M8 x 25.m3d")
        self.assertEqual((p.exists, p.section), (False, "Стандартные изделия"))

    def test_plan_rejects_wrong_input(self):
        from mkga_components.builder import BuildError, Request, plan
        std = self.c.standards["din-912"]
        for req in (self.request(size="M99"), self.request(length=7), self.request(length=None),
                    self.request(strength="99.9"), Request(std, "M8", 25, self.tmp / "нет-такой")):
            with self.assertRaises(BuildError):
                plan(req)

    def test_washer_ignores_a_length(self):
        from mkga_components.builder import plan
        self.assertEqual(plan(self.request("din-125-a", "M8", 99)).file_stem, "Шайба DIN 125 A - M8")

    def test_create_saves_the_part_sets_title_and_standard_type_and_threads_it(self):
        from mkga_components.builder import create_part
        r = create_part(self.ctx, self.request(length=60))
        self.assertTrue(r.path.is_file())
        doc = next(iter(self.kompas.app7.documents), None)
        self.assertIsNone(doc)                                  # скрытый документ закрыт без сохранения
        self.assertEqual(r.title, "Винт с цилиндрической головкой и шестигранным углублением под ключ DIN 912 - M8 x 60")

    def test_title_type_and_thread_are_recorded_on_the_part(self):
        from mkga.core.model3d import Part
        from mkga_components.builder import create_part
        seen = {}
        original_close = Part.close

        def spy(self_):
            seen["doc"] = self_.doc
            seen["threads"] = [s for s in self_.top.created if s.kind == "thread"]
            original_close(self_)

        with mock.patch.object(Part, "close", spy):
            create_part(self.ctx, self.request(length=60))
        doc = seen["doc"]
        self.assertEqual(doc.properties[5], "Винт с цилиндрической головкой и шестигранным углублением под ключ DIN 912 - M8 x 60")
        self.assertEqual(doc.properties[14], "Стандартное изделие")
        self.assertEqual(doc.spec_sections, [25])                   # объект спецификации: «Стандартные изделия»
        self.assertIn('id="SPCSection" value="25"', doc.properties_xml)
        (thread,) = seen["threads"]
        self.assertEqual(thread.BaseObject.Radius, 4.0)
        self.assertEqual(thread.Lenght, 28)                      # b из таблицы
        self.assertFalse(thread.AutoLenght)

    def test_short_screw_gets_a_thread_over_the_whole_length(self):
        from mkga.core.model3d import Part
        from mkga_components.builder import create_part
        seen = {}
        original_close = Part.close

        def spy(self_):
            seen["threads"] = [s for s in self_.top.created if s.kind == "thread"]
            original_close(self_)

        with mock.patch.object(Part, "close", spy):
            create_part(self.ctx, self.request(length=20))
        self.assertTrue(seen["threads"][0].AutoLenght)

    def test_other_section_creates_a_spec_object_instead_of_a_type(self):
        from dataclasses import replace
        from mkga.core.model3d import Part
        from mkga_components.builder import Request, create_part
        std = replace(self.c.standards["din-125-a"], section="other")
        seen = {}
        original_close = Part.close

        def spy(self_):
            seen["doc"] = self_.doc
            original_close(self_)

        with mock.patch.object(Part, "close", spy):
            create_part(self.ctx, Request(std, "M8", None, self.folder, open_after=False))
        self.assertEqual(seen["doc"].spec_sections, [30])           # «Прочие изделия» (раздел 30)
        self.assertNotIn(14, seen["doc"].properties)
        self.assertIn('id="SPCSection" value="30"', seen["doc"].properties_xml)

    def test_existing_file_needs_overwrite_and_the_old_one_is_kept_in_history(self):
        from mkga_components.builder import BuildError, create_part
        first = create_part(self.ctx, self.request())
        first.path.write_bytes(b"old")
        with self.assertRaises(BuildError):
            create_part(self.ctx, self.request())
        self.assertEqual(first.path.read_bytes(), b"old")        # отказ ничего не тронул
        create_part(self.ctx, self.request(overwrite=True))
        self.assertNotEqual(first.path.read_bytes(), b"old")
        newest = self.ctx.backups.sessions()[0]                 # новые первыми
        self.assertEqual(newest.operations[0].kind, "modify")
        self.assertTrue(self.ctx.backups.undo(newest.id).ok)
        self.assertEqual(first.path.read_bytes(), b"old")        # замену можно отменить

    def test_new_file_creation_can_be_undone(self):
        from mkga_components.builder import create_part
        r = create_part(self.ctx, self.request())
        info = self.ctx.backups.sessions()[0]
        self.assertEqual(info.operations[0].kind, "create")
        self.assertTrue(self.ctx.backups.undo(info.id).ok)
        self.assertFalse(r.path.exists())

    def test_open_after_opens_the_saved_file_in_kompas(self):
        from mkga_components.builder import create_part
        r = create_part(self.ctx, self.request(open_after=True))
        self.assertTrue(r.opened)
        self.assertEqual([d.Name for d in self.kompas.app7.documents], [r.path.name])

    def test_failed_build_rolls_back_the_file_and_closes_the_hidden_document(self):
        from mkga.core.model3d import ModelError, Part
        from mkga_components.builder import create_part
        with mock.patch.object(Part, "verify_volume", side_effect=ModelError("объём не сошёлся")):
            with self.assertRaises(ModelError):
                create_part(self.ctx, self.request())
        self.assertEqual(list(self.folder.iterdir()), [])
        self.assertEqual(self.kompas.app7.Documents.Count, 0)

    def test_every_standard_builds_on_the_fake_with_its_shape(self):
        from mkga_components.builder import create_part
        for std in self.c.standards.values():
            size = "M8" if "M8" in std.sizes else std.size_labels[0]
            lengths = std.lengths_for(size)
            length = lengths[len(lengths) // 2] if lengths else None
            with self.subTest(standard=std.id):
                folder = self.folder / std.id
                folder.mkdir()
                from mkga_components.builder import Request
                create_part(self.ctx, Request(std, size, length, folder, open_after=False))


class CustomPartsTests(unittest.TestCase):
    def test_template_is_a_valid_standard_with_a_new_id_and_an_empty_source_marker(self):
        from mkga_components.catalog import validate
        from mkga_components.custom import template_for
        std = catalog().standards["din-912"]
        name, text = template_for(std)
        data = json.loads(text)
        self.assertEqual((name, data["id"]), ("my-din-912.json", "my-din-912"))
        self.assertEqual(validate(data), [])
        self.assertIn("ЗАПОЛНИТЕ", data["source"])
        self.assertFalse(data["verified"])

    def test_template_id_never_exceeds_the_limit(self):
        from mkga_components.custom import template_for
        from dataclasses import replace
        std = replace(catalog().standards["din-912"], id="a" * 40)
        name, _ = template_for(std)
        self.assertLessEqual(len(name[:-5]), 40)

    def test_round_trip_through_json_keeps_the_standard(self):
        from mkga_components.catalog import _from_data
        from mkga_components.custom import standard_to_dict
        for std in catalog().standards.values():
            again = _from_data(json.loads(json.dumps(standard_to_dict(std))), "user", None)
            self.assertEqual(again.sizes, std.sizes, std.id)
            self.assertEqual(again.lengths, std.lengths, std.id)
            self.assertEqual(again.number, std.number)

    def test_ai_prompt_lists_all_shapes_rules_and_a_working_example(self):
        from mkga_components import shapes
        from mkga_components.custom import ai_prompt
        prompt = ai_prompt(catalog().standards["din-912"])
        for shape_id in shapes.SHAPES:
            self.assertIn(f'"{shape_id}"', prompt)
        for fragment in ("source", "verified", "standard", "other", "lmin", "Не выдумывай"):
            self.assertIn(fragment, prompt)
        self.assertIn('"id": "din-912"', prompt)
        self.assertTrue(ai_prompt(None))


@unittest.skipUnless(display_available(), "нет дисплея для tkinter")
class WindowTests(unittest.TestCase):
    def setUp(self):
        from mkga_components.ui import ComponentsWindow
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.folder = self.tmp / "parts"
        self.folder.mkdir()
        self.user = self.tmp / "user"
        self.ctx, self.kompas = make_ctx(self.tmp)
        self.ctx.settings.set("folder", str(self.folder))
        self.names_file = self.tmp / "data" / "names.json"
        self.win = ComponentsWindow(self.ctx, catalog(), version="0.1.0", user_dir=self.user, builtin_dir=DATA,
                                    names_file=self.names_file)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        self.win.close()
        self.win = None
        gc.collect()
        self._tmp.cleanup()

    def pump(self, n=15):
        for _ in range(n):
            self.win.root.update()
            time.sleep(0.01)

    def test_tree_lists_categories_and_standards_and_a_standard_is_preselected(self):
        w = self.win
        labels = [w.tree.item(i, "text") for i in w.tree.get_children()]
        self.assertTrue(any(t.startswith("Винты и болты") for t in labels))
        self.assertIsNotNone(w.std)
        self.assertEqual(w.title_var.get(), w.std.names(w._current_size(), w._length()).title)

    def test_choosing_a_standard_fills_size_and_length_lists_and_names(self):
        w = self.win
        w._select_standard("din-912")
        self.assertEqual(w.size_var.get(), "M8")
        self.assertIn("25", w.length_box.cget("values"))
        w.length_var.set("40")
        w._refresh_preview()
        self.assertEqual(w.file_var.get(), "Винт DIN 912 - M8 x 40")
        self.assertTrue(w.file_note_var.get().startswith(".m3d"))
        self.assertEqual(w.section_var.get(), "Стандартные изделия")

    def test_size_change_limits_the_lengths(self):
        w = self.win
        w._select_standard("din-912")
        w.size_var.set("M3")
        w._on_size_changed()
        lengths = w.length_box.cget("values")
        self.assertNotIn("120", lengths)
        self.assertIn(w.length_var.get(), lengths)

    def test_washer_hides_length_and_nut_shows_class(self):
        w = self.win
        w._select_standard("din-125-a")
        self.pump()
        self.assertFalse(w.length_box.winfo_ismapped())
        self.assertFalse(w.class_box.winfo_ismapped())
        w._select_standard("din-934")
        self.pump()
        self.assertTrue(w.class_box.winfo_ismapped())

    def test_strength_class_goes_into_the_name(self):
        w = self.win
        w._select_standard("din-912")
        w.class_var.set("12.9")
        w._refresh_preview()
        self.assertTrue(w.file_var.get().endswith("- 12.9"))
        w.class_var.set("не указывать")
        w._refresh_preview()
        self.assertNotIn("12.9", w.file_var.get())

    def test_names_can_be_edited_by_hand_and_are_used_for_the_part(self):
        w = self.win
        w._select_standard("din-912")
        w.file_var.set("Мой винт M8")
        w.title_var.set("Винт мой особенный")
        w._on_name_edited()
        w.folder_var.set(str(self.folder))
        req = w._request()
        self.assertEqual((req.file_stem, req.title), ("Мой винт M8", "Винт мой особенный"))
        w.length_var.set("40")
        w._refresh_preview()
        self.assertEqual(w.file_var.get(), "Мой винт M8")             # правка сохраняется при смене папки и предпросмотра
        w._params_changed()                                          # смена длины возвращает автоматические имена
        self.assertEqual(w.file_var.get(), "Винт DIN 912 - M8 x 40")
        self.assertIsNone(w._request().file_stem)

    def test_reset_names_button_returns_the_standard_names(self):
        w = self.win
        w._select_standard("din-934")
        w.title_var.set("что-то своё")
        w._on_name_edited()
        w._reset_names()
        self.assertEqual(w.title_var.get(), w.std.names(w._current_size(), w._length()).title)

    def test_saving_own_names_for_a_standard_renames_it_everywhere(self):
        w = self.win
        w._select_standard("din-912")
        w.save_names("din-912", {"number": "ISO 4762", "kind_name": "Болт"})
        self.assertTrue(self.names_file.is_file())
        self.assertEqual(w.std.number, "ISO 4762")
        self.assertTrue(w.std.is_renamed)
        w.length_var.set("40")
        w._refresh_preview()
        self.assertEqual(w.file_var.get(), "Болт ISO 4762 - M8 x 40")
        self.assertIn("Имена изменены вами", w.std_aliases.cget("text"))
        self.assertIn("ISO 4762", [w.tree.item(i, "text") for n in w.tree.get_children() for i in w.tree.get_children(n)][0] +
                      " ".join(w.tree.item(i, "text") for n in w.tree.get_children() for i in w.tree.get_children(n)))
        w.save_names("din-912", None)                               # вернуть по умолчанию
        self.assertEqual(w.std.number, "DIN 912")
        self.assertFalse(w.std.is_renamed)

    def test_search_filters_the_tree(self):
        w = self.win
        w.search_var.set("DIN 934")
        self.pump()
        self.assertEqual(list(w._tree_ids.values()), ["din-934"])
        w.search_var.set("")
        self.pump()
        self.assertGreater(len(w._tree_ids), 3)

    def test_drawing_is_rendered_on_the_canvas_and_legend_is_filled(self):
        w = self.win
        w._select_standard("din-912")
        self.pump(30)
        self.assertGreater(len(w.canvas.find_all()), 20)
        self.assertGreater(len(w.legend_frame.winfo_children()), 8)

    def test_create_runs_in_background_and_writes_the_file(self):
        from mkga.core.model3d import Part
        w = self.win
        w._select_standard("din-125-a")
        w.open_var.set(False)
        w._refresh_preview()
        with mock.patch.object(Part, "verify_volume", lambda self_, expected, tol=1e-6: expected),                 mock.patch.object(Part, "verify_planar_area", lambda self_, expected, tol=1e-6: expected):
            w._create()
            w.wait_idle(10)
        self.assertTrue((self.folder / "Шайба DIN 125 A - M8.m3d").is_file())
        self.assertIn("Готово:", w.log_text.get("1.0", "end"))
        self.assertEqual(self.ctx.settings.get("folder"), str(self.folder))

    def test_create_asks_before_replacing_and_does_nothing_on_no(self):
        w = self.win
        w._select_standard("din-125-a")
        target = self.folder / "Шайба DIN 125 A - M8.m3d"
        target.write_bytes(b"old")
        with mock.patch("mkga_components.ui.messagebox.askyesno", return_value=False) as ask:
            w._create()
            w.wait_idle(5)
        self.assertTrue(ask.called)
        self.assertEqual(target.read_bytes(), b"old")

    def test_missing_folder_is_reported_not_raised(self):
        w = self.win
        w.folder_var.set(str(self.tmp / "нет"))
        w._create()
        self.pump()
        self.assertIn("папки нет", w.log_text.get("1.0", "end"))

    def test_template_and_reload_add_a_user_standard(self):
        w = self.win
        w._select_standard("din-934")
        with mock.patch("mkga_components.ui.os.startfile", create=True):
            w.create_template()
            w.wait_idle(5)
        self.assertTrue((self.user / "my-din-934.json").is_file())
        w.reload_catalog()
        self.pump()
        self.assertIn("my-din-934", w.catalog.standards)
        self.assertTrue(any("★" in w.tree.item(i, "text") for node in w.tree.get_children() for i in w.tree.get_children(node)))

    def test_copy_ai_prompt_puts_text_on_the_clipboard(self):
        w = self.win
        w.copy_ai_prompt()
        self.assertIn("Помоги добавить изделие", w.root.clipboard_get())

    def test_custom_dialog_opens(self):
        from mkga_components.custom import open_custom_dialog
        open_custom_dialog(self.win)
        self.pump()
        tops = [c for c in self.win.root.winfo_children() if c.winfo_class() == "Toplevel"]
        self.assertEqual(len(tops), 1)
        tops[0].destroy()

    def test_works_in_the_dark_theme_too(self):
        from mkga.ui.theme import DARK
        from mkga_components.ui import ComponentsWindow
        other = ComponentsWindow(self.ctx, catalog(), palette=DARK, user_dir=self.user, builtin_dir=DATA)
        try:
            other.root.update()
            self.assertIsNotNone(other.std)
        finally:
            other.close()


class ModuleEntryTests(unittest.TestCase):
    def test_manifest_is_valid_and_claims_only_the_tested_version(self):
        from mkga.manifest import load_manifest
        m = load_manifest(MOD_DIR)
        self.assertEqual((m.id, list(m.kompas_versions)), ("components", [24]))

    def test_mod_passes_the_io_guard(self):
        from mkga.guard import check_path, violations
        self.assertEqual(violations(check_path(MOD_DIR)), [])

    def test_main_loads_the_catalog_and_starts_the_app(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("components_main", MOD_DIR / "main.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            ctx, _ = make_ctx(Path(tmp))
            with mock.patch("mkga_components.ui.run_app") as run_app:
                module.run(ctx)
        (_, catalog_arg), kwargs = run_app.call_args
        self.assertIn("din-912", catalog_arg.standards)
        self.assertEqual(kwargs["version"], "0.5.0")
        self.assertEqual(kwargs["user_dir"], Path(ctx.data_dir) / "standards")


if __name__ == "__main__":
    unittest.main()
