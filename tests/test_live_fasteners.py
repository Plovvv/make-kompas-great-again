"""ЖИВАЯ проверка мода «Метизы и фитинги»: детали строятся в КОМПАС, объём сверяется с расчётом, файл сохраняется,
открывается заново и в нём читаются наименование, тип объекта и резьба.

    $env:MKGA_LIVE_KOMPAS = "1"; python -m unittest tests.test_live_fasteners -v

Пропускается без MKGA_LIVE_KOMPAS=1. Нужен запущенный КОМПАС. Файлы пишутся только во временную папку, документы
пользователя не трогаются. Проверено на КОМПАС-3D v24.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

LIVE = os.environ.get("MKGA_LIVE_KOMPAS") == "1"
MOD_DIR = Path(__file__).resolve().parent.parent / "mods" / "fasteners"


@unittest.skipUnless(LIVE, "живая проверка: задайте MKGA_LIVE_KOMPAS=1 и запустите КОМПАС")
class LiveFastenersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(MOD_DIR))
        from mkga.core.kompas import connect
        from mkga.core.safe_io import BackupStore
        from mkga.runner import ModContext
        from mkga_fasteners.catalog import load_catalog

        cls.k = connect()
        cls.catalog = load_catalog(MOD_DIR / "data")
        cls._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.folder = Path(cls._tmp.name)
        cls.ctx = ModContext(mod_dir=MOD_DIR, data_dir=cls.folder / "data", connect=lambda: cls.k, mod_id="fasteners",
                             backups=BackupStore(cls.folder / "store"))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()
        sys.path.remove(str(MOD_DIR))

    def setUp(self):
        self.count = self.k.app7.Documents.Count
        self.folder = Path(tempfile.mkdtemp(dir=self.__class__.folder))   # у каждого теста своя папка

    def tearDown(self):
        self.assertEqual(self.k.app7.Documents.Count, self.count)     # тест не оставил документов

    # --- помощники -------------------------------------------------------------------------------
    def create(self, std_id, size, length=None, strength=None):
        from mkga_fasteners.builder import Request, create_part
        std = self.catalog.standards[std_id]
        return create_part(self.ctx, Request(std, size, length, self.folder, strength, open_after=False))

    def reopen(self, path):
        """Открыть сохранённый файл скрытым, вернуть (документ, свойства)."""
        from mkga.core import com_iface
        doc = self.k.app7.Documents.Open(str(path), False, False)
        props = {int(p.Id): p for p in com_iface.get(self.k.app7, "IPropertyMng", "GetProperties", doc)}
        return doc, props

    def read_property(self, doc, props, pid):
        from mkga.core import com_iface
        import pythoncom
        from win32com.client import VARIANT
        value = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_VARIANT, None)
        from_source = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BOOL, False)
        com_iface.call(doc, "IPropertyKeeper", "GetPropertyValue", props[pid], value, True, from_source)
        return value.value

    def check_saved(self, result, *, object_type=None, threads=0):
        self.assertTrue(result.path.is_file())
        doc, props = self.reopen(result.path)
        try:
            self.assertEqual(self.read_property(doc, props, 5), result.title)          # Наименование
            if object_type:
                self.assertEqual(self.read_property(doc, props, 14), object_type)       # Тип объекта
            self.assertEqual(doc.TopPart.Threads.Count, threads)
            return doc.TopPart.Mass
        finally:
            doc.Close(0)

    # --- винт DIN 912 ------------------------------------------------------------------------------
    def test_din912_m8x25_whole_length_thread(self):
        r = self.create("din-912", "M8", 25)
        self.assertAlmostEqual(r.volume_mm3, r.expected_mm3, delta=r.expected_mm3 * 1e-6)
        self.assertEqual(r.path.name, "Винт DIN 912 - M8 x 25.m3d")
        self.assertEqual(r.title, "Винт с цилиндрической головкой и шестигранным углублением под ключ DIN 912 - M8 x 25")
        self.check_saved(r, object_type="Стандартное изделие", threads=1)

    def test_din912_m8x60_partial_thread_from_the_tip(self):
        from mkga.core.model3d import Part
        r = self.create("din-912", "M8", 60)
        doc = self.k.app7.Documents.Open(str(r.path), False, False)
        try:
            from mkga.core import com_iface
            thread = doc.TopPart.Threads.Item(0)
            outs = com_iface.out_doubles(6)
            com_iface.invoke_with_outs(thread, "GetLimitPoints", *outs)
            y1, y2 = outs[1].value, outs[4].value
            # торец винта y = -(k + l) = -68; резьба b = 28 от самого конца: -68 ... -40
            self.assertAlmostEqual(min(y1, y2), -68.0, places=3)
            self.assertAlmostEqual(max(y1, y2), -40.0, places=3)
        finally:
            doc.Close(0)

    def test_din912_with_strength_class_and_decimal_size(self):
        r = self.create("din-912", "M2.5", 12, "12.9")
        self.assertEqual(r.path.name, "Винт DIN 912 - M2,5 x 12 - 12.9.m3d")
        self.assertAlmostEqual(r.volume_mm3, r.expected_mm3, delta=r.expected_mm3 * 1e-6)

    def test_din912_range_of_sizes(self):
        for size, length in (("M3", 10), ("M5", 30), ("M10", 40), ("M12", 100), ("M16", 60), ("M24", 80)):
            with self.subTest(size=size):
                r = self.create("din-912", size, length)
                self.assertAlmostEqual(r.volume_mm3, r.expected_mm3, delta=r.expected_mm3 * 1e-6)

    # --- шайба DIN 125 A ---------------------------------------------------------------------------
    def test_din125_washers(self):
        for size in ("M3", "M8", "M16", "M36"):
            with self.subTest(size=size):
                r = self.create("din-125-a", size)
                self.assertAlmostEqual(r.volume_mm3, r.expected_mm3, delta=r.expected_mm3 * 1e-6)
        self.check_saved(self.create("din-125-a", "M5"), object_type="Стандартное изделие", threads=0)

    # --- гайка DIN 934 -----------------------------------------------------------------------------
    def test_din934_nuts(self):
        for size in ("M3", "M8", "M12", "M20"):
            with self.subTest(size=size):
                r = self.create("din-934", size)
                self.assertAlmostEqual(r.volume_mm3, r.expected_mm3, delta=r.expected_mm3 * 3e-2)
        self.check_saved(self.create("din-934", "M5"), object_type="Стандартное изделие", threads=1)


    # --- DIN 7991, ISO 7380, DIN 127 B ---------------------------------------------------------------------
    def test_din7991_countersunk(self):
        for size, length in (("M3", 10), ("M6", 25), ("M8", 30), ("M12", 50), ("M20", 60)):
            with self.subTest(size=size):
                r = self.create("din-7991", size, length)
                self.assertAlmostEqual(r.volume_mm3, r.expected_mm3, delta=r.expected_mm3 * 1e-6)
        self.check_saved(self.create("din-7991", "M5", 20), object_type="Стандартное изделие", threads=1)

    def test_iso7380_button_head_with_arc(self):
        for size, length in (("M3", 8), ("M5", 20), ("M8", 25), ("M10", 40), ("M16", 50)):
            with self.subTest(size=size):
                r = self.create("iso-7380-1", size, length)     # объём КОМПАС неточен на сфере с углублением (~4e-4)
                self.assertAlmostEqual(r.volume_mm3, r.expected_mm3, delta=r.expected_mm3 * 2e-3)
        self.check_saved(self.create("iso-7380-1", "M6", 16), object_type="Стандартное изделие", threads=1)

    def test_din127_spring_washers(self):
        for size in ("M3", "M8", "M16", "M36"):
            with self.subTest(size=size):
                r = self.create("din-127-b", size)
                self.assertAlmostEqual(r.volume_mm3, r.expected_mm3, delta=r.expected_mm3 * 1e-6)
        self.check_saved(self.create("din-127-b", "M6"), object_type="Стандартное изделие", threads=0)

    def test_every_catalog_standard_builds_with_one_sample_size(self):
        """По одному типоразмеру из каждого стандарта каталога: страховка от опечаток в таблицах."""
        for std in self.catalog.standards.values():
            size = "M8" if "M8" in std.sizes else std.size_labels[0]
            lengths = std.lengths_for(size)
            length = lengths[len(lengths) // 2] if lengths else None
            with self.subTest(standard=std.id):
                r = self.create(std.id, size, length)
                tol = std.shape_obj.volume_tol
                self.assertAlmostEqual(r.volume_mm3, r.expected_mm3, delta=r.expected_mm3 * tol)

    # --- «Прочие изделия» ----------------------------------------------------------------------------
    def test_other_section_creates_a_spec_object(self):
        from dataclasses import replace
        from mkga_fasteners.builder import Request, create_part
        std = replace(self.catalog.standards["din-125-a"], id="test-other", section="other")
        r = create_part(self.ctx, Request(std, "M8", None, self.folder, None, open_after=False))
        doc = self.k.app7.Documents.Open(str(r.path), False, False)
        try:
            self.assertEqual(doc.SpecificationDescriptions.Count, 1)
        finally:
            doc.Close(0)

    # --- существующий файл и откат ---------------------------------------------------------------------
    def test_existing_file_needs_overwrite_flag(self):
        from mkga_fasteners.builder import BuildError, Request, create_part
        std = self.catalog.standards["din-125-a"]
        first = self.create("din-125-a", "M10")
        with self.assertRaises(BuildError):
            create_part(self.ctx, Request(std, "M10", None, self.folder, None, open_after=False))
        again = create_part(self.ctx, Request(std, "M10", None, self.folder, None, open_after=False, overwrite=True))
        self.assertEqual(first.path, again.path)


if __name__ == "__main__":
    unittest.main()
