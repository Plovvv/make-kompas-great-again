"""Константы КОМПАСа: целостность модуля и (на машине с КОМПАСом) сверка с библиотекой типов."""

import unittest

from mkga.core import constants as C
from mkga.core.fake import make_fake_kompas
from mkga.core.typelib import read_enum_constants, typelib_available


class ConstantsModuleTests(unittest.TestCase):
    def test_values_known_from_kompas_v24(self):
        # эти значения подтверждены чтением библиотеки типов КОМПАС-3D v24
        self.assertEqual((C.ksDocumentDrawing, C.ksDocumentFragment, C.ksDocumentPart, C.ksDocumentAssembly),
                         (1, 2, 4, 5))
        self.assertEqual(C.ksObjectSketch, 11006)
        self.assertEqual(C.prBaseExtrusion, 20000)

    def test_all_dict_is_consistent_and_ints(self):
        self.assertGreater(len(C.ALL), 100)
        for name, value in C.ALL.items():
            self.assertIsInstance(value, int, name)
            self.assertEqual(getattr(C, name), value, name)

    def test_not_the_whole_table(self):
        # осознанное решение: берём только нужное, а не все 3666 констант
        self.assertLess(len(C.ALL), 600)

    def test_kompas_exposes_constants_without_com(self):
        k = make_fake_kompas()
        self.assertIs(k.constants, C)
        self.assertEqual(k.constants.ksDocumentPart, 4)


@unittest.skipUnless(typelib_available(), "нужен Windows с установленным КОМПАСом (библиотека типов Kompas6Constants)")
class ConstantsMatchTypelibTests(unittest.TestCase):
    def test_every_constant_matches_installed_kompas(self):
        from mkga.core.typelib import read_enums
        lib = dict(read_enum_constants())
        for members in read_enums().values():          # 3D-константы: библиотека Kompas6Constants3D
            lib.update(members)
        wrong = {n: (v, lib.get(n)) for n, v in C.ALL.items() if lib.get(n) != v}
        self.assertEqual(wrong, {}, "расхождения (в файле, в КОМПАСе); возможно, другая версия КОМПАСа")


class EditionTests(unittest.TestCase):
    def test_edition_flags_from_api5(self):
        full = make_fake_kompas()
        self.assertEqual((full.is_study, full.is_home, full.is_spds), (False, False, False))
        study = make_fake_kompas(study=True)
        self.assertTrue(study.is_study)


if __name__ == "__main__":
    unittest.main()
