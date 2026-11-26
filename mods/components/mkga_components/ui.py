"""Окно мода «Каталог комплектующих»: дерево стандартов, параметры, 2D-чертёж, имя детали и создание.

Слева каталог (папки и стандарты) с поиском, посередине параметры выбранного стандарта (выпадающие списки
типоразмера, длины и класса прочности, таблица размеров с расшифровкой букв), справа упрощённый чертёж, снизу
имя будущего файла, «Наименование» детали, папка сохранения и галочка «открыть деталь после создания».
Логика (каталог, имена, построение) в соседних модулях; здесь только интерфейс на `mkga.ui.base.WindowBase`.
"""

from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from mkga.ui.base import WindowBase
from mkga.ui.theme import LIGHT, Palette

from . import drawing
from .builder import BuildError, Request, create_part, plan
from .catalog import Catalog, Standard, fmt_number, load_catalog, safe_filename, size_display

NO_CLASS = "не указывать"


def default_folder() -> Path:
    docs = Path.home() / "Documents"
    return docs if docs.is_dir() else Path.home()


class ComponentsWindow(WindowBase):
    def __init__(self, ctx, catalog: Catalog, *, version: str = "", palette: Palette = LIGHT,
                 user_dir: Path | None = None, builtin_dir: Path | None = None, names_file: Path | None = None):
        super().__init__(ctx, "Каталог комплектующих: MKGA (неофициальный)", size=(1260, 800), min_size=(1020, 640),
                         palette=palette)
        self.catalog = catalog
        self.user_dir = user_dir
        self.builtin_dir = builtin_dir
        self.names_file = names_file          # свои имена стандартов (names.json)
        self.version = version
        self.std: Standard | None = None
        self._tree_ids: dict[str, str] = {}
        self._redraw_job: str | None = None
        self.register("created", self._on_created)
        self.register("open_path", self._open_path)

        s = ctx.settings
        self.search_var = tk.StringVar()
        self.size_var = tk.StringVar()
        self.length_var = tk.StringVar()
        self.class_var = tk.StringVar(value=NO_CLASS)
        self.folder_var = tk.StringVar(value=s.get("folder", str(default_folder())))
        self.open_var = tk.BooleanVar(value=bool(s.get("open_after", True)))
        self.file_var = tk.StringVar()
        self.title_var = tk.StringVar()
        self.section_var = tk.StringVar()
        self.file_note_var = tk.StringVar()
        self._file_auto = self._title_auto = ""      # что подставлено автоматически
        self._manual_file = self._manual_title = False   # пользователь правил имя вручную
        self._build()
        self._fill_tree()
        for problem in catalog.problems:
            ctx.log(f"Каталог: {problem}", tag="error")
        last = s.get("last_standard")
        first = last if last in catalog.standards else ("din-912" if "din-912" in catalog.standards else next(iter(sorted(catalog.standards)), None))
        if first:
            self._select_standard(first)

    # --- построение интерфейса -------------------------------------------------------------------------------
    def _build(self) -> None:
        t, root = self.theme, self.root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        header = ttk.Frame(root, padding=(t.pad, t.pad_small, t.pad, 0))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(2, weight=1)
        ttk.Label(header, text="Каталог комплектующих", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text=f"версия {self.version}" if self.version else "", style="Small.Muted.TLabel"
                  ).grid(row=0, column=1, sticky="sw", padx=(t.pad_small, 0), pady=(0, t.px(6)))
        pill, check = self.build_kompas_pill(header)
        pill.grid(row=0, column=3, sticky="e", padx=(0, t.pad_small))
        check.grid(row=0, column=4, sticky="e")

        body = ttk.Frame(root, padding=(t.pad, t.pad_small, t.pad, 0))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(2, weight=1)
        body.rowconfigure(0, weight=1, minsize=t.px(300))   # на маленьком экране чертёж не должен схлопываться
        self._build_tree_card(body).grid(row=0, column=0, sticky="ns", padx=(0, t.pad))
        self._build_params_card(body).grid(row=0, column=1, sticky="ns", padx=(0, t.pad))
        self._build_drawing_card(body).grid(row=0, column=2, sticky="nsew")
        self._build_create_card(body).grid(row=1, column=0, columnspan=3, sticky="ew", pady=(t.pad_small, 0))

        self.build_log_card(root, height=1).grid(row=2, column=0, sticky="ew", padx=t.pad, pady=(t.pad_small, 0))
        self.build_footer(root).grid(row=3, column=0, sticky="ew")
        self.add_action("Создать деталь", self._create, primary=True, icon="play")
        self.add_action("Свои детали…", self._custom, icon="info")

    def add_action(self, text: str, handler, *, primary: bool = False, icon: str | None = None) -> ttk.Button:
        btn = ttk.Button(self._actions, text=self.label(text, icon),
                         style="Primary.TButton" if primary else "TButton", command=handler)
        btn.pack(side="left", padx=(self.theme.pad_small, 0))
        self._buttons.append(btn)
        return btn

    def _build_tree_card(self, parent) -> ttk.Frame:
        t = self.theme
        card = t.card(parent)
        card.rowconfigure(2, weight=1)
        ttk.Label(card, text="Каталог", style="Card.Heading.TLabel").grid(row=0, column=0, sticky="w")
        search = ttk.Entry(card, textvariable=self.search_var, style="Card.TEntry", width=26)
        search.grid(row=1, column=0, sticky="ew", pady=(t.pad_small, t.pad_small))
        self.search_var.trace_add("write", lambda *_: self._fill_tree())
        self.tree = ttk.Treeview(card, show="tree", selectmode="browse", height=10)
        self.tree.column("#0", width=t.px(270), stretch=True)
        self.tree.grid(row=2, column=0, sticky="nsew")
        sb = ttk.Scrollbar(card, orient="vertical", command=self.tree.yview)
        sb.grid(row=2, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        ttk.Label(card, text="Поиск: обозначение, аналог или название", style="Card.Small.Muted.TLabel"
                  ).grid(row=3, column=0, sticky="w", pady=(t.pad_small, 0))
        return card

    def _build_params_card(self, parent) -> ttk.Frame:
        t = self.theme
        card = t.card(parent)
        card.columnconfigure(0, weight=1)
        card.columnconfigure(1, weight=1)
        wrap = t.px(340)
        ttk.Label(card, text="Параметры", style="Card.Heading.TLabel").grid(row=0, column=0, sticky="w")
        head_buttons = ttk.Frame(card, style="CardInner.TFrame", padding=0)
        head_buttons.grid(row=0, column=1, sticky="e")
        self.std_title = ttk.Label(card, style="Card.TLabel", wraplength=wrap, justify="left")
        self.std_title.grid(row=1, column=0, columnspan=2, sticky="w", pady=(t.pad_small, 0))
        self.std_aliases = ttk.Label(card, style="Card.Small.Muted.TLabel", wraplength=wrap, justify="left")
        self.std_aliases.grid(row=2, column=0, columnspan=2, sticky="w")

        self.size_label, self.size_box = self._combo(card, 3, 0, "Типоразмер", self.size_var)
        self.length_label, self.length_box = self._combo(card, 3, 1, "Длина, мм", self.length_var)
        self.class_label, self.class_box = self._combo(card, 5, 0, "Класс прочности", self.class_var, span=2)
        self.size_box.bind("<<ComboboxSelected>>", lambda e: self._on_size_changed())
        self.length_box.bind("<<ComboboxSelected>>", lambda e: self._params_changed())
        self.class_box.bind("<<ComboboxSelected>>", lambda e: self._params_changed())

        self.std_verified = ttk.Label(card, style="Card.TLabel", wraplength=wrap, justify="left")
        self.std_verified.grid(row=7, column=0, columnspan=2, sticky="w", pady=(t.pad, 0))
        info = ttk.Button(head_buttons, text="Источник…", style="Card.Ghost.TButton", command=self._show_source)
        info.pack(side="left")
        names = ttk.Button(head_buttons, text="Свои имена…", style="Card.Ghost.TButton", command=self._edit_names)
        names.pack(side="left", padx=(t.px(4), 0))
        self._buttons += [info, names]
        card.rowconfigure(9, weight=1)
        return card

    def _combo(self, card, row: int, col: int, text: str, var: tk.StringVar, span: int = 1):
        """Подпись над выпадающим списком (две подписи в ряд). Возвращает (подпись, список)."""
        t = self.theme
        label = ttk.Label(card, text=text, style="Card.Muted.TLabel")
        label.grid(row=row, column=col, columnspan=span, sticky="w", pady=(t.pad_small, 0), padx=(0, t.pad_small))
        box = ttk.Combobox(card, textvariable=var, state="readonly", style="Card.TCombobox", width=12 if span == 1 else 28)
        box.grid(row=row + 1, column=col, columnspan=span, sticky="ew", padx=(0, t.pad_small if col == 0 and span == 1 else 0))
        return label, box

    def _build_drawing_card(self, parent) -> ttk.Frame:
        t = self.theme
        card = t.card(parent)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(1, weight=1)
        top = ttk.Frame(card, style="CardInner.TFrame", padding=0)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        ttk.Label(top, text="Чертёж", style="Card.Heading.TLabel").grid(row=0, column=0, sticky="w")
        self.views_hint = ttk.Label(top, style="Card.Small.Muted.TLabel")
        self.views_hint.grid(row=1, column=0, columnspan=2, sticky="w")
        self.canvas = tk.Canvas(card, background=self.theme.palette.surface, highlightthickness=0, borderwidth=0)
        self.canvas.grid(row=1, column=0, sticky="nsew", pady=(t.pad_small, 0))
        self.canvas.bind("<Configure>", lambda e: self._schedule_redraw())
        self.legend_frame = ttk.Frame(card, style="CardInner.TFrame", padding=0)
        self.legend_frame.grid(row=2, column=0, sticky="ew", pady=(t.pad_small, 0))
        for col in (1, 3):
            self.legend_frame.columnconfigure(col, weight=1)
        return card

    def _build_create_card(self, parent) -> ttk.Frame:
        t = self.theme
        card = t.card(parent, padding=t.pad_small + t.px(4))
        card.columnconfigure(1, weight=3)
        card.columnconfigure(4, weight=2)
        ttk.Label(card, text="Файл", style="Card.Muted.TLabel").grid(row=0, column=0, sticky="w", padx=(0, t.pad))
        file_row = ttk.Frame(card, style="CardInner.TFrame", padding=0)
        file_row.grid(row=0, column=1, sticky="ew")
        file_row.columnconfigure(0, weight=1)
        self.file_entry = ttk.Entry(file_row, textvariable=self.file_var, style="Card.TEntry")
        self.file_entry.grid(row=0, column=0, sticky="ew")
        ttk.Label(file_row, textvariable=self.file_note_var, style="Card.Small.Muted.TLabel").grid(
            row=0, column=1, sticky="w", padx=(t.px(4), 0))
        ttk.Label(card, text="Наименование", style="Card.Muted.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, t.pad), pady=(t.px(4), 0))
        self.title_entry = ttk.Entry(card, textvariable=self.title_var, style="Card.TEntry")
        self.title_entry.grid(row=1, column=1, sticky="ew", pady=(t.px(4), 0))
        for entry in (self.file_entry, self.title_entry):
            entry.bind("<KeyRelease>", lambda e: self._on_name_edited())
        ttk.Label(card, text="Раздел спецификации", style="Card.Muted.TLabel").grid(
            row=2, column=0, sticky="w", padx=(0, t.pad), pady=(t.px(4), 0))
        section_row = ttk.Frame(card, style="CardInner.TFrame", padding=0)
        section_row.grid(row=2, column=1, sticky="ew", pady=(t.px(4), 0))
        ttk.Label(section_row, textvariable=self.section_var, style="Card.TLabel").pack(side="left")
        reset = ttk.Button(section_row, text="Имена по стандарту", style="Card.Ghost.TButton", command=self._reset_names)
        reset.pack(side="right")
        self._buttons.append(reset)
        ttk.Separator(card, orient="vertical").grid(row=0, column=2, rowspan=3, sticky="ns", padx=t.pad)
        right = ttk.Frame(card, style="CardInner.TFrame", padding=0)
        right.grid(row=0, column=3, rowspan=3, columnspan=2, sticky="nsew")
        right.columnconfigure(0, weight=1)
        entry = ttk.Entry(right, textvariable=self.folder_var, style="Card.TEntry")
        entry.grid(row=0, column=0, sticky="ew")
        entry.bind("<KeyRelease>", lambda e: self._refresh_preview())
        browse = ttk.Button(right, text="Папка…", style="Card.TButton", command=self._browse)
        browse.grid(row=0, column=1, padx=(t.pad_small, 0))
        self._buttons.append(browse)
        ttk.Checkbutton(right, text="Открыть деталь в новой вкладке КОМПАС", variable=self.open_var,
                        style="Card.TCheckbutton").grid(row=1, column=0, columnspan=2, sticky="w", pady=(t.pad_small, 0))
        return card

    # --- дерево ------------------------------------------------------------------------------------------------
    def _fill_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._tree_ids.clear()
        found = {s.id for s in self.catalog.search(self.search_var.get())}
        for cid, cname in self.catalog.categories:
            standards = [s for s in self.catalog.in_category(cid) if s.id in found]
            if not standards:
                continue
            node = self.tree.insert("", "end", text=f"{cname}  ({len(standards)})", open=True)
            for s in standards:
                mark = "  ★" if s.origin == "user" else ""
                iid = self.tree.insert(node, "end", text=f"{s.number}  ·  {s.kind_name}{mark}")
                self._tree_ids[iid] = s.id
        if self.std is not None:
            self._focus_tree(self.std.id)

    def _focus_tree(self, std_id: str) -> None:
        for iid, sid in self._tree_ids.items():
            if sid == std_id:
                self.tree.selection_set(iid)
                self.tree.see(iid)
                return

    def _on_tree_select(self, _event=None) -> None:
        sel = self.tree.selection()
        if sel and sel[0] in self._tree_ids and self._tree_ids[sel[0]] != getattr(self.std, "id", None):
            self._select_standard(self._tree_ids[sel[0]])

    # --- выбор стандарта и параметров -----------------------------------------------------------------------------
    def _select_standard(self, std_id: str) -> None:
        std = self.catalog.standards[std_id]
        self.std = std
        self.ctx.settings.set("last_standard", std_id)
        self._focus_tree(std_id)
        self.std_title.configure(text=f"{std.full_name} {std.number}")
        aliases = ("Аналоги: " + "; ".join(std.aliases)) if std.aliases else ""
        if std.is_renamed:
            was = std.defaults
            aliases = (aliases + "\n" if aliases else "") + f"Имена изменены вами (по стандарту: «{was[1]} {was[0]}»)"
        self.std_aliases.configure(text=aliases)
        self._manual_file = self._manual_title = False
        if std.verified:
            self.std_verified.configure(text="✓ Таблица сверена с оригиналом стандарта", foreground=self.theme.palette.ok)
        else:
            self.std_verified.configure(text="Таблица не сверена с оригиналом стандарта (размеры из открытых источников)",
                                        foreground=self.theme.palette.muted)
        labels = std.size_labels
        self.size_box.configure(values=[size_display(x) for x in labels])
        old = self.size_var.get().replace(",", ".")
        pick = old if old in labels else ("M8" if "M8" in labels else labels[0])
        self.size_var.set(size_display(pick))
        classes = [NO_CLASS, *std.classes]
        self.class_box.configure(values=classes)
        self.class_var.set(NO_CLASS)
        for widget in (self.class_label, self.class_box):
            widget.grid() if std.classes else widget.grid_remove()
        for widget in (self.length_label, self.length_box):
            widget.grid() if std.has_length else widget.grid_remove()
        self._on_size_changed()

    def _current_size(self) -> str | None:
        text = self.size_var.get().replace(",", ".")
        return text if self.std and text in self.std.sizes else None

    def _params_changed(self) -> None:
        """Сменили длину или класс: имена снова считаются по стандарту (правка вручную относилась к прежней детали)."""
        self._manual_file = self._manual_title = False
        self._refresh_preview()

    def _on_size_changed(self) -> None:
        self._manual_file = self._manual_title = False
        std, size = self.std, self._current_size()
        if not std or not size:
            return
        if std.has_length:
            lengths = std.lengths_for(size)
            self.length_box.configure(values=[fmt_number(x) for x in lengths])
            keep = self.length_var.get()
            if keep not in [fmt_number(x) for x in lengths]:
                preferred = [x for x in lengths if x >= 3 * std.dims(size).get("d", 0)]
                self.length_var.set(fmt_number((preferred or lengths)[0]))
        self._refresh_preview()

    def _length(self) -> float | None:
        text = self.length_var.get().replace(",", ".")
        try:
            return float(text) if self.std and self.std.has_length and text else None
        except ValueError:
            return None

    def _strength(self) -> str | None:
        value = self.class_var.get()
        return None if value in ("", NO_CLASS) or not (self.std and self.std.classes) else value

    def _show_source(self) -> None:
        std = self.std
        if std is None:
            return
        text = f"{std.number}\n\nИсточник размеров:\n{std.source}"
        if std.notes:
            text += f"\n\nДопущения модели:\n{std.notes}"
        text += f"\n\nСверено с оригиналом: " + ("да" if std.verified else "нет")
        messagebox.showinfo("Источник и допущения", text, parent=self.root)

    # --- предпросмотр ---------------------------------------------------------------------------------------------
    def _refresh_preview(self) -> None:
        std, size = self.std, self._current_size()
        if not std or not size:
            return
        length = self._length()
        self._fill_dims(std, size, length)
        try:
            names = std.names(size, length, self._strength())
        except KeyError:
            return
        self._file_auto, self._title_auto = names.file_stem, names.title
        if not self._manual_file:
            self.file_var.set(names.file_stem)
        if not self._manual_title:
            self.title_var.set(names.title)
        self.section_var.set(std.section_name)
        self._update_file_note()
        self._schedule_redraw()

    def _update_file_note(self) -> None:
        """Подсказка справа от имени файла: расширение и состояние папки или файла."""
        folder = Path(self.folder_var.get().strip() or ".")
        stem = safe_filename(self.file_var.get().removesuffix(".m3d"))
        note = ".m3d"
        if not folder.is_dir():
            note += "   (папки нет)"
        elif stem and (folder / f"{stem}.m3d").exists():
            note += "   (уже есть: будет заменён)"
        self.file_note_var.set(note)

    def _on_name_edited(self) -> None:
        self._manual_file = self.file_var.get() != self._file_auto
        self._manual_title = self.title_var.get() != self._title_auto
        self._update_file_note()

    def _reset_names(self) -> None:
        self._manual_file = self._manual_title = False
        self._refresh_preview()

    def _fill_dims(self, std: Standard, size: str, length: float | None) -> None:
        """Расшифровка размеров под чертёжом: «буква = значение» и что это, в две колонки."""
        for child in self.legend_frame.winfo_children():
            child.destroy()
        rows = drawing.legend(std.shape, std.dims(size), length)
        per_col = (len(rows) + 1) // 2
        for i, (sym, meaning, value) in enumerate(rows):
            col, row = (0, i) if i < per_col else (2, i - per_col)
            ttk.Label(self.legend_frame, text=f"{sym} = {value}", style="Card.TLabel").grid(
                row=row, column=col, sticky="w", padx=(0, self.theme.pad_small))
            ttk.Label(self.legend_frame, text=meaning, style="Card.Small.Muted.TLabel").grid(
                row=row, column=col + 1, sticky="w", padx=(0, self.theme.pad))

    def _schedule_redraw(self) -> None:
        if self._redraw_job is not None:
            self.root.after_cancel(self._redraw_job)
        self._redraw_job = self.root.after(30, self._redraw)

    def _redraw(self) -> None:
        self._redraw_job = None
        std, size = self.std, self._current_size()
        if not std or not size or self._closing:
            return
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        if w < 50 or h < 50:
            return
        try:
            d = drawing.draw(std.shape, std.dims(size), self._length())
        except KeyError:
            self.canvas.delete("all")
            self.canvas.create_text(w / 2, h / 2, text="Для этой формы чертежа пока нет", fill=self.theme.palette.muted,
                                    font=self.theme.font_small)
            return
        drawing.render_tk(self.canvas, d, self.theme.palette, self.theme.font_small, w, h,
                          dpi_scale=max(1.0, self.theme.px(10) / 10))
        self.views_hint.configure(text="   ·   ".join(f"{name}: {where}" for name, where in d.caption))

    # --- действия -------------------------------------------------------------------------------------------------
    def _browse(self) -> None:
        start = self.folder_var.get() if Path(self.folder_var.get()).is_dir() else str(default_folder())
        chosen = filedialog.askdirectory(parent=self.root, initialdir=start, mustexist=False,
                                         title="Папка для сохранения детали")
        if chosen:
            self.folder_var.set(str(Path(chosen)))
            self._refresh_preview()

    def _request(self, overwrite: bool = False) -> Request:
        std, size = self.std, self._current_size()
        if std is None or size is None:
            raise BuildError("выберите стандарт и типоразмер")
        return Request(std, size, self._length(), Path(self.folder_var.get().strip()), self._strength(),
                       open_after=bool(self.open_var.get()), overwrite=overwrite,
                       file_stem=self.file_var.get() if self._manual_file else None,
                       title=self.title_var.get() if self._manual_title else None)

    def _create(self) -> None:
        if self._busy:
            return
        try:
            req = self._request()
            p = plan(req)
        except BuildError as e:
            self.log(f"Ошибка: {e}", tag="error")
            return
        if p.exists:
            if not messagebox.askyesno("Файл уже есть",
                                       f"Файл «{p.path.name}» уже существует.\n\nЗаменить его? Старый вариант сохранится "
                                       f"в истории изменений, замену можно будет отменить.", parent=self.root):
                return
            req = self._request(overwrite=True)
        s = self.ctx.settings
        s.set("folder", str(req.folder))
        s.set("open_after", req.open_after)

        def work(ctx) -> None:
            ctx.log(f"Создаю «{p.file_stem}»…")
            result = create_part(ctx, req)
            ctx.log(f"Готово: {result.path}", tag="ok")
            ctx.log(f"Объём {result.volume_mm3:.3f} мм³ совпал с расчётом {result.expected_mm3:.3f} мм³.", tag="muted")
            if result.opened:
                ctx.log("Деталь открыта в новой вкладке КОМПАС.", tag="muted")
            self.post("created", str(result.path))

        self.run_in_background(work, "Создание детали")

    def _on_created(self, path: str) -> None:
        self._refresh_preview()   # файл теперь существует: подсказка «будет заменён» актуальна

    def _edit_names(self) -> None:
        if self.std is not None:
            from .names import open_names_dialog
            open_names_dialog(self)

    def save_names(self, std_id: str, fields: dict[str, str] | None) -> None:
        """Запомнить свои имена стандарта (None: вернуть по умолчанию). Файл пишется через сессию отката."""
        from .catalog import serialize_name_overrides
        if self.names_file is None:
            self.log("Свои имена сохранить некуда: у мода нет папки данных.", tag="error")
            return
        overrides = {k: dict(v) for k, v in self.catalog.name_overrides.items()}
        if fields:
            overrides[std_id] = fields
        else:
            overrides.pop(std_id, None)
        text = serialize_name_overrides(overrides)
        with self.ctx.session("Свои имена в каталоге") as session:
            session.write_text(self.names_file, text)
        self.reload_catalog(quiet=True)
        self.log("Свои имена стандарта сохранены." if fields else "Имена стандарта возвращены по умолчанию.", tag="ok")

    def _custom(self) -> None:
        from .custom import open_custom_dialog
        open_custom_dialog(self)

    # --- свои детали (окно custom.py вызывает эти методы) -------------------------------------------------------------
    def open_user_folder(self) -> None:
        if self.user_dir is None:
            return
        self.user_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(str(self.user_dir))   # mkga: allow-unsafe-io (только показать папку в проводнике, файлы не меняются)

    def _open_path(self, path: str) -> None:
        try:
            os.startfile(path)             # mkga: allow-unsafe-io (открыть файл в программе по умолчанию, не меняя его)
        except OSError:
            self.open_user_folder()

    def create_template(self) -> None:
        """Заготовка своей детали на основе выбранного стандарта (новый файл в папке своих деталей, с откатом)."""
        from .custom import template_for
        if self.std is None or self.user_dir is None:
            return
        name, text = template_for(self.std)
        self.user_dir.mkdir(parents=True, exist_ok=True)
        stem, n = name[:-5], 2
        while (self.user_dir / name).exists():
            name = f"{stem}-{n}.json"
            n += 1
        target = self.user_dir / name

        def work(ctx) -> None:
            with ctx.session(f"Заготовка своей детали «{name}»") as session:
                session.write_text(target, text)
            ctx.log(f"Создана заготовка: {target}", tag="ok")
            ctx.log("Поправьте размеры и источник в файле, сохраните его и нажмите «Свои детали» → «Обновить каталог».",
                    tag="muted")
            self.post("open_path", str(target))

        self.run_in_background(work, "Создание заготовки")

    def copy_ai_prompt(self) -> None:
        from .custom import ai_prompt
        self.root.clipboard_clear()
        self.root.clipboard_append(ai_prompt(self.std))
        self.log("Инструкция для ИИ скопирована в буфер обмена: вставьте её в чат с ИИ.", tag="ok")

    def reload_catalog(self, quiet: bool = False) -> None:
        if self.builtin_dir is None:
            return
        self.catalog = load_catalog(self.builtin_dir, self.user_dir, self.names_file)
        for problem in self.catalog.problems:
            self.log(f"Каталог: {problem}", tag="error")
        self._fill_tree()
        keep = self.std.id if self.std and self.std.id in self.catalog.standards else None
        if keep or self.catalog.standards:
            self._select_standard(keep or next(iter(sorted(self.catalog.standards))))
        if not quiet:
            self.log(f"Каталог обновлён: стандартов {len(self.catalog.standards)}.", tag="ok")


def run_app(ctx, catalog: Catalog, *, version: str = "", user_dir: Path | None = None,
            builtin_dir: Path | None = None, names_file: Path | None = None) -> None:
    win = ComponentsWindow(ctx, catalog, version=version, user_dir=user_dir, builtin_dir=builtin_dir,
                           names_file=names_file)
    win.mainloop()
