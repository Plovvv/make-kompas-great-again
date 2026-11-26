"""Окно хаба: каталог модов, установленные, история изменений файлов с откатом.

Хаб не выполняет код модов у себя: мод запускается отдельным процессом (mkga/launcher.py), поэтому сбой
мода не роняет хаб. Работа с сетью и диском идёт в рабочих потоках, окно не зависает.

Страницы (боковая навигация):
  * «Каталог»: моды из реестра на GitHub; установка и обновление одной кнопкой;
  * «Установленные»: то, что стоит на этом компьютере (в т.ч. мод, поставленный из файла);
  * «История изменений»: каждая запись это одна операция мода над файлами; кнопка «Отменить» возвращает
    файлы как были (mkga/core/safe_io.py).
"""

from __future__ import annotations

import gc
import os
import threading
import tkinter as tk
import urllib.error
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from .. import __version__
from ..bundled import BUNDLED_REPO, BundledMod, bundled_by_id, load_bundled, merge_entries
from ..core.safe_io import BackupStore
from ..core.settings import Settings
from ..core.versions import OK, REFUSE, check_version
from ..hub_model import (
    AVAILABLE, INSTALLED, LOCAL, UPDATE, HistoryRow, ModRow, build_rows, filter_rows, history_rows,
    missing_requirements,
)
from ..installer import InstallError, install_from_registry, install_zip, list_installed, uninstall
from ..launcher import start_mod
from ..manifest import ManifestError
from ..registry import RegistryEntry, RegistryError, load_registry
from ..runner import ModContext
from .base import WindowBase
from .theme import palette_by_name

THEME_CYCLE = ("system", "light", "dark")
THEME_LABEL = {"system": "как в Windows", "light": "светлая", "dark": "тёмная"}
_STATE_PILL = {AVAILABLE: "Card.PillMuted.TLabel", INSTALLED: "Card.PillOk.TLabel",
               UPDATE: "Card.PillAccent.TLabel", LOCAL: "Card.PillMuted.TLabel"}
_KIND_TEXT = {"app": "приложение с окном", "macro": "макрос (один запуск)", "library": "библиотека для других модов"}
_PAGES = (("catalog", "Каталог", None), ("installed", "Установленные", None), ("history", "История изменений", "undo"))


def describe_catalog_error(e: BaseException) -> str:
    """Понятное объяснение, почему не загрузился каталог."""
    if isinstance(e, urllib.error.HTTPError):
        return f"Сервер каталога ответил ошибкой {e.code}."
    if isinstance(e, (urllib.error.URLError, TimeoutError, ConnectionError)):
        return "Нет доступа к каталогу. Проверьте подключение к интернету."
    if isinstance(e, RegistryError):
        return f"Каталог повреждён: {e}"
    return f"{type(e).__name__}: {e}"


class HubWindow(WindowBase):
    def __init__(
        self,
        *,
        mods_dir: str | Path,
        registry: str,
        store: BackupStore | None = None,
        theme_name: str = "system",
        loader: Callable[[str], list[RegistryEntry]] = load_registry,
        launcher: Callable[..., object] = start_mod,
        installer: Callable[..., object] = install_from_registry,
        zip_installer: Callable[..., object] = install_zip,
        remover: Callable[..., bool] = uninstall,
        state: dict | None = None,
        bundled: list[BundledMod] | None = None,
    ):
        self.mods_dir = Path(mods_dir)
        self.registry = registry
        self.theme_name = theme_name
        self._loader, self._launcher = loader, launcher
        self._installer, self._zip_installer, self._remover = installer, zip_installer, remover
        self._bundled_problems: list[str] = []
        if bundled is None:
            bundled, self._bundled_problems = load_bundled()
        self._bundled = bundled_by_id(bundled)           # моды из поставки: ставятся без сети
        ctx = ModContext(mod_dir=self.mods_dir, data_dir=self.mods_dir.parent / "data" / "hub",
                         backups=store or BackupStore(), mod_id="hub")
        super().__init__(ctx, "MKGA: хаб модов (неофициальный)", size=(1240, 740), min_size=(1000, 600),
                         palette=palette_by_name(theme_name))
        state = state or {}
        self.restart_requested = False
        self.entries: list[RegistryEntry] = state.get("entries", [])
        self.catalog_error: str = state.get("catalog_error", "")
        self.catalog_loaded: bool = state.get("catalog_loaded", False)
        self.rows: list[ModRow] = []
        self.history: list[HistoryRow] = []
        self.kompas_version: tuple | None = None
        self._page = state.get("page", "catalog")
        self._selected: str | None = state.get("selected")

        for problem in self._bundled_problems:
            self.log(f"Поставка: {problem}", tag="error")
        self.register("catalog", self._on_catalog)
        self.register("mod_exit", self._on_mod_exit)
        self._build()
        self.search_var.set(state.get("query", ""))
        self.show_page(self._page)
        if not self.catalog_loaded:
            self.refresh_catalog()

    # =========================== построение ===========================================================
    def _build(self) -> None:
        t, root = self.theme, self.root
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)
        self._build_sidebar()

        content = ttk.Frame(root)
        content.grid(row=0, column=1, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)
        pages = ttk.Frame(content, padding=(0, t.pad, t.pad, 0))
        pages.grid(row=0, column=0, sticky="nsew")
        pages.columnconfigure(0, weight=1)
        pages.rowconfigure(0, weight=1)
        self._mods_page = self._build_mods_page(pages)
        self._history_page = self._build_history_page(pages)
        for page in (self._mods_page, self._history_page):
            page.grid(row=0, column=0, sticky="nsew")

        self.build_log_card(content, height=3).grid(row=1, column=0, sticky="ew", padx=(0, t.pad), pady=(t.pad, 0))
        self.build_footer(content).grid(row=2, column=0, sticky="ew")

    def _build_sidebar(self) -> None:
        t = self.theme
        side = ttk.Frame(self.root, padding=t.pad)
        side.grid(row=0, column=0, sticky="ns")
        side.columnconfigure(0, minsize=t.px(250))
        side.rowconfigure(10, weight=1)
        ttk.Label(side, text="MKGA", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(side, text="Make KOMPAS Great Again", style="Small.Muted.TLabel").grid(row=1, column=0, sticky="w")
        ttk.Label(side, text="Неофициальный проект", style="Small.Muted.TLabel").grid(
            row=2, column=0, sticky="w", pady=(0, t.pad))
        self._nav: dict[str, ttk.Button] = {}
        for i, (key, text, icon) in enumerate(_PAGES):
            button = ttk.Button(side, text=self.label(text, icon), style="Nav.TButton",
                                command=lambda k=key: self.show_page(k))
            button.grid(row=3 + i, column=0, sticky="ew", pady=2)
            self._nav[key] = button
        pill, check = self.build_kompas_pill(side)
        pill.configure(anchor="center", wraplength=t.px(220))
        pill.grid(row=11, column=0, sticky="ew", pady=(0, t.pad_small))
        check.grid(row=12, column=0, sticky="ew")
        ttk.Button(side, text="Пункты в меню КОМПАС…", style="Ghost.TButton", command=self._kompas_menu).grid(
            row=13, column=0, sticky="ew", pady=(t.pad_small, 0))
        self._theme_btn = ttk.Button(side, text=f"Тема: {THEME_LABEL[self.theme_name]}", style="Ghost.TButton",
                                     command=self._cycle_theme)
        self._theme_btn.grid(row=14, column=0, sticky="ew", pady=(t.pad_small, 0))
        ttk.Label(side, text=f"Версия MKGA {__version__}", style="Small.Muted.TLabel").grid(
            row=15, column=0, sticky="w", pady=(t.pad_small, 0))

    def _build_mods_page(self, parent: tk.Misc) -> ttk.Frame:
        t, p = self.theme, self.theme.palette
        page = ttk.Frame(parent)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)

        head = ttk.Frame(page)
        head.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, t.pad))
        head.columnconfigure(1, weight=1)
        self._title = ttk.Label(head, text="Каталог", style="Title.TLabel")
        self._title.grid(row=0, column=0, sticky="w")
        self.search_var = tk.StringVar()
        ttk.Label(head, text=self.label("Поиск", "search"), style="Muted.TLabel").grid(
            row=0, column=2, sticky="e", padx=(0, t.pad_small))
        self.search_entry = ttk.Entry(head, textvariable=self.search_var, width=22)
        self.search_entry.grid(row=0, column=3, sticky="e", padx=(0, t.pad_small))
        self.search_entry.bind("<KeyRelease>", lambda _e: self._render_list())
        self._file_btn = ttk.Button(head, text=self.label("Из файла…", "add"), command=self._install_from_file)
        self._file_btn.grid(row=0, column=4, padx=(0, t.pad_small))
        self._folder_btn = ttk.Button(head, text="Папка модов", style="Ghost.TButton", command=self._open_mods_dir)
        self._folder_btn.grid(row=0, column=5)
        self._buttons += [self._file_btn, self._folder_btn]

        # список
        list_card = t.card(page)
        list_card.grid(row=1, column=0, sticky="nsew", padx=(0, t.pad))
        list_card.columnconfigure(0, weight=1)
        list_card.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(list_card, columns=("name", "version", "state"), show="headings", selectmode="browse")
        for col, title, width, stretch in (("name", "МОД", 200, True), ("version", "ВЕРСИЯ", 80, False),
                                           ("state", "СОСТОЯНИЕ", 160, False)):
            self.tree.heading(col, text=title, anchor="w")
            self.tree.column(col, width=t.px(width), stretch=stretch)
        self.tree.tag_configure(UPDATE, foreground=p.accent)
        self.tree.tag_configure(LOCAL, foreground=p.muted)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(list_card, orient="vertical", command=self.tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._on_select())

        # состояние «пусто»: показывается вместо списка
        self.empty = ttk.Frame(list_card, style="CardInner.TFrame")
        self.empty.columnconfigure(0, weight=1)
        self.empty_title = ttk.Label(self.empty, style="Card.Heading.TLabel", anchor="center", justify="center")
        self.empty_title.grid(row=0, column=0, pady=(t.px(70), t.pad_small))
        self.empty_text = ttk.Label(self.empty, style="Card.Muted.TLabel", anchor="center", justify="center",
                                    wraplength=t.px(420))
        self.empty_text.grid(row=1, column=0)
        self.empty_btn = ttk.Button(self.empty, text=self.label("Повторить", "refresh"), style="Card.TButton",
                                    command=self.refresh_catalog)
        self.empty_btn.grid(row=2, column=0, pady=(t.pad, 0))
        self.empty.grid(row=0, column=0, columnspan=2, sticky="nsew")

        # карточка выбранного мода
        details_card = t.card(page)
        details_card.grid(row=1, column=1, sticky="ns")
        self._build_details(details_card)
        return page

    def _build_details(self, card: ttk.Frame) -> None:
        t = self.theme
        width = t.px(310)
        self.d_placeholder = ttk.Label(card, text="Выберите мод слева, чтобы увидеть подробности",
                                       style="Card.Muted.TLabel", wraplength=width, justify="left")
        self.d_placeholder.grid(row=0, column=0, sticky="nw")
        box = ttk.Frame(card, style="CardInner.TFrame", width=width)
        self.d_box = box
        box.grid(row=0, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        self.d_name = ttk.Label(box, style="Card.Heading.TLabel", wraplength=width, justify="left")
        self.d_name.grid(row=0, column=0, sticky="w")
        self.d_state = ttk.Label(box, style="Card.PillMuted.TLabel")
        self.d_state.grid(row=1, column=0, sticky="w", pady=(t.pad_small, t.pad_small))
        self.d_desc = ttk.Label(box, style="Card.TLabel", wraplength=width, justify="left")
        self.d_desc.grid(row=2, column=0, sticky="w", pady=(0, t.pad_small))
        meta = ttk.Frame(box, style="CardInner.TFrame")
        meta.grid(row=3, column=0, sticky="ew")
        meta.columnconfigure(1, weight=1)
        self.d_meta: dict[str, ttk.Label] = {}
        for i, (key, title) in enumerate((("version", "Версия"), ("author", "Автор"), ("license", "Лицензия"),
                                          ("kind", "Тип"), ("kompas", "Проверен на"), ("tags", "Теги"))):
            ttk.Label(meta, text=title, style="Card.Muted.TLabel").grid(row=i, column=0, sticky="nw", pady=1)
            value = ttk.Label(meta, style="Card.TLabel", wraplength=t.px(200), justify="left")
            value.grid(row=i, column=1, sticky="w", padx=(t.pad, 0), pady=1)
            self.d_meta[key] = value
        self.d_compat = ttk.Label(box, style="Card.Muted.TLabel", wraplength=width, justify="left")
        self.d_compat.grid(row=4, column=0, sticky="w", pady=(t.pad_small, 0))
        actions = ttk.Frame(box, style="CardInner.TFrame")
        actions.grid(row=5, column=0, sticky="ew", pady=(t.pad_small, 0))
        self.install_btn = ttk.Button(actions, text="Установить", style="Card.Primary.TButton",
                                      command=self._install_selected)
        self.run_btn = ttk.Button(actions, text=self.label("Запустить", "play"), style="Card.TButton",
                                  command=self._run_selected)
        self.remove_btn = ttk.Button(actions, text="Удалить", style="Card.Ghost.TButton", command=self._uninstall_selected)
        self.install_btn.pack(side="left")
        self.run_btn.pack(side="left", padx=(t.pad_small, 0))
        self.remove_btn.pack(side="left", padx=(t.pad_small, 0))
        ttk.Label(box, style="Card.Small.Muted.TLabel", wraplength=width, justify="left",
                  text="Моды выполняют код на вашем компьютере: ставьте только проверенные.").grid(
            row=6, column=0, sticky="w", pady=(t.pad_small, 0))

    def _build_history_page(self, parent: tk.Misc) -> ttk.Frame:
        t = self.theme
        page = ttk.Frame(parent)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        head = ttk.Frame(page)
        head.grid(row=0, column=0, sticky="ew", pady=(0, t.pad))
        head.columnconfigure(0, weight=1)
        ttk.Label(head, text="История изменений", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(head, text="Каждая запись это одна операция мода над вашими файлами. «Отменить» возвращает файлы, "
                             "как они были до неё.", style="Small.Muted.TLabel").grid(row=1, column=0, sticky="w")
        card = t.card(page)
        card.grid(row=1, column=0, sticky="nsew")
        card.columnconfigure(0, weight=1)
        card.rowconfigure(0, weight=1)
        self.history_tree = ttk.Treeview(card, columns=("when", "mod", "title", "status", "files"), show="headings",
                                         selectmode="browse")
        for col, title, width, stretch in (("when", "КОГДА", 150, False), ("mod", "МОД", 140, False),
                                           ("title", "ОПЕРАЦИЯ", 280, True), ("status", "СОСТОЯНИЕ", 170, False),
                                           ("files", "ФАЙЛОВ", 80, False)):
            self.history_tree.heading(col, text=title, anchor="w")
            self.history_tree.column(col, width=t.px(width), stretch=stretch)
        self.history_tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(card, orient="vertical", command=self.history_tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.history_tree.configure(yscrollcommand=sb.set)
        self.history_tree.bind("<<TreeviewSelect>>", lambda _e: self._update_history_buttons())
        self.history_empty = ttk.Label(card, text="Моды пока ничего не меняли в ваших файлах.", style="Card.Muted.TLabel")
        self.history_empty.grid(row=0, column=0, columnspan=2)
        bar = ttk.Frame(page, padding=(0, t.pad, 0, 0))
        bar.grid(row=2, column=0, sticky="ew")
        self.undo_btn = ttk.Button(bar, text=self.label("Отменить выбранное", "undo"), style="Primary.TButton",
                                   command=self._undo_selected)
        self.undo_btn.pack(side="left")
        refresh = ttk.Button(bar, text=self.label("Обновить", "refresh"), style="Ghost.TButton",
                             command=self.refresh_history)
        refresh.pack(side="left", padx=(t.pad_small, 0))
        return page

    # =========================== страницы и данные ====================================================
    def show_page(self, key: str) -> None:
        self._page = key
        for k, button in self._nav.items():
            button.configure(style="NavActive.TButton" if k == key else "Nav.TButton")
        if key == "history":
            self._history_page.tkraise()
            self.refresh_history()
            return
        self._title.configure(text="Каталог" if key == "catalog" else "Установленные")
        for b in (self._file_btn, self._folder_btn):
            b.grid() if key == "catalog" else b.grid_remove()
        self._mods_page.tkraise()
        self.refresh_rows()

    def refresh_rows(self) -> None:
        self.rows = build_rows(merge_entries(self.entries, list(self._bundled.values())), list_installed(self.mods_dir))
        self._render_list()

    def _visible_rows(self) -> list[ModRow]:
        return filter_rows(self.rows, self.search_var.get(), only_installed=self._page == "installed")

    def _render_list(self) -> None:
        rows = self._visible_rows()
        self.tree.delete(*self.tree.get_children())
        for r in rows:
            self.tree.insert("", "end", iid=r.id, tags=(r.state,), values=(r.name, r.version_text, r.state_label))
        if self._selected in {r.id for r in rows}:
            self.tree.selection_set(self._selected)
        else:
            self._selected = None
        title, text, retry = self._empty_state(rows)
        if rows:
            self.empty.grid_remove()
        else:
            self.empty_title.configure(text=title)
            self.empty_text.configure(text=text)
            self.empty_btn.grid() if retry else self.empty_btn.grid_remove()
            self.empty.grid()
            self.empty.tkraise()
        self._show_details()

    def _empty_state(self, rows: list[ModRow]) -> tuple[str, str, bool]:
        if rows:
            return "", "", False
        if self.search_var.get().strip():
            return "Ничего не найдено", "Попробуйте изменить запрос.", False
        if self._page == "installed":
            return ("Установленных модов пока нет",
                    "Откройте «Каталог» или установите мод из файла.", False)
        if self.catalog_error:
            return "Не удалось загрузить каталог", self.catalog_error, True
        if not self.catalog_loaded:
            return "Загрузка каталога…", "Подождите несколько секунд.", False
        return ("В каталоге пока нет модов",
                "Каталог читается из репозитория проекта на GitHub. Свой мод можно установить из файла "
                "(кнопка «Из файла…» выше).", False)

    def _current_row(self) -> ModRow | None:
        return next((r for r in self.rows if r.id == self._selected), None)

    def _on_select(self) -> None:
        sel = self.tree.selection()
        self._selected = sel[0] if sel else None
        self._show_details()

    def _show_details(self) -> None:
        row = self._current_row()
        if row is None:
            self.d_box.grid_remove()
            self.d_placeholder.grid()
            return
        self.d_placeholder.grid_remove()
        self.d_box.grid()
        m = row.manifest
        self.d_name.configure(text=row.name)
        self.d_state.configure(text=row.state_label if row.state != UPDATE
                               else f"Есть обновление: {row.latest_tag}", style=_STATE_PILL[row.state])
        self.d_desc.configure(text=row.description)
        self.d_meta["version"].configure(text=row.installed_version or (row.latest_tag or "—").lstrip("vV"))
        self.d_meta["author"].configure(text=m.author if m else "—")
        self.d_meta["license"].configure(text=m.license if m else "—")
        self.d_meta["kind"].configure(text=_KIND_TEXT.get(m.kind, m.kind) if m else "—")
        self.d_meta["kompas"].configure(
            text=", ".join(f"v{v}" for v in m.kompas_versions) if m and m.kompas_versions else "не указано")
        self.d_meta["tags"].configure(text=", ".join(row.tags) or "—")
        self.d_compat.configure(text=self._compat_text(row))
        busy = self._busy > 0
        self.install_btn.configure(text="Обновить" if row.state == UPDATE else "Установить")
        self._set_enabled(self.install_btn, row.can_install and not busy)
        self._set_enabled(self.run_btn, row.is_installed and not busy)
        self._set_enabled(self.remove_btn, row.is_installed and not busy)
        if row.can_install:
            self.install_btn.pack(side="left", before=self.run_btn)
        else:
            self.install_btn.pack_forget()

    @staticmethod
    def _set_enabled(button: ttk.Button, enabled: bool) -> None:
        button.state(["!disabled"] if enabled else ["disabled"])

    def _compat_text(self, row: ModRow) -> str:
        if row.manifest is None:
            return "Совместимость с вашим КОМПАСом станет известна после установки."
        if self.kompas_version is None:
            return "Нажмите «Проверить» слева, чтобы узнать, подходит ли мод вашему КОМПАСу." + self._requires_note(row)
        verdict = check_version(self.kompas_version, row.manifest.kompas_versions)
        prefix = {OK: "✓ ", REFUSE: "✗ "}.get(verdict.level, "! ")
        return prefix + verdict.message + self._requires_note(row)

    @staticmethod
    def _requires_note(row: ModRow) -> str:
        missing = missing_requirements(row.manifest) if row.manifest else []
        if not missing:
            return ""
        return ("\n✗ Мод требует пакеты, которых нет в собранной версии: " + ", ".join(missing)
                + ". Запуск из исходников возможен, если поставить их самому.")

    def on_kompas(self, version: tuple | None) -> None:
        self.kompas_version = version
        self._show_details()

    def on_busy_changed(self, busy: bool) -> None:
        self._show_details()
        self._update_history_buttons()
        if not busy:  # после любого действия (установка, откат) обновляем списки
            self.refresh_rows()
            if self._page == "history":
                self.refresh_history()

    # =========================== каталог ==============================================================
    def refresh_catalog(self) -> None:
        """Загрузить каталог в фоне (без блокировки окна и без «занятости»)."""
        self.set_status("Загрузка каталога…")
        if self.catalog_error or not self.catalog_loaded:
            self.catalog_error = ""
            self._render_list()

        def work() -> None:
            try:
                self.post("catalog", self._loader(self.registry), "")
            except Exception as e:  # noqa: BLE001  любая сетевая/файловая ошибка показывается в окне
                self.post("catalog", None, describe_catalog_error(e))

        threading.Thread(target=work, daemon=True).start()

    def _on_catalog(self, entries: list[RegistryEntry] | None, error: str) -> None:
        self.catalog_loaded = True
        if entries is not None:
            self.entries, self.catalog_error = entries, ""
            self.set_status(f"Каталог загружен: модов {len(entries)}")
        else:
            self.catalog_error = error
            self.log(error, tag="error")
            self.set_status("Каталог недоступен")
        self.refresh_rows()

    # =========================== действия над модами ==================================================
    def _friendly(self, fn: Callable[[ModContext], None]) -> Callable[[ModContext], None]:
        def run(ctx: ModContext) -> None:
            try:
                fn(ctx)
            except (InstallError, ManifestError, RegistryError, OSError) as e:
                ctx.log(f"Ошибка: {describe_catalog_error(e) if isinstance(e, urllib.error.URLError) else e}", tag="error")
        return run

    def _install_selected(self) -> None:
        row = self._current_row()
        if row is None or not row.can_install or self._busy:
            return
        entry = row.entry
        bundle = self._bundled.get(entry.id) if entry.repo == BUNDLED_REPO else None

        def work(ctx: ModContext) -> None:
            if bundle is not None:
                ctx.log(f"Ставлю «{entry.name}» {entry.tag} из поставки (без сети) и проверяю хеш…", tag="muted")
                manifest = self._zip_installer(bundle.path, self.mods_dir, expected_id=entry.id, expected_sha256=entry.sha256)
            else:
                ctx.log(f"Скачиваю «{entry.name}» {entry.tag} и проверяю хеш…", tag="muted")
                manifest = self._installer(entry, self.mods_dir)
            ctx.log(f"Установлено: {manifest.name} {manifest.version}", tag="ok")

        self.run_in_background(self._friendly(work), "Установка")

    def _install_from_file(self) -> None:
        if self._busy:
            return
        path = filedialog.askopenfilename(parent=self.root, title="Выберите архив мода",
                                          filetypes=[("Архив мода (*.zip)", "*.zip")])
        if not path:
            return
        if not messagebox.askyesno(
                "Установка не из каталога",
                "Мод выполняет код на вашем компьютере, а этот архив не проверялся каталогом.\n"
                "Устанавливайте только то, чему доверяете.\n\nУстановить?", parent=self.root):
            return

        def work(ctx: ModContext) -> None:
            manifest = self._zip_installer(path, self.mods_dir)
            ctx.log(f"Установлено из файла: {manifest.name} {manifest.version}", tag="ok")

        self.run_in_background(self._friendly(work), "Установка из файла")

    def _uninstall_selected(self) -> None:
        row = self._current_row()
        if row is None or not row.is_installed or self._busy:
            return
        if not messagebox.askyesno("Удаление мода", f"Удалить мод «{row.name}»?\n\nНастройки мода сохранятся, "
                                   "его можно будет установить снова.", parent=self.root):
            return

        def work(ctx: ModContext) -> None:
            removed = self._remover(row.id, self.mods_dir)
            ctx.log(f"Удалено: {row.name}" if removed else f"Мод {row.name} не найден", tag="ok" if removed else "muted")

        self.run_in_background(self._friendly(work), "Удаление")

    def _run_selected(self) -> None:
        row = self._current_row()
        if row is None or not row.is_installed or self._busy:
            return
        mod_id = row.id
        missing = missing_requirements(row.manifest)
        if missing:
            self.log(f"Мод «{row.name}» не запущен: ему нужны пакеты, которых нет в собранной версии "
                     f"({', '.join(missing)}).", tag="error")
            return
        self.log(f"Запускаю «{row.name}» отдельным процессом…", tag="muted")
        try:
            self._launcher(self.mods_dir, mod_id,
                           on_line=lambda line: self.log(f"[{mod_id}] {line}"),
                           on_exit=lambda code: self.post("mod_exit", mod_id, code))
        except OSError as e:
            self.log(f"Не удалось запустить мод: {e}", tag="error")

    def _on_mod_exit(self, mod_id: str, code: int) -> None:
        if code == 0:
            self.log(f"[{mod_id}] завершён", tag="muted")
        else:
            self.log(f"[{mod_id}] завершился с ошибкой (код {code}). Хаб и другие моды не затронуты.", tag="error")

    def _open_mods_dir(self) -> None:
        self.mods_dir.mkdir(parents=True, exist_ok=True)
        if hasattr(os, "startfile"):
            os.startfile(self.mods_dir)  # noqa: S606  (папка модов самого MKGA)
        else:
            self.log(f"Папка модов: {self.mods_dir}", tag="muted")

    # =========================== история и откат ======================================================
    def refresh_history(self) -> None:
        self.history = history_rows(self.ctx.backups)
        self.history_tree.delete(*self.history_tree.get_children())
        for h in self.history:
            self.history_tree.insert("", "end", iid=h.id, values=(h.when, h.mod_id, h.title, h.status_label, h.files))
        if self.history:
            self.history_empty.grid_remove()
        else:
            self.history_empty.grid()
        self._update_history_buttons()

    def _selected_history(self) -> HistoryRow | None:
        sel = self.history_tree.selection()
        return next((h for h in self.history if sel and h.id == sel[0]), None)

    def _update_history_buttons(self) -> None:
        row = self._selected_history()
        self._set_enabled(self.undo_btn, bool(row and row.can_undo) and not self._busy)

    def _undo_selected(self) -> None:
        row = self._selected_history()
        if row is None or not row.can_undo or self._busy:
            return
        if not messagebox.askyesno("Отмена операции", f"Вернуть файлы к состоянию до операции «{row.title}»?",
                                   parent=self.root):
            return

        def work(ctx: ModContext) -> None:
            store = ctx.backups
            report = store.undo(row.id)
            if not report.ok:
                names = ", ".join(Path(p).name for p in report.conflicts)
                if not self.ask(f"Эти файлы изменены после операции: {names}.\nЕсли откатить, ваши правки "
                                "в них будут потеряны.", question="Откатить всё равно?"):
                    ctx.log("Откат отменён: файлы остались как есть.", tag="muted")
                    return
                report = store.undo(row.id, force=True)
            ctx.log(f"Откат выполнен, возвращено файлов: {len(report.restored)}", tag="ok")

        self.run_in_background(self._friendly(work), "Откат")

    # =========================== меню КОМПАС ==========================================================
    def _kompas_menu(self) -> None:
        """Добавить или убрать пункты MKGA в меню КОМПАС («Приложения → Утилиты»). Работает только при закрытом КОМПАС."""
        from .. import kompas_menu as km
        entries: list = []
        try:
            state = km.status()
            if not state:
                self.log("Файл настроек КОМПАС не найден: пункты меню добавить нельзя.", tag="error")
                return
            present = sum(state.values())
            text = ("Пункты MKGA в меню КОМПАС (Приложения → Утилиты) позволят открыть хаб и моды прямо из КОМПАС.\n"
                    "Для этого меняется файл настроек КОМПАС: КОМПАС должен быть закрыт, изменение можно откатить "
                    "(страница «История изменений»).\n\n"
                    + (f"Сейчас пунктов MKGA: {present}.\n\n" if present else "")
                    + "Да: добавить или обновить пункты.\nНет: убрать пункты MKGA.\nОтмена: ничего не менять.")
            answer = messagebox.askyesnocancel("Пункты в меню КОМПАС", text, parent=self.root)
            if answer is None:
                return
            if answer:
                exe = km.find_exe()
                if exe is None:
                    self.log("Не нашёл MKGA.exe для пунктов меню (нужна собранная версия: python tools/build_exe.py).",
                             tag="error")
                    return
                entries = km.installed_entries(exe, self.mods_dir)
            reports = km.apply(entries, store=self.ctx.backups)
        except (km.MenuError, OSError) as e:
            self.log(f"Меню КОМПАС не изменено: {e}", tag="error")
            return
        for r in reports:
            self.log(f"КОМПАС {r.version}: пунктов MKGA было {r.before}, стало {r.after}" if r.changed
                     else f"КОМПАС {r.version}: без изменений", tag="ok" if r.changed else "muted")
        if entries and any(r.changed for r in reports):
            self.log("Откройте КОМПАС: пункты появятся в меню «Приложения → Утилиты».", tag="muted")
        self.refresh_history()

    # =========================== тема =================================================================
    def _cycle_theme(self) -> None:
        nxt = THEME_CYCLE[(THEME_CYCLE.index(self.theme_name) + 1) % len(THEME_CYCLE)]
        self.ctx.settings.set("theme", nxt)
        self.theme_name = nxt
        self.restart_requested = True
        self.close()

    def export_state(self) -> dict:
        """Что сохранить при пересоздании окна (смена темы): страница, поиск, выбор, загруженный каталог."""
        return {"page": self._page, "query": self.search_var.get() if self.search_var else "",
                "selected": self._selected, "entries": self.entries, "catalog_error": self.catalog_error,
                "catalog_loaded": self.catalog_loaded}


def run_hub(registry: str, mods_dir: str | Path, store: BackupStore | None = None) -> None:
    """Открыть окно хаба. При смене темы окно пересоздаётся (страница и поиск сохраняются)."""
    mods_dir = Path(mods_dir)
    settings_path = mods_dir.parent / "data" / "hub" / "settings.json"
    state: dict | None = None
    while True:
        theme_name = Settings(settings_path).get("theme", "system")
        win = HubWindow(mods_dir=mods_dir, registry=registry, store=store, theme_name=theme_name, state=state)
        win.mainloop()
        if not win.restart_requested:
            break
        state = win.export_state()
        del win
        gc.collect()  # здесь, в главном потоке: объекты Tk старого окна удаляются безопасно
