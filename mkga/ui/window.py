"""Каркас окна мода: параметры, предпросмотр изменений, журнал, статус КОМПАСа, кнопки действий.

Каждый мод с окном строится на ModWindow, поэтому у всех модов одинаковые расположение, шрифты,
поведение и защита от ошибок:

    win = ModWindow(ctx, "Метизы", version="0.1.0")
    ttk.Label(win.params, text="Стандарт:", style="Card.TLabel").grid(...)   # свои элементы мода
    win.add_action("Предпросмотр", preview, icon="view")      # fn(ctx) выполняется в рабочем потоке
    win.add_action("Создать", create, primary=True, icon="play")
    win.mainloop()

В карточке «Параметры» используйте стили Card.* (Card.TLabel, Card.TEntry, Card.TCombobox,
Card.TCheckbutton, Card.TRadiobutton, Card.TButton): у них правильный фон.

Правила потоков и общая механика (журнал, статус, подтверждения): ui/base.py и docs/UI_STYLE.md.
"""

from __future__ import annotations

from pathlib import Path
from tkinter import ttk
from typing import Callable, Iterable

from ..core.safe_io import Change
from ..runner import ModContext
from .base import WindowBase
from .theme import LIGHT, Palette

_KIND_LABEL = {"create": "Создать", "modify": "Изменить", "delete": "Удалить (в корзину)"}


class ModWindow(WindowBase):
    def __init__(self, ctx: ModContext, title: str, *, version: str = "", size: tuple[int, int] = (1040, 700),
                 palette: Palette = LIGHT):
        super().__init__(ctx, f"{title}: MKGA (неофициальный)", size=size, min_size=(800, 540), palette=palette)
        self.register("changes", self._show_changes)
        self._build(title, version)

    # --- построение ---------------------------------------------------------------------
    def _build(self, title: str, version: str) -> None:
        t, root, p = self.theme, self.root, self.theme.palette
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        # Шапка: название и версия слева, статус КОМПАСа справа
        header = ttk.Frame(root, padding=(t.pad, t.pad, t.pad, t.pad_small))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text=title, style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text=f"Версия мода {version}" if version else "", style="Small.Muted.TLabel"
                  ).grid(row=1, column=0, sticky="w")
        pill, check = self.build_kompas_pill(header)
        pill.grid(row=0, column=1, rowspan=2, sticky="e", padx=(0, t.pad_small))
        check.grid(row=0, column=2, rowspan=2, sticky="e")

        body = ttk.Frame(root, padding=(t.pad, t.pad_small, t.pad, 0))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        # Слева: параметры мода
        left = t.card(body)
        left.grid(row=0, column=0, sticky="ns", padx=(0, t.pad))
        ttk.Label(left, text="Параметры", style="Card.Heading.TLabel").pack(anchor="w", pady=(0, t.pad_small))
        self.params = ttk.Frame(left, style="CardInner.TFrame", padding=0)
        self.params.pack(fill="both", expand=True)
        self.params.configure(width=t.px(280))

        # Справа: что будет сделано и журнал
        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=3)
        right.rowconfigure(1, weight=2)

        changes_card = t.card(right)
        changes_card.grid(row=0, column=0, sticky="nsew", pady=(0, t.pad))
        changes_card.columnconfigure(0, weight=1)
        changes_card.rowconfigure(1, weight=1)
        top = ttk.Frame(changes_card, style="CardInner.TFrame", padding=0)
        top.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, t.pad_small))
        top.columnconfigure(0, weight=1)
        ttk.Label(top, text="Что будет сделано с файлами", style="Card.Heading.TLabel").grid(row=0, column=0, sticky="w")
        self._changes_hint = ttk.Label(top, style="Card.Muted.TLabel", text="Нажмите «Предпросмотр», чтобы увидеть")
        self._changes_hint.grid(row=0, column=1, sticky="e")
        self.changes_tree = ttk.Treeview(changes_card, columns=("kind", "name", "folder"), show="headings",
                                         selectmode="browse")
        self.changes_tree.heading("kind", text="ДЕЙСТВИЕ", anchor="w")
        self.changes_tree.heading("name", text="ФАЙЛ", anchor="w")
        self.changes_tree.heading("folder", text="ПАПКА", anchor="w")
        self.changes_tree.column("kind", width=t.px(150), stretch=False)
        self.changes_tree.column("name", width=t.px(200), stretch=False)
        self.changes_tree.column("folder", width=t.px(300), stretch=True)
        self.changes_tree.tag_configure("create", foreground=p.ok)
        self.changes_tree.tag_configure("delete", foreground=p.error)
        self.changes_tree.grid(row=1, column=0, sticky="nsew")
        sb = ttk.Scrollbar(changes_card, orient="vertical", command=self.changes_tree.yview)
        sb.grid(row=1, column=1, sticky="ns")
        self.changes_tree.configure(yscrollcommand=sb.set)

        self.build_log_card(right).grid(row=1, column=0, sticky="nsew")
        self.build_footer(root).grid(row=2, column=0, sticky="ew")

    # --- публичный API для модов ---------------------------------------------------------
    def add_action(self, text: str, fn: Callable[..., object], *, primary: bool = False, icon: str | None = None,
                   params: Callable[[], object] | None = None) -> ttk.Button:
        """Кнопка действия; fn выполняется в рабочем потоке (widgets из неё не трогать).

        fn(ctx), либо fn(ctx, values), если задан params. params() вызывается в ГЛАВНОМ потоке в момент
        нажатия: именно там безопасно читать значения полей (tk.StringVar.get() и т.п.).
        icon: имя значка из mkga.ui.theme.ICONS ("view", "play", "undo", ...); без шрифта значков не показывается.
        """
        def on_click() -> None:
            if self._busy:
                return
            if params is None:
                self.run_in_background(fn, text)
            else:
                values = params()
                self.run_in_background(lambda ctx: fn(ctx, values), text)

        btn = ttk.Button(self._actions, text=self.label(text, icon),
                         style="Primary.TButton" if primary else "TButton", command=on_click)
        btn.pack(side="left", padx=(self.theme.pad_small, 0))
        self._buttons.append(btn)
        return btn

    def set_changes(self, changes: Iterable[Change]) -> None:
        """Показать список «что будет сделано с файлами» (обычно session.changes)."""
        self.post("changes", list(changes))

    # --- главный поток ------------------------------------------------------------------------
    def _show_changes(self, changes: list[Change]) -> None:
        self.changes_tree.delete(*self.changes_tree.get_children())
        for c in changes:
            path = Path(c.path)
            self.changes_tree.insert("", "end", tags=(c.kind,),
                                     values=(_KIND_LABEL.get(c.kind, c.kind), path.name, str(path.parent)))
        self._changes_hint.configure(text=f"Файлов: {len(changes)}" if changes else "Изменений файлов не будет")
