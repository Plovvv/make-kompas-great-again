"""Тесты окна мода и демо. Нужен дисплей (Windows или Linux с X): без него тесты пропускаются."""

import gc
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import tkinter as tk
except ImportError:  # на некоторых Linux tkinter не установлен
    tk = None


def display_available() -> bool:
    if tk is None:
        return False
    try:
        r = tk.Tk()
        r.destroy()
        return True
    except tk.TclError:
        return False


@unittest.skipUnless(display_available(), "нет дисплея для tkinter")
class DemoWindowTests(unittest.TestCase):
    def setUp(self):
        from mkga.ui.demo import build_demo
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.win = build_demo(fake_kompas=True, base_dir=self.base, auto_check=False)
        self.undo, self.preview, self.apply = self.win._actions.winfo_children()  # порядок кнопок в демо

    def tearDown(self):
        self.win.close()
        del self.win, self.preview, self.apply, self.undo
        gc.collect()  # объекты Tk должны быть удалены здесь, в главном потоке
        self._tmp.cleanup()

    def log(self) -> str:
        return self.win.log_text.get("1.0", "end")

    def rows(self):
        return [self.win.changes_tree.item(i, "values") for i in self.win.changes_tree.get_children()]

    def test_check_kompas_shows_version_and_edition(self):
        self.win.check_kompas()
        self.win.wait_idle()
        text = self.win._kompas_var.get()
        self.assertIn("24.0.3.0", text)
        self.assertIn("Фейковая деталь.m3d", self.log())

    def test_preview_lists_changes_and_writes_nothing(self):
        self.preview.invoke()
        self.win.wait_idle()
        self.assertEqual([r[0] for r in self.rows()], ["Создать", "Изменить"])
        self.assertFalse((self.base / "files" / "Новый файл.txt").exists())
        self.assertEqual((self.base / "files" / "Сборка.txt").read_text(encoding="utf-8"), "исходное содержимое\n")

    def test_apply_then_undo_restores_files(self):
        self.apply.invoke()
        self.win.wait_idle()
        new = self.base / "files" / "Новый файл.txt"
        existing = self.base / "files" / "Сборка.txt"
        self.assertTrue(new.exists())
        self.assertEqual(existing.read_text(encoding="utf-8"), "изменённое содержимое\n")
        self.undo.invoke()
        self.win.wait_idle()
        self.assertFalse(new.exists())
        self.assertEqual(existing.read_text(encoding="utf-8"), "исходное содержимое\n")
        self.assertEqual(self.rows(), [])
        self.assertIn("Откат выполнен", self.log())

    def test_buttons_disabled_while_busy_and_enabled_after(self):
        import threading
        gate = threading.Event()
        self.win.run_in_background(lambda ctx: gate.wait(30), "долго")
        # состояние кнопок выставляется синхронно, поэтому проверка не зависит от скорости отрисовки окна
        self.assertTrue(self.apply.instate(["disabled"]))
        self.assertTrue(self.preview.instate(["disabled"]))
        gate.set()
        self.win.wait_idle()
        self.assertFalse(self.apply.instate(["disabled"]))

    def test_action_error_is_logged_and_window_survives(self):
        def boom(ctx):
            raise RuntimeError("мод сломался")

        self.win.run_in_background(boom, "сбой")
        self.win.wait_idle()
        self.assertIn("мод сломался", self.log())
        self.assertIn("ошибка", self.win._status_var.get())
        self.assertTrue(self.win.root.winfo_exists())

    def test_version_warning_asks_user_in_main_thread(self):
        self.win.ctx.tested_versions = [23]  # КОМПАС v24 «новее проверенного»: нужно подтверждение
        with mock.patch("mkga.ui.window.messagebox.askyesno", return_value=True) as ask:
            self.win.check_kompas()
            self.win.wait_idle()
        self.assertEqual(ask.call_count, 1)
        self.assertIn("24.0.3.0", self.win._kompas_var.get())

    def test_version_warning_declined_blocks_connection(self):
        self.win.ctx.tested_versions = [23]
        with mock.patch("mkga.ui.window.messagebox.askyesno", return_value=False):
            self.win.check_kompas()
            self.win.wait_idle()
        self.assertIn("не подключён", self.win._kompas_var.get())
        self.assertIn("Подтверждения не получено", self.log())


@unittest.skipIf(tk is None, "tkinter не установлен")
class ThemeTests(unittest.TestCase):
    def test_enable_dpi_awareness_is_safe_everywhere(self):
        from mkga.ui.theme import enable_dpi_awareness
        self.assertIn(enable_dpi_awareness(), (True, False))

    @unittest.skipUnless(display_available(), "нет дисплея для tkinter")
    def test_widget_background_never_leaves_parent_colour(self):
        # Регресс: при открытии списка комбобокса (состояние pressed) clam красил углы серым.
        from tkinter import ttk
        from mkga.ui.theme import DARK, LIGHT, apply_theme
        for palette in (LIGHT, DARK):
            root = tk.Tk()
            try:
                apply_theme(root, palette)
                style = ttk.Style(root)
                for prefix, around in (("", palette.bg), ("Card.", palette.surface)):
                    for base in ("TButton", "Primary.TButton", "Ghost.TButton", "TEntry", "TCombobox",
                                 "Horizontal.TProgressbar", "PillOk.TLabel", "PillError.TLabel", "PillMuted.TLabel",
                                 "TCheckbutton", "TRadiobutton"):
                        for state in ("active", "pressed", "focus", "readonly", "disabled", "selected"):
                            got = str(style.lookup(prefix + base, "background", [state]))
                            self.assertEqual(got.lower(), around.lower(), f"{palette.name} {prefix}{base} {state}")
            finally:
                root.destroy()

    @unittest.skipUnless(display_available(), "нет дисплея для tkinter")
    def test_px_scales_with_dpi_and_theme_applies(self):
        from mkga.ui.theme import apply_theme
        root = tk.Tk()
        try:
            theme = apply_theme(root)
            expected = round(12 * root.winfo_fpixels("1i") / 96)
            self.assertEqual(theme.px(12), expected)
            self.assertGreaterEqual(theme.pad, 1)
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
