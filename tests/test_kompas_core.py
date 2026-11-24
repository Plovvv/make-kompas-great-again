"""Тесты ядра подключения к КОМПАСу. Настоящий КОМПАС и pywin32 не нужны:
win32com подменяется заглушкой, поэтому тесты безопасны на машине с запущенным КОМПАСом."""

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from mkga.core.kompas import Kompas, KompasNotAvailable, connect
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
            ctx = ModContext(mod_dir=ROOT / "mods" / "fasteners", data_dir=Path(tmp) / "d", log=logs.append)
            run_mod_dir(ROOT / "mods" / "fasteners", ctx)
            self.assertTrue(logs)
            self.assertTrue((Path(tmp) / "d").is_dir())


if __name__ == "__main__":
    unittest.main()
