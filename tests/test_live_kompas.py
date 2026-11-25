"""ЖИВАЯ проверка на настоящем КОМПАСе. Пропускается, если не задан MKGA_LIVE_KOMPAS=1.

    $env:MKGA_LIVE_KOMPAS = "1"; python -m unittest tests.test_live_kompas -v

Нужен запущенный КОМПАС. Тест создаёт СВОЙ новый пустой документ, сохраняет его только во временную папку
и закрывает без сохранения; документы пользователя не трогаются, число открытых документов и активный
документ после теста те же. Проверено на КОМПАС-3D v24 (24.0.3.0, полная версия).
"""

import os
import tempfile
import unittest
from pathlib import Path

LIVE = os.environ.get("MKGA_LIVE_KOMPAS") == "1"


@unittest.skipUnless(LIVE, "живая проверка: задайте MKGA_LIVE_KOMPAS=1 и запустите КОМПАС")
class LiveKompasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from mkga.core.kompas import connect
        cls.k = connect()

    def test_versions_agree_between_api5_and_api7(self):
        self.assertEqual(self.k.api5_version, self.k.version)
        self.assertGreaterEqual(self.k.version[0], 17)

    def test_edition_flags_are_booleans(self):
        self.assertIsInstance(self.k.is_study, bool)
        self.assertIsInstance(self.k.is_home, bool)

    def test_child_objects_are_late_bound_even_if_gen_py_cache_exists(self):
        if self.k.app7.Documents.Count == 0:
            self.skipTest("нет открытых документов")
        doc = self.k.app7.Documents.Item(0)
        self.assertNotIn("gen_py", type(doc).__module__)

    def test_constants_match_real_document_types(self):
        from mkga.core import constants as C
        doc = self.k.new_document(C.ksDocumentPart, visible=False)
        try:
            self.assertEqual(doc.DocumentType, C.ksDocumentPart)
        finally:
            self.k.close_document(doc)

    def test_save_as_new_file_overwrite_and_undo(self):
        from mkga.core import constants as C
        from mkga.core.safe_io import BackupStore
        k = self.k
        count, active = k.app7.Documents.Count, k.active_document.Name if k.active_document else None
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            store = BackupStore(tmp / "backups", trash=lambda p: p.unlink())
            target = tmp / "mkga-live-test.m3d"
            doc = k.new_document(C.ksDocumentPart, visible=False)
            try:
                with store.begin("live", "SaveAs нового файла") as s:
                    k.save_as(s, doc, target)
                    sid = s.info.id
                self.assertGreater(target.stat().st_size, 1000)          # настоящий файл КОМПАСа
                self.assertTrue(store.undo(sid).ok)
                self.assertFalse(target.exists())                          # создание откачено

                target.write_bytes(b"IMPORTANT USER FILE")
                with store.begin("live", "SaveAs поверх существующего") as s:
                    k.save_as(s, doc, target)
                    sid = s.info.id
                self.assertNotEqual(target.read_bytes(), b"IMPORTANT USER FILE")
                self.assertTrue(store.undo(sid).ok)
                self.assertEqual(target.read_bytes(), b"IMPORTANT USER FILE")  # исходный файл вернулся

                target.unlink()
                with store.begin("live", "предпросмотр", dry_run=True) as s:
                    k.save_as(s, doc, target)
                self.assertFalse(target.exists())                           # предпросмотр ничего не пишет
            finally:
                k.close_document(doc)
        self.assertEqual(k.app7.Documents.Count, count)
        self.assertEqual(k.active_document.Name if k.active_document else None, active)


if __name__ == "__main__":
    unittest.main()
