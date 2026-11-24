"""Окно хаба на tkinter: каталог модов, установка, удаление, запуск.

Минимальный прототип. На Linux в среде разработки tkinter недоступен,
поэтому окно проверялось только на Windows (tk 8.6).
"""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .installer import install_from_registry, list_installed, uninstall
from .registry import load_registry, search
from .runner import run_mod


def launch(registry: str, mods_dir: Path) -> None:
    root = tk.Tk()
    root.title("MAKE KOMPAS GREAT AGAIN (неофициальный хаб модов)")
    root.geometry("820x480")

    try:
        entries = load_registry(registry)
        load_error = ""
    except Exception as e:  # сетевые и файловые ошибки показываем в окне
        entries, load_error = [], str(e)

    top = ttk.Frame(root, padding=8)
    top.pack(fill="x")
    ttk.Label(top, text="Поиск:").pack(side="left")
    query = tk.StringVar()
    ttk.Entry(top, textvariable=query, width=40).pack(side="left", padx=6)

    cols = ("name", "version", "state", "description")
    tree = ttk.Treeview(root, columns=cols, show="headings", selectmode="browse")
    for col, title, width in (("name", "Мод", 200), ("version", "Версия", 80),
                              ("state", "Состояние", 110), ("description", "Описание", 400)):
        tree.heading(col, text=title)
        tree.column(col, width=width, anchor="w")
    tree.pack(fill="both", expand=True, padx=8)

    status = tk.StringVar(value=load_error or "Готово")
    ttk.Label(root, textvariable=status, padding=8).pack(fill="x")

    def refresh(*_):
        installed = {m.id: m for m in list_installed(mods_dir)}
        tree.delete(*tree.get_children())
        for e in search(entries, query.get()):
            m = installed.get(e.id)
            if m is None:
                state = "не установлен"
            elif m.version == e.tag.lstrip("v"):
                state = "установлен"
            else:
                state = f"есть {m.version}"
            tree.insert("", "end", iid=e.id, values=(e.name, e.tag, state, e.description))

    def selected():
        sel = tree.selection()
        return next((e for e in entries if sel and e.id == sel[0]), None)

    def in_thread(fn, ok_text):
        def work():
            try:
                fn()
                root.after(0, lambda: status.set(ok_text))
            except Exception as ex:
                root.after(0, lambda: messagebox.showerror("Ошибка", str(ex)))
            root.after(0, refresh)
        threading.Thread(target=work, daemon=True).start()

    def do_install():
        e = selected()
        if e:
            status.set(f"Устанавливаю {e.name}…")
            in_thread(lambda: install_from_registry(e, mods_dir), f"Установлено: {e.name}")

    def do_uninstall():
        e = selected()
        if e:
            in_thread(lambda: uninstall(e.id, mods_dir), f"Удалено: {e.name}")

    def do_run():
        e = selected()
        if e:
            in_thread(lambda: run_mod(mods_dir, e.id), f"Запущено: {e.name}")

    btns = ttk.Frame(root, padding=8)
    btns.pack(fill="x")
    ttk.Button(btns, text="Установить / обновить", command=do_install).pack(side="left")
    ttk.Button(btns, text="Запустить", command=do_run).pack(side="left", padx=6)
    ttk.Button(btns, text="Удалить", command=do_uninstall).pack(side="left")

    query.trace_add("write", refresh)
    refresh()
    root.mainloop()
