"""Демо окна мода (`python -m mkga ui-demo`): образец для авторов модов и смотровая для интерфейса.

Показывает весь путь: параметры, предпросмотр изменений, применение с откатом, журнал, статус КОМПАСа.
Демо пишет ТОЛЬКО во временную папку (%TEMP%\\mkga-demo-*), к вашим файлам и документам КОМПАСа не
прикасается; с настоящим КОМПАСом оно лишь читает версию, редакцию и имя активного документа.
"""

from __future__ import annotations

import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from ..core.fake import FakeDocument, make_fake_kompas
from ..core.safe_io import BackupStore
from ..runner import ModContext
from .theme import DARK, LIGHT
from .window import ModWindow


def build_demo(fake_kompas: bool = True, base_dir: Path | None = None, dark: bool = False,
               auto_check: bool = True) -> ModWindow:
    base = Path(base_dir) if base_dir else Path(tempfile.mkdtemp(prefix="mkga-demo-"))
    work = base / "files"
    work.mkdir(parents=True, exist_ok=True)
    existing = work / "Сборка.txt"
    existing.write_text("исходное содержимое\n", encoding="utf-8")

    # В демо «корзина» просто удаляет файлы из временной папки, чтобы не засорять настоящую корзину.
    store = BackupStore(base / "backups", trash=lambda p: p.unlink())
    connect = (lambda: make_fake_kompas(documents=[FakeDocument("Фейковая деталь.m3d")])) if fake_kompas else None
    ctx = ModContext(mod_dir=Path(__file__).parent, data_dir=base / "data", backups=store,
                     mod_id="ui-demo", connect=connect)
    win = ModWindow(ctx, "Демо окна мода", version="0.0.0", palette=DARK if dark else LIGHT)
    t = win.theme
    last_session: list[str] = []

    # --- параметры (внутри карточки используем стили Card.*) -------------------------------
    name = tk.StringVar(value="Новый файл.txt")
    standard = tk.StringVar(value="Вариант A")
    touch = tk.BooleanVar(value=True)
    win.params.columnconfigure(0, weight=1)
    ttk.Label(win.params, text="Имя нового файла", style="Card.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Entry(win.params, textvariable=name, style="Card.TEntry", width=28).grid(
        row=1, column=0, sticky="ew", pady=(t.px(4), t.pad))
    ttk.Label(win.params, text="Вариант", style="Card.TLabel").grid(row=2, column=0, sticky="w")
    ttk.Combobox(win.params, textvariable=standard, values=("Вариант A", "Вариант B"), state="readonly",
                 style="Card.TCombobox").grid(row=3, column=0, sticky="ew", pady=(t.px(4), t.pad))
    ttk.Checkbutton(win.params, text="Изменить и существующий файл «Сборка.txt»", variable=touch,
                    style="Card.TCheckbutton").grid(row=4, column=0, sticky="w")
    ttk.Label(win.params, style="Card.Muted.TLabel", wraplength=t.px(250), justify="left",
              text=f"Все файлы демо лежат во временной папке:\n{work}").grid(row=5, column=0, sticky="w",
                                                                             pady=(t.pad, 0))

    def values():
        return name.get().strip() or "Новый файл.txt", standard.get(), touch.get()

    def plan(session, vals) -> None:
        file_name, variant, touch_existing = vals
        session.write_text(work / file_name, f"Демо-файл\n{variant}\n")
        if touch_existing:
            session.write_text(existing, "изменённое содержимое\n")

    # --- действия ------------------------------------------------------------------------
    def preview(c: ModContext, vals) -> None:
        with c.session("Демо: предпросмотр", dry_run=True) as s:
            plan(s, vals)
            win.set_changes(s.changes)
        c.log(f"Предпросмотр: файлов {len(s.changes)}. Ничего не записано.", tag="muted")

    def apply(c: ModContext, vals) -> None:
        with c.session("Демо: применение") as s:
            plan(s, vals)
            last_session.append(s.info.id)
        win.set_changes(s.changes)
        c.log(f"Готово: записано файлов {len(s.changes)} (сессия {s.info.id}).", tag="ok")

    def undo(c: ModContext) -> None:
        if not last_session:
            c.log("Откатывать нечего.", tag="muted")
            return
        report = c.backups.undo(last_session.pop())
        if report.ok:
            win.set_changes([])
            c.log(f"Откат выполнен, возвращено файлов: {len(report.restored)}.", tag="ok")
        else:
            c.log("Откат отклонён: файлы изменены после операции: " + ", ".join(report.conflicts), tag="error")

    win.add_action("Отменить последнее", undo, icon="undo")
    win.add_action("Предпросмотр", preview, params=values, icon="view")
    win.add_action("Выполнить", apply, primary=True, params=values, icon="play")
    if auto_check:  # при запуске сразу показать статус КОМПАСа (тесты отключают: нужна детерминированность)
        win.root.after(300, win.check_kompas)
    return win


def run_demo(fake_kompas: bool = True, dark: bool = False) -> None:
    build_demo(fake_kompas, dark=dark).mainloop()
