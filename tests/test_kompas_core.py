"""Тесты ядра подключения к КОМПАСу. Настоящий КОМПАС и pywin32 не нужны:
win32com подменяется заглушкой, поэтому тесты безопасны на машине с запущенным КОМПАСом."""

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from mkga.core.fake import FakeDocument, make_fake_kompas
from mkga.core.kompas import Kompas, KompasNotAvailable, connect, force_late_binding, out_ints
from mkga.runner import ModContext, run_mod_dir

ROOT = Path(__file__).resolve().parent.parent


class FakeComError(Exception):
    pass


def fake_win32(running: bool):
    """Подмена pythoncom/win32com. running=True: КОМПАС «запущен», иначе GetActiveObject падает."""
    calls = {"dispatch": [], "active": []}
    app7 = mock.MagicMock(name="app7")
    api7 = mock.MagicMock(name="api7")
    api7.Application = app7
    api5 = mock.MagicMock(name="api5")

    class FakeUnknown:
        def __init__(self, obj):
            self.obj = obj

        def QueryInterface(self, _iid):
            return self.obj

    def get_active(progid):
        calls["active"].append(progid)
        if not running:
            raise FakeComError("Операция недоступна")
        return FakeUnknown(api5 if progid.endswith(".5") else api7)

    def dispatch(target):
        if isinstance(target, str):  # запуск нового экземпляра по ProgID
            calls["dispatch"].append(target)
            return api5 if target.endswith(".5") else api7
        return target  # уже полученный IDispatch: оборачиваем как есть

    pythoncom = types.ModuleType("pythoncom")
    pythoncom.com_error = FakeComError
    pythoncom.GetActiveObject = get_active
    pythoncom.IID_IDispatch = "IID_IDispatch"
    dynamic = types.ModuleType("win32com.client.dynamic")
    dynamic.Dispatch = dispatch
    client = types.ModuleType("win32com.client")
    client.dynamic = dynamic
    win32com = types.ModuleType("win32com")
    win32com.client = client
    modules = {"pythoncom": pythoncom, "win32com": win32com,
               "win32com.client": client, "win32com.client.dynamic": dynamic}
    return modules, calls, app7


class ConnectTests(unittest.TestCase):
    def test_not_running_does_not_launch_new_instance(self):
        modules, calls, _ = fake_win32(running=False)
        with mock.patch.dict(sys.modules, modules):
            with self.assertRaises(KompasNotAvailable) as cm:
                connect()
        self.assertEqual(calls["dispatch"], [])  # новый КОМПАС не запускался
        self.assertIn("не запущен", str(cm.exception))

    def test_attaches_to_running_without_changing_visibility(self):
        modules, calls, app7 = fake_win32(running=True)
        with mock.patch.dict(sys.modules, modules):
            k = connect()
        self.assertEqual(calls["dispatch"], [])
        self.assertEqual(sorted(calls["active"]), ["Kompas.Application.5", "Kompas.Application.7"])
        self.assertIs(k.app7, app7)
        self.assertIsNot(app7.Visible, True)  # видимость чужого окна не трогали

    def test_launch_true_starts_and_shows(self):
        modules, calls, app7 = fake_win32(running=False)
        with mock.patch.dict(sys.modules, modules):
            connect(launch=True)
        self.assertEqual(sorted(calls["dispatch"]), ["Kompas.Application.5", "Kompas.Application.7"])
        self.assertIs(app7.Visible, True)


class VersionTests(unittest.TestCase):
    def test_version_tuple(self):
        app7 = mock.MagicMock()
        app7.GetSystemVersion.return_value = (True, 24, 0, 3, 0)
        k = Kompas(api5=None, api7=None, app7=app7)
        self.assertEqual(k.version, (24, 0, 3, 0))

    def test_version_failure(self):
        app7 = mock.MagicMock()
        app7.GetSystemVersion.return_value = (False, 0, 0, 0, 0)
        k = Kompas(api5=None, api7=None, app7=app7)
        with self.assertRaises(KompasNotAvailable):
            k.version


class RunDirTests(unittest.TestCase):
    def test_run_mod_dir_uses_given_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs = []
            ctx = ModContext(mod_dir=ROOT / "mods" / "_template", data_dir=Path(tmp) / "d", log=logs.append,
                             connect=lambda: make_fake_kompas(documents=[FakeDocument("Фейковый документ.m3d")]))
            run_mod_dir(ROOT / "mods" / "_template", ctx)
            self.assertTrue(logs)
            self.assertTrue((Path(tmp) / "d").is_dir())


if __name__ == "__main__":
    unittest.main()


class Api5OutParamsTests(unittest.TestCase):
    def test_api5_version_matches_api7_version_on_fake(self):
        from mkga.core.fake import make_fake_kompas
        for version in ((24, 0, 3, 0), (25, 1, 2, 3)):
            k = make_fake_kompas(version=version)
            self.assertEqual(k.api5_version, version)
            self.assertEqual(k.api5_version, k.version)

    def test_out_ints_without_pywin32_gives_plain_holders(self):
        hidden = {"pythoncom": None, "win32com": None, "win32com.client": None}
        with mock.patch.dict(sys.modules, hidden):
            outs = out_ints(3)
        self.assertEqual([o.value for o in outs], [0, 0, 0])

    def test_out_ints_with_pywin32_gives_byref_variants(self):
        try:
            import pythoncom  # noqa: F401
        except ImportError:
            self.skipTest("нужен pywin32")
        outs = out_ints(2)
        self.assertEqual(len(outs), 2)
        outs[0].value = 24  # VARIANT по ссылке принимает значение


class LateBindingTests(unittest.TestCase):
    def test_gen_py_cache_is_disabled_in_a_clean_process(self):
        import subprocess
        try:
            import win32com.gen_py  # noqa: F401
        except ImportError:
            self.skipTest("нужен pywin32")
        code = ("from mkga.core.kompas import force_late_binding; import win32com.gen_py as g;"
                "force_late_binding(); force_late_binding(); print(list(g.__path__))")
        r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "[]")  # импорт типизированных обёрток из кэша невозможен

    def test_force_late_binding_is_safe_without_pywin32(self):
        with mock.patch.dict(sys.modules, {"win32com": None, "win32com.gen_py": None}):
            force_late_binding()  # не падает


class DocumentLifecycleTests(unittest.TestCase):
    def test_new_document_can_be_closed_without_saving(self):
        from mkga.core import constants as C
        from mkga.core.fake import make_fake_kompas
        k = make_fake_kompas()
        before = k.app7.Documents.Count
        doc = k.new_document(C.ksDocumentPart, visible=False)
        self.assertEqual((k.app7.Documents.Count, doc.DocumentType, doc.Name), (before + 1, C.ksDocumentPart, ""))
        k.close_document(doc)
        self.assertEqual(k.app7.Documents.Count, before)
        self.assertEqual(doc.closed_with, 0)            # kdDoNotSaveChanges

    def test_close_with_save_uses_save_option(self):
        from mkga.core.fake import make_fake_kompas
        k = make_fake_kompas()
        doc = k.new_document(4)
        k.close_document(doc, save=True)
        self.assertEqual(doc.closed_with, 1)            # kdSaveChanges

    def test_users_documents_cannot_be_closed_by_a_mod(self):
        from mkga.core.fake import FakeDocument, make_fake_kompas
        from mkga.core.kompas import KompasError
        users = FakeDocument("Чертёж пользователя.cdw")
        k = make_fake_kompas(documents=[users])
        with self.assertRaises(KompasError):
            k.close_document(users)
        self.assertEqual(k.app7.Documents.Count, 1)     # не закрыт, правки не потеряны
        self.assertIsNone(users.closed_with)
