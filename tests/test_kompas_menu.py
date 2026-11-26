"""Пункты MKGA в меню КОМПАС: правка KOMPAS.kit.config (на копиях и синтетических файлах, настоящий КОМПАС не нужен)."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from mkga import kompas_menu as km
from mkga.core.safe_io import BackupStore

SAMPLE = (
    '<?xml version="1.0" encoding="utf-16" ?>\n<Kit_Config>\n\t<Version>1.0</Version>\n\t<Groups>\n\t\t<Group>\n'
    '\t\t\t<Application libType="lbt_rtw_ocx" path="C:\\K\\a.rtw" id="A" libName="a" displayName="Приложение" autostart="true"/>\n'
    '\t\t\t<Utility path="C:\\WINDOWS\\system32\\calc.exe" displayName="Калькулятор" params="" description=""/>\n'
    '\t\t\t<Utility path="C:\\K\\KLibEditor.exe" displayName="Редактор" params="" description=""/>\n'
    '\t\t</Group>\n\t\t<Group groupName="Другое">\n\t\t\t<Library libType="lbt_kle" path="C:\\K\\x.kle" id="X"/>\n\t\t</Group>\n'
    '\t</Groups>\n</Kit_Config>\n'
)
ENTRIES = [km.MenuEntry("MKGA: хаб модов", r"C:\Prog Files\MKGA\MKGA.exe", "", "Хаб"),
           km.MenuEntry("MKGA: Каталог & «комплектующих»", r"C:\Prog Files\MKGA\MKGA.exe", '--mods-dir "C:\\m d" run components')]


def make_appdata(text=SAMPLE, versions=("24",)):
    root = Path(tempfile.mkdtemp())
    for v in versions:
        d = root / "ASCON" / "KOMPAS-3D" / v
        d.mkdir(parents=True)
        (d / "KOMPAS.kit.config").write_bytes(km.encode_config(text))
    return root


class TextEditing(unittest.TestCase):
    def test_entries_go_after_the_last_utility_with_the_same_indent(self):
        new = km.apply_entries(SAMPLE, ENTRIES)
        lines = new.split("\n")
        i = next(n for n, l in enumerate(lines) if "KLibEditor" in l)
        self.assertIn("MKGA: хаб модов", lines[i + 1])
        self.assertTrue(lines[i + 1].startswith("\t\t\t<Utility"))
        self.assertEqual(len(km.our_rows(new)), 2)

    def test_result_is_valid_xml_with_escaped_attributes(self):
        from xml.etree import ElementTree as ET
        root = ET.fromstring(km.encode_config(km.apply_entries(SAMPLE, ENTRIES)))
        ours = [u for u in root.iter("Utility") if km.MARK in u.get("description")]
        self.assertEqual(ours[1].get("displayName"), "MKGA: Каталог & «комплектующих»")
        self.assertEqual(ours[1].get("params"), '--mods-dir "C:\\m d" run components')

    def test_foreign_rows_are_untouched_and_remove_restores_the_original(self):
        new = km.apply_entries(SAMPLE, ENTRIES)
        self.assertIn("Калькулятор", new)
        self.assertEqual(km.remove_entries(new), SAMPLE)
        self.assertEqual(km.apply_entries(SAMPLE, []), SAMPLE)

    def test_applying_twice_replaces_instead_of_duplicating(self):
        once = km.apply_entries(SAMPLE, ENTRIES)
        twice = km.apply_entries(once, ENTRIES[:1])
        self.assertEqual(len(km.our_rows(twice)), 1)
        self.assertEqual(km.remove_entries(twice), SAMPLE)

    def test_crlf_is_preserved(self):
        crlf = SAMPLE.replace("\n", "\r\n")
        new = km.apply_entries(crlf, ENTRIES)
        self.assertNotIn("\n\n", new.replace("\r\n", ""))
        self.assertEqual(km.remove_entries(new), crlf)

    def test_without_utilities_nothing_is_guessed(self):
        with self.assertRaises(km.MenuError):
            km.apply_entries("<Kit_Config></Kit_Config>", ENTRIES)

    def test_default_entries(self):
        e = km.default_entries(r"C:\x\MKGA.exe", [("components", "Каталог комплектующих")], r"C:\mods")
        self.assertEqual(e[0].params, "")
        self.assertEqual(e[1].title, "MKGA: Каталог комплектующих")
        self.assertEqual(e[1].params, '--mods-dir "C:\\mods" run components')


EMPTY_V25 = '<?xml version="1.0" encoding="utf-16" ?>\n<Kit_Config>\n\t<Version>1.0</Version>\n\t<Groups/>\n</Kit_Config>\n'
NO_UTILITIES = ('<?xml version="1.0" encoding="utf-16" ?>\n<Kit_Config>\n\t<Groups>\n\t\t<Group>\n'
                '\t\t\t<Application libType="lbt_rtw_ocx" path="C:\\K\\a.rtw" id="A" libName="a" displayName="a" autostart="true"/>\n'
                '\t\t</Group>\n\t</Groups>\n</Kit_Config>\n')


class OtherLayouts(unittest.TestCase):
    """КОМПАС v25: пользовательский файл пуст («<Groups/>»); бывают файлы с группами, но без утилит."""

    def test_empty_groups_get_a_group_with_our_utilities_and_come_back_byte_for_byte(self):
        from xml.etree import ElementTree as ET
        for eol in ("\n", "\r\n"):
            with self.subTest(eol=repr(eol)):
                text = EMPTY_V25.replace("\n", eol)
                new = km.apply_entries(text, ENTRIES)
                root = ET.fromstring(km.encode_config(new))
                (group,) = root.find("Groups").findall("Group")
                self.assertEqual(len(group.findall("Utility")), 2)
                self.assertEqual(len(km.our_rows(new)), 2)
                self.assertNotIn("<Groups/>", new)
                self.assertEqual(km.remove_entries(new), text)

    def test_groups_without_utilities_get_rows_at_the_end_of_the_first_group(self):
        from xml.etree import ElementTree as ET
        new = km.apply_entries(NO_UTILITIES, ENTRIES)
        root = ET.fromstring(km.encode_config(new))
        group = root.find("Groups").find("Group")
        self.assertEqual([c.tag for c in group], ["Application", "Utility", "Utility"])
        self.assertEqual(km.remove_entries(new), NO_UTILITIES)

    def test_file_without_any_group_is_still_refused(self):
        with self.assertRaises(km.MenuError):
            km.apply_entries("<Kit_Config><Version>1.0</Version></Kit_Config>", ENTRIES)

    def test_apply_twice_on_empty_file_does_not_duplicate(self):
        once = km.apply_entries(EMPTY_V25, ENTRIES)
        twice = km.apply_entries(once, ENTRIES[:1])
        self.assertEqual(len(km.our_rows(twice)), 1)
        self.assertEqual(km.remove_entries(twice), EMPTY_V25)

    def test_whole_file_roundtrip_on_a_v25_style_file(self):
        appdata = make_appdata(EMPTY_V25, versions=("25",))
        self.addCleanup(shutil.rmtree, appdata, True)
        store = BackupStore(tempfile.mkdtemp(), trash=lambda p: None)
        path = appdata / "ASCON" / "KOMPAS-3D" / "25" / "KOMPAS.kit.config"
        before = path.read_bytes()
        (report,) = km.apply(ENTRIES, appdata=appdata, store=store, running=lambda: False)
        self.assertEqual((report.before, report.after), (0, 2))
        self.assertTrue(store.undo(report.session_id).ok)
        self.assertEqual(path.read_bytes(), before)


class FileOperations(unittest.TestCase):
    def setUp(self):
        self.appdata = make_appdata(versions=("23", "24"))
        self.store = BackupStore(tempfile.mkdtemp(), trash=lambda p: None)
        self.addCleanup(shutil.rmtree, self.appdata, True)

    def read(self, v):
        return km.read_config(self.appdata / "ASCON" / "KOMPAS-3D" / v / "KOMPAS.kit.config")

    def test_only_selected_versions_change(self):
        reports = km.apply(ENTRIES, versions=["24"], appdata=self.appdata, store=self.store, running=lambda: False)
        self.assertEqual([r.version for r in reports], ["24"])
        self.assertEqual(km.status(appdata=self.appdata), {"23": 0, "24": 2})

    def test_refuses_while_kompas_is_running(self):
        with self.assertRaises(km.MenuError):
            km.apply(ENTRIES, appdata=self.appdata, store=self.store, running=lambda: True)
        self.assertEqual(self.read("24"), SAMPLE)

    def test_dry_run_writes_nothing_even_with_kompas_running(self):
        r = km.apply(ENTRIES, appdata=self.appdata, store=self.store, dry_run=True, running=lambda: True)
        self.assertTrue(all(x.changed and x.after == 2 for x in r))
        self.assertEqual(self.read("24"), SAMPLE)

    def test_undo_restores_the_file_byte_for_byte(self):
        path = self.appdata / "ASCON" / "KOMPAS-3D" / "24" / "KOMPAS.kit.config"
        before = path.read_bytes()
        (report,) = km.apply(ENTRIES, versions=["24"], appdata=self.appdata, store=self.store, running=lambda: False)
        self.assertNotEqual(path.read_bytes(), before)
        self.assertTrue(self.store.undo(report.session_id).ok)
        self.assertEqual(path.read_bytes(), before)

    def test_remove_and_second_run_changes_nothing(self):
        km.apply(ENTRIES, appdata=self.appdata, store=self.store, running=lambda: False)
        km.apply([], appdata=self.appdata, store=self.store, running=lambda: False)
        self.assertEqual(self.read("24"), SAMPLE)
        again = km.apply([], appdata=self.appdata, store=self.store, running=lambda: False)
        self.assertFalse(any(r.changed for r in again))

    def test_wrong_encoding_is_refused(self):
        p = self.appdata / "ASCON" / "KOMPAS-3D" / "24" / "KOMPAS.kit.config"
        p.write_bytes(SAMPLE.encode("utf-8"))
        with self.assertRaises(km.MenuError):
            km.apply(ENTRIES, versions=["24"], appdata=self.appdata, store=self.store, running=lambda: False)

    def test_missing_config_is_an_error(self):
        with self.assertRaises(km.MenuError):
            km.apply(ENTRIES, appdata=Path(tempfile.mkdtemp()), store=self.store, running=lambda: False)


@unittest.skipUnless(os.environ.get("APPDATA") and km.kit_configs(), "нет настоящего KOMPAS.kit.config")
class RealFileCopy(unittest.TestCase):
    """Настоящий файл КОМПАС читается и правится КОПИЕЙ: оригинал не трогается."""

    def test_roundtrip_on_a_copy_of_the_real_config(self):
        ver, src = next(iter(km.kit_configs().items()))
        appdata = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, appdata, True)
        d = appdata / "ASCON" / "KOMPAS-3D" / ver
        d.mkdir(parents=True)
        shutil.copy2(src, d / "KOMPAS.kit.config")
        store = BackupStore(tempfile.mkdtemp(), trash=lambda p: None)
        km.apply([], appdata=appdata, store=store, running=lambda: False)     # в настоящем файле уже могут быть наши пункты
        original = (d / "KOMPAS.kit.config").read_bytes()
        km.apply(ENTRIES, appdata=appdata, store=store, running=lambda: False)
        added = (d / "KOMPAS.kit.config").read_bytes()
        self.assertGreater(len(added), len(original))
        km.apply([], appdata=appdata, store=store, running=lambda: False)
        self.assertEqual((d / "KOMPAS.kit.config").read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
