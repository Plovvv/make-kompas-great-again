"""Тесты окна хаба на подставных данных: сеть, запуск процессов и диалоги подменены."""

import gc
import json
import shutil
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from tests.test_ui import display_available


def settle(win, condition, timeout=5.0):
    """Крутить события окна, пока условие не выполнится."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        win.root.update()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("условие не выполнилось за отведённое время")


@unittest.skipUnless(display_available(), "нет дисплея для tkinter")
class HubTests(unittest.TestCase):
    def setUp(self):
        from mkga.core.safe_io import BackupStore
        from mkga.registry import RegistryEntry
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.mods = self.base / "mods"
        self.store = BackupStore(self.base / "backups", trash=lambda p: p.unlink())
        self.entries = [
            RegistryEntry("fasteners", "Метизы", "Винты и гайки", "o/r", "v0.2.0", "0" * 64, ("каталог",)),
            RegistryEntry("converter", "Конвертер", "Сохранение в v22", "o/r", "v1.0.0", "0" * 64),
        ]
        self.launched = []
        self.installed_calls = []
        self.win = None

    def tearDown(self):
        if self.win is not None:
            self.win.close()
            self.win = None
        gc.collect()  # объекты Tk удаляются здесь, в главном потоке
        self._tmp.cleanup()

    # --- помощники ---------------------------------------------------------------------------
    def _write_mod(self, mod_id, version="0.1.0", name=None):
        from mkga.manifest import parse_manifest
        from tests.helpers import good_manifest
        data = good_manifest(id=mod_id, version=version, name=name or mod_id.title(), kompas_versions=[24])
        d = self.mods / mod_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "mkga-mod.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        (d / "main.py").write_text("def run(ctx):\n    pass\n", encoding="utf-8")
        return parse_manifest(data)

    def _fake_installer(self, entry, mods_dir):
        self.installed_calls.append(entry.id)
        return self._write_mod(entry.id, entry.tag.lstrip("v"), entry.name)

    def _hub(self, loader=None, **kw):
        from mkga.ui.hub import HubWindow
        self.win = HubWindow(
            mods_dir=self.mods, registry="demo", store=self.store, theme_name="light",
            loader=loader or (lambda src: self.entries), installer=self._fake_installer,
            launcher=lambda mods_dir, mod_id, on_line, on_exit: self.launched.append((mods_dir, mod_id, on_line, on_exit)),
            **kw)
        settle(self.win, lambda: self.win.catalog_loaded)
        return self.win

    def _ids(self):
        return list(self.win.tree.get_children())

    def _select(self, mod_id):
        self.win.tree.selection_set(mod_id)
        self.win._on_select()

    def log(self):
        return self.win.log_text.get("1.0", "end")

    # --- каталог ---------------------------------------------------------------------------------
    def test_catalog_lists_modes_with_states(self):
        self._write_mod("fasteners", "0.1.0")           # установлен, в каталоге новее
        self._write_mod("my-script", "0.0.1")           # свой
        win = self._hub()
        rows = {i: win.tree.item(i, "values") for i in self._ids()}
        self.assertEqual(set(rows), {"fasteners", "converter", "my-script"})
        self.assertEqual(rows["fasteners"][2], "Есть обновление")
        self.assertEqual(rows["converter"][2], "Не установлен")
        self.assertEqual(rows["my-script"][2], "Свой (не из каталога)")

    def test_empty_catalog_explains_itself(self):
        win = self._hub(loader=lambda src: [])
        self.assertEqual(self._ids(), [])
        self.assertIn("пока нет модов", win.empty_title.cget("text"))

    def test_catalog_error_is_shown_with_retry(self):
        def broken(src):
            raise urllib.error.URLError("no network")
        win = self._hub(loader=broken)
        self.assertIn("Не удалось загрузить каталог", win.empty_title.cget("text"))
        self.assertIn("Нет доступа к каталогу", win.empty_text.cget("text"))
        self.assertTrue(win.empty_btn.winfo_manager())          # кнопка «Повторить» видна
        self.assertIn("Нет доступа к каталогу", self.log())

    def test_search_filters_rows(self):
        win = self._hub()
        win.search_var.set("винты")
        win._render_list()
        self.assertEqual(self._ids(), ["fasteners"])
        win.search_var.set("zzz")
        win._render_list()
        self.assertEqual(self._ids(), [])
        self.assertEqual(win.empty_title.cget("text"), "Ничего не найдено")

    # --- детали и кнопки -------------------------------------------------------------------------
    def test_buttons_follow_the_state_of_the_selected_mod(self):
        self._write_mod("converter", "1.0.0")           # актуальный
        win = self._hub()
        self._select("fasteners")                       # только в каталоге
        self.assertEqual(win.install_btn.cget("text"), "Установить")
        self.assertFalse(win.install_btn.instate(["disabled"]))
        self.assertTrue(win.run_btn.instate(["disabled"]))
        self.assertTrue(win.remove_btn.instate(["disabled"]))
        self._select("converter")                       # установлен и актуален
        self.assertFalse(win.run_btn.instate(["disabled"]))
        self.assertFalse(win.remove_btn.instate(["disabled"]))
        self.assertEqual(win.install_btn.winfo_manager(), "")   # установить нечего: кнопки нет

    def test_details_show_compatibility_after_kompas_check(self):
        self._write_mod("converter", "1.0.0")           # проверен на v24
        win = self._hub()
        self._select("converter")
        self.assertIn("Проверить", win.d_compat.cget("text"))
        win.on_kompas((24, 0, 3, 0))
        self.assertTrue(win.d_compat.cget("text").startswith("✓"))
        win.on_kompas((25, 0, 0, 0))
        self.assertTrue(win.d_compat.cget("text").startswith("!"))

    # --- установка, удаление, запуск -----------------------------------------------------------
    def test_install_updates_the_list(self):
        win = self._hub()
        self._select("fasteners")
        win._install_selected()
        win.wait_idle()
        self.assertEqual(self.installed_calls, ["fasteners"])
        self.assertEqual(win.tree.item("fasteners", "values")[2], "Установлен")
        self.assertIn("Установлено: Метизы", self.log())

    def test_install_error_is_reported_not_raised(self):
        from mkga.installer import InstallError
        win = self._hub()
        win._installer = mock.Mock(side_effect=InstallError("хеш архива не совпал с реестром"))
        self._select("fasteners")
        win._install_selected()
        win.wait_idle()
        self.assertIn("хеш архива не совпал", self.log())
        self.assertEqual(win.tree.item("fasteners", "values")[2], "Не установлен")

    def test_uninstall_asks_and_removes(self):
        self._write_mod("converter", "1.0.0")
        win = self._hub()
        self._select("converter")
        with mock.patch("tkinter.messagebox.askyesno", return_value=False):
            win._uninstall_selected()
        self.assertTrue((self.mods / "converter").exists())      # отказались: ничего не удалено
        with mock.patch("tkinter.messagebox.askyesno", return_value=True):
            win._uninstall_selected()
            win.wait_idle()
        self.assertFalse((self.mods / "converter").exists())
        self.assertEqual(win.tree.item("converter", "values")[2], "Не установлен")

    def test_run_starts_a_separate_process_and_logs_its_output(self):
        self._write_mod("converter", "1.0.0")
        win = self._hub()
        self._select("converter")
        win._run_selected()
        (mods_dir, mod_id, on_line, on_exit), = self.launched
        self.assertEqual((Path(mods_dir), mod_id), (self.mods, "converter"))
        on_line("привет из мода")
        on_exit(2)
        settle(win, lambda: "завершился с ошибкой" in self.log())
        self.assertIn("[converter] привет из мода", self.log())
        self.assertIn("Хаб и другие моды не затронуты", self.log())

    def test_mod_needing_unbundled_packages_is_not_run_in_the_frozen_build(self):
        from mkga.manifest import parse_manifest
        from tests.helpers import good_manifest
        data = good_manifest(id="needs-numpy", requires=["numpy"], kompas_versions=[24])
        d = self.mods / "needs-numpy"
        d.mkdir(parents=True)
        (d / "mkga-mod.json").write_text(json.dumps(data), encoding="utf-8")
        (d / "main.py").write_text("def run(ctx):\n    pass\n", encoding="utf-8")
        win = self._hub()
        self._select("needs-numpy")
        self.assertNotIn("numpy", win.d_compat.cget("text"))             # из исходников пакеты ставит пользователь
        with mock.patch.object(__import__("sys"), "frozen", True, create=True):
            win._show_details()
            self.assertIn("numpy", win.d_compat.cget("text"))
            win._run_selected()
        self.assertEqual(self.launched, [])                              # процесс не запускался
        settle(win, lambda: "не запущен: ему нужны пакеты" in self.log())

    def test_install_from_file_warns_first(self):
        win = self._hub()
        win._zip_installer = mock.Mock(return_value=self._write_mod("from-zip", "0.0.1"))
        with mock.patch("tkinter.filedialog.askopenfilename", return_value="C:/x/mod.zip"), \
                mock.patch("tkinter.messagebox.askyesno", return_value=False) as ask:
            win._install_from_file()
        win._zip_installer.assert_not_called()                    # отказались после предупреждения
        self.assertIn("выполняет код", ask.call_args[0][1])
        with mock.patch("tkinter.filedialog.askopenfilename", return_value="C:/x/mod.zip"), \
                mock.patch("tkinter.messagebox.askyesno", return_value=True):
            win._install_from_file()
            win.wait_idle()
        win._zip_installer.assert_called_once()
        self.assertIn("from-zip", self._ids())

    # --- история и откат ------------------------------------------------------------------------
    def _make_history(self):
        f = self.base / "f.txt"
        f.write_text("до", encoding="utf-8")
        with self.store.begin("fasteners", "Правка файла") as s:
            s.write_text(f, "после")
        return f

    # --- меню КОМПАС -----------------------------------------------------------------------------
    def test_kompas_menu_button_adds_and_removes_entries(self):
        from mkga import kompas_menu as km
        from tests.test_kompas_menu import SAMPLE, make_appdata
        appdata = make_appdata()
        self.addCleanup(shutil.rmtree, appdata, True)
        exe = self.mods.parent / "MKGA.exe"
        exe.write_bytes(b"x")
        self._write_mod("fasteners", "0.1.0")
        win = self._hub()
        real_apply = km.apply
        with mock.patch.dict("os.environ", {"APPDATA": str(appdata)}),                 mock.patch.object(km, "find_exe", return_value=exe),                 mock.patch.object(km, "is_kompas_running", return_value=False),                 mock.patch.object(km, "apply", lambda entries, **kw: real_apply(entries, running=lambda: False, **kw)):
            with mock.patch("tkinter.messagebox.askyesnocancel", return_value=True):
                win._kompas_menu()
            self.assertEqual(km.status(), {"24": 1})                # пункт хаба (мод fasteners не приложение)
            settle(win, lambda: "пунктов MKGA было 0, стало 1" in self.log())
            with mock.patch("tkinter.messagebox.askyesnocancel", return_value=False):
                win._kompas_menu()
            self.assertEqual(km.status(), {"24": 0})
            with mock.patch("tkinter.messagebox.askyesnocancel", return_value=None):
                win._kompas_menu()
            self.assertEqual(km.read_config(appdata / "ASCON" / "KOMPAS-3D" / "24" / "KOMPAS.kit.config"), SAMPLE)

    def test_kompas_menu_refuses_while_kompas_runs(self):
        from mkga import kompas_menu as km
        from tests.test_kompas_menu import make_appdata
        appdata = make_appdata()
        self.addCleanup(shutil.rmtree, appdata, True)
        exe = self.mods.parent / "MKGA.exe"
        exe.write_bytes(b"x")
        win = self._hub()
        real_apply = km.apply
        with mock.patch.dict("os.environ", {"APPDATA": str(appdata)}), mock.patch.object(km, "find_exe", return_value=exe),                 mock.patch.object(km, "apply", lambda entries, **kw: real_apply(entries, running=lambda: True, **kw)),                 mock.patch("tkinter.messagebox.askyesnocancel", return_value=True):
            win._kompas_menu()
        settle(win, lambda: "КОМПАС запущен" in self.log())
        self.assertEqual(km.status(appdata=appdata), {"24": 0})

    def test_history_lists_and_undoes(self):
        f = self._make_history()
        win = self._hub()
        win.show_page("history")
        (row_id,) = win.history_tree.get_children()
        self.assertEqual(win.history_tree.item(row_id, "values")[3], "Применено")
        self.assertTrue(win.undo_btn.instate(["disabled"]))       # ничего не выбрано
        win.history_tree.selection_set(row_id)
        win._update_history_buttons()
        self.assertFalse(win.undo_btn.instate(["disabled"]))
        with mock.patch("tkinter.messagebox.askyesno", return_value=True):
            win._undo_selected()
            win.wait_idle()
        self.assertEqual(f.read_text(encoding="utf-8"), "до")
        self.assertEqual(win.history_tree.item(row_id, "values")[3], "Откачено")
        self.assertIn("Откат выполнен", self.log())

    def test_undo_conflict_asks_and_can_be_declined(self):
        f = self._make_history()
        f.write_text("правка пользователя после операции", encoding="utf-8")
        win = self._hub()
        win.show_page("history")
        (row_id,) = win.history_tree.get_children()
        win.history_tree.selection_set(row_id)
        win._update_history_buttons()
        answers = iter([True, False])                              # подтвердить откат, отказаться от force
        with mock.patch("tkinter.messagebox.askyesno", side_effect=lambda *a, **k: next(answers)):
            win._undo_selected()
            win.wait_idle()
        self.assertEqual(f.read_text(encoding="utf-8"), "правка пользователя после операции")  # не затёрто
        self.assertIn("Откат отменён", self.log())

    # --- состояние -----------------------------------------------------------------------------
    def test_export_state_survives_a_theme_switch(self):
        win = self._hub()
        win.search_var.set("метиз")
        win._render_list()
        self._select("fasteners")
        win.show_page("catalog")
        state = win.export_state()
        self.assertEqual((state["page"], state["query"], state["selected"]), ("catalog", "метиз", "fasteners"))
        self.assertEqual(len(state["entries"]), 2)
        self.assertTrue(state["catalog_loaded"])
        win.close()
        self.win = self._hub_with_state(state)
        self.assertEqual(self.win.search_var.get(), "метиз")
        self.assertEqual(self.win._selected, "fasteners")

    def _hub_with_state(self, state):
        from mkga.ui.hub import HubWindow
        return HubWindow(mods_dir=self.mods, registry="demo", store=self.store, theme_name="dark",
                         loader=lambda s: [], state=state)

    def test_cycle_theme_saves_choice_and_requests_restart(self):
        win = self._hub()
        win._cycle_theme()
        self.assertTrue(win.restart_requested)
        from mkga.core.settings import Settings
        saved = Settings(self.mods.parent / "data" / "hub" / "settings.json").get("theme")
        self.assertEqual(saved, "dark")       # цикл: system -> light -> dark; стартовали со светлой, значит дальше тёмная

    def test_run_hub_recreates_window_with_new_theme(self):
        # смена темы закрывает окно и создаёт новое; страница и поиск сохраняются
        from mkga.ui import hub
        seen = []

        class FakeWin:
            def __init__(self, **kw):
                seen.append((kw["theme_name"], kw["state"]))
                self.restart_requested = len(seen) == 1

            def mainloop(self):
                pass

            def export_state(self):
                return {"page": "history"}

        with mock.patch.object(hub, "HubWindow", FakeWin):
            hub.run_hub("demo", self.mods)
        self.assertEqual([s[0] for s in seen], ["system", "system"])
        self.assertEqual(seen[1][1], {"page": "history"})


if __name__ == "__main__":
    unittest.main()
