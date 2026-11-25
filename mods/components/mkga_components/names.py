"""Окно «Свои имена»: изменить, как называется стандарт в именах файлов и в поле «Наименование» (хранится локально)."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .catalog import NAME_KEYS

FIELD_LABELS = {
    "kind_name": ("Вид изделия", "Короткое имя для файла: «Винт», «Болт», «Шайба»."),
    "number": ("Обозначение стандарта", "Например «DIN 912» или «ISO 4762»; подставляется в имя и в «Наименование»."),
    "full_name": ("Полное название", "Идёт в начало поля «Наименование»."),
}


def changed_fields(std, values: dict[str, str]) -> dict[str, str]:
    """Только то, что отличается от исходных имён стандарта (пустое значение считается «как в стандарте»)."""
    base = std.defaults or (std.number, std.kind_name, std.full_name)
    originals = dict(zip(NAME_KEYS, base))
    return {k: v.strip() for k, v in values.items() if k in originals and v.strip() and v.strip() != originals[k]}


def open_names_dialog(win) -> None:
    std = win.std
    t = win.theme
    top = tk.Toplevel(win.root)
    top.title("Свои имена")
    top.configure(background=t.palette.bg)
    top.transient(win.root)
    top.resizable(False, False)
    frame = t.card(top)
    frame.grid(row=0, column=0, padx=t.pad, pady=t.pad)
    frame.columnconfigure(0, weight=1)
    wrap = t.px(520)
    base = dict(zip(NAME_KEYS, std.defaults or (std.number, std.kind_name, std.full_name)))
    current = {"number": std.number, "kind_name": std.kind_name, "full_name": std.full_name}
    vars_ = {k: tk.StringVar(value=current[k]) for k in NAME_KEYS}

    ttk.Label(frame, text=f"Имена: {base['number']}", style="Card.Heading.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Label(frame, text="Меняется только у вас и только для этого стандарта. Имя одной конкретной детали можно править "
                          "прямо в поле «Наименование» перед созданием.", style="Card.Small.Muted.TLabel",
              wraplength=wrap, justify="left").grid(row=1, column=0, sticky="w", pady=(0, t.pad_small))
    row = 2
    for key in ("kind_name", "number", "full_name"):
        label, hint = FIELD_LABELS[key]
        ttk.Label(frame, text=label, style="Card.Muted.TLabel").grid(row=row, column=0, sticky="w", pady=(t.pad_small, 0))
        ttk.Entry(frame, textvariable=vars_[key], style="Card.TEntry", width=64).grid(row=row + 1, column=0, sticky="ew")
        ttk.Label(frame, text=f"{hint}  По стандарту: {base[key]}", style="Card.Small.Muted.TLabel", wraplength=wrap,
                  justify="left").grid(row=row + 2, column=0, sticky="w")
        row += 3
    preview = tk.StringVar()
    ttk.Label(frame, text="Получится", style="Card.Muted.TLabel").grid(row=row, column=0, sticky="w", pady=(t.pad_small, 0))
    ttk.Label(frame, textvariable=preview, style="Card.TLabel", wraplength=wrap, justify="left").grid(
        row=row + 1, column=0, sticky="w")

    def refresh(*_):
        size = win._current_size() or std.size_labels[0]
        length = (std.lengths_for(size) or [None])[len(std.lengths_for(size)) // 2] if std.has_length else None
        file_stem = f"{vars_['kind_name'].get().strip() or std.kind_name} {vars_['number'].get().strip() or std.number}"
        file_stem += f" - {size.replace('.', ',')}" + (f" x {length:g}" if length else "")
        title = f"{vars_['full_name'].get().strip() or std.full_name} {vars_['number'].get().strip() or std.number}"
        preview.set(f"Файл: {file_stem}.m3d\nНаименование: {title} - {size.replace('.', ',')}" + (f" x {length:g}" if length else ""))

    for var in vars_.values():
        var.trace_add("write", refresh)
    refresh()

    buttons = ttk.Frame(frame, style="CardInner.TFrame", padding=0)
    buttons.grid(row=row + 2, column=0, sticky="ew", pady=(t.pad, 0))

    def save() -> None:
        fields = changed_fields(std, {k: v.get() for k, v in vars_.items()})
        top.destroy()
        win.save_names(std.id, fields or None)

    def reset() -> None:
        top.destroy()
        win.save_names(std.id, None)

    ttk.Button(buttons, text="Сохранить", style="Primary.TButton", command=save).pack(side="left")
    ttk.Button(buttons, text="Вернуть по стандарту", style="Card.TButton", command=reset).pack(side="left", padx=t.pad_small)
    ttk.Button(buttons, text="Отмена", style="Card.Ghost.TButton", command=top.destroy).pack(side="right")
    top.update_idletasks()
    x = win.root.winfo_rootx() + (win.root.winfo_width() - top.winfo_width()) // 2
    y = win.root.winfo_rooty() + t.px(80)
    top.geometry(f"+{max(0, x)}+{max(0, y)}")
    top.focus_set()
