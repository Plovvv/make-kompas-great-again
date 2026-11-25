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

Правила: действия выполняются в РАБОЧЕМ потоке (окно не зависает), с подготовкой COM (com_thread) и
собственным подключением к КОМПАСу. Из рабочего потока НЕ трогайте виджеты: пишите в ctx.log или
вызывайте win.set_changes() и win.set_status(): они безопасны. Ошибка действия показывается в журнале и
не закрывает окно.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable, Iterable

from ..core.kompas import KompasError, com_thread
from ..core.safe_io import Change, SafeIOError
from ..runner import ModContext
from .theme import ICONS, LIGHT, Palette, apply_theme, enable_dpi_awareness

_KIND_LABEL = {"create": "Создать", "modify": "Изменить", "delete": "Удалить (в корзину)"}
_PILL = {"ok": "PillOk.TLabel", "error": "PillError.TLabel", "muted": "PillMuted.TLabel"}


class ModWindow:
    def __init__(self, ctx: ModContext, title: str, *, version: str = "", size: tuple[int, int] = (1040, 700),
                 palette: Palette = LIGHT):
        enable_dpi_awareness()
        self.ctx = ctx
        self.root = tk.Tk()
        self.theme = apply_theme(self.root, palette)
        t = self.theme
        self.root.title(f"{title}: MKGA (неофициальный)")
        # Размер задаётся «как при 96 DPI», но не больше 90% экрана (маленькие и сильно масштабированные экраны).
        width = min(t.px(size[0]), int(self.root.winfo_screenwidth() * 0.9))
        height = min(t.px(size[1]), int(self.root.winfo_screenheight() * 0.9))
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(min(t.px(800), width), min(t.px(540), height))

        self._queue: "queue.Queue[tuple]" = queue.Queue()
        self._busy = 0
        self._buttons: list[ttk.Button] = []
        self._closing = False

        # Всё, что мод пишет в ctx.log, попадает в журнал окна (потокобезопасно).
        ctx.log = self.log
        # Вопросы о версии КОМПАСа из рабочего потока задаются диалогом в главном потоке
        # (консольный вопрос из CLI в оконном режиме не подходит).
        ctx.confirm = self._confirm_from_worker

        self._build(title, version)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(40, self._pump)

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
        self._kompas_var = tk.StringVar(value="КОМПАС не проверялся")
        self._kompas_label = ttk.Label(header, textvariable=self._kompas_var, style=_PILL["muted"])
        self._kompas_label.grid(row=0, column=1, rowspan=2, sticky="e", padx=(0, t.pad_small))
        self._check_btn = ttk.Button(header, text=self._label("Проверить", "refresh"), style="Ghost.TButton",
                                     command=self.check_kompas)
        self._check_btn.grid(row=0, column=2, rowspan=2, sticky="e")
        self._buttons.append(self._check_btn)

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

        log_card = ttk.Frame(right, style="Log.TFrame", padding=t.pad_small)
        log_card.grid(row=1, column=0, sticky="nsew")
        log_card.columnconfigure(0, weight=1)
        log_card.rowconfigure(1, weight=1)
        ttk.Label(log_card, text="  ЖУРНАЛ", style="Log.Muted.TLabel").grid(row=0, column=0, sticky="w", padx=t.pad_small,
                                                                         pady=(t.pad_small // 2, 0))
        self.log_text = tk.Text(log_card, height=6, wrap="word", state="disabled", font=t.font_mono, relief="flat",
                                borderwidth=0, background=p.log_bg, foreground=p.log_text,
                                insertbackground=p.log_text, selectbackground=p.accent, highlightthickness=0,
                                padx=t.px(10), pady=t.px(6))
        self.log_text.grid(row=1, column=0, sticky="nsew")
        lsb = ttk.Scrollbar(log_card, orient="vertical", command=self.log_text.yview)
        lsb.grid(row=1, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=lsb.set)
        self.log_text.tag_configure("error", foreground=p.log_error)
        self.log_text.tag_configure("ok", foreground=p.log_ok)
        self.log_text.tag_configure("muted", foreground=p.log_muted)

        # Низ: статус слева, прогресс и кнопки справа
        footer = ttk.Frame(root, padding=t.pad)
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self._status_var = tk.StringVar(value="Готово")
        ttk.Label(footer, textvariable=self._status_var, style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self._progress = ttk.Progressbar(footer, mode="indeterminate", length=t.px(140))
        self._progress.grid(row=0, column=1, padx=t.pad)
        self._progress.grid_remove()  # показывается только пока выполняется действие
        self._actions = ttk.Frame(footer)
        self._actions.grid(row=0, column=2, sticky="e")

    def _label(self, text: str, icon: str | None) -> str:
        glyph = self.theme.icon(ICONS[icon]) if icon else ""
        return f"{glyph}  {text}" if glyph else text

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

        btn = ttk.Button(self._actions, text=self._label(text, icon),
                         style="Primary.TButton" if primary else "TButton", command=on_click)
        btn.pack(side="left", padx=(self.theme.pad_small, 0))
        self._buttons.append(btn)
        return btn

    def run_in_background(self, fn: Callable[[ModContext], object], title: str = "") -> None:
        """Выполнить fn(ctx) в рабочем потоке: COM подготовлен, окно не зависает, ошибки в журнале."""
        if self._busy:
            return
        self._set_busy(True)
        self.set_status(f"{title}…" if title else "Выполняется…")

        def work() -> None:
            ok = False
            with com_thread():
                try:
                    fn(self.ctx)
                    ok = True
                except (KompasError, SafeIOError) as e:
                    self.log(f"Ошибка: {e}", tag="error")
                except Exception as e:  # ошибка мода не должна ронять окно
                    self.log(traceback.format_exc(), tag="error")
                    self.log(f"Действие завершилось с ошибкой: {type(e).__name__}: {e}", tag="error")
                finally:
                    # COM-объекты принадлежат этому потоку: отпускаем их здесь, до CoUninitialize.
                    # gc.collect() вызывать НЕЛЬЗЯ: он удалил бы объекты Tk из чужого потока (сбой Tcl).
                    self.ctx.reset_kompas()
            self._queue.put(("done", ok, title))

        threading.Thread(target=work, daemon=True).start()

    def check_kompas(self) -> None:
        """Проверить подключение к КОМПАСу и показать версию и редакцию в шапке окна."""
        def probe(ctx: ModContext) -> None:
            k = ctx.kompas()
            edition = "учебная" if k.is_study else "домашняя" if k.is_home else "полная"
            doc = k.active_document
            self._queue.put(("kompas", f"●  КОМПАС-3D v{'.'.join(map(str, k.version))} ({edition})", "ok"))
            ctx.log(f"Активный документ: {doc.Name}" if doc else "Активного документа нет", tag="muted")

        def failed_probe(ctx: ModContext) -> None:
            try:
                probe(ctx)
            except Exception:
                self._queue.put(("kompas", "●  КОМПАС не подключён", "error"))
                raise

        self.run_in_background(failed_probe, "Проверка КОМПАСа")

    def log(self, text: str, tag: str = "") -> None:
        """Строка в журнал. Можно вызывать из любого потока."""
        self._queue.put(("log", text, tag))

    def set_status(self, text: str) -> None:
        self._queue.put(("status", text))

    def set_changes(self, changes: Iterable[Change]) -> None:
        """Показать список «что будет сделано с файлами» (обычно session.changes)."""
        self._queue.put(("changes", list(changes)))

    def mainloop(self) -> None:
        self.root.mainloop()

    def wait_idle(self, timeout: float = 5.0) -> None:
        """Обработать события, пока действия не закончатся (для тестов и демо-скриптов)."""
        import time
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.root.update()
            if not self._busy and self._queue.empty():
                return
            time.sleep(0.01)
        raise TimeoutError("окно не успокоилось за отведённое время")

    # --- внутреннее: всё ниже выполняется в главном потоке -----------------------------------
    def _confirm_from_worker(self, message: str) -> bool:
        """Вопрос пользователю из рабочего потока (например, о непроверенной версии КОМПАСа)."""
        event, box = threading.Event(), {}
        self._queue.put(("ask", message, event, box))
        event.wait()
        return bool(box.get("yes"))

    def _set_busy(self, busy: bool) -> None:
        self._busy += 1 if busy else -1
        active = self._busy > 0
        for b in self._buttons:
            b.state(["disabled"] if active else ["!disabled"])
        if active:
            self._progress.grid()
            self._progress.start(12)
        else:
            self._progress.stop()
            self._progress.grid_remove()

    def _pump(self) -> None:
        try:
            while True:
                self._handle(self._queue.get_nowait())
        except queue.Empty:
            pass
        if not self._closing:
            self.root.after(40, self._pump)

    def _handle(self, item: tuple) -> None:
        kind = item[0]
        if kind == "log":
            _, text, tag = item
            self.log_text.configure(state="normal")
            self.log_text.insert("end", text.rstrip("\n") + "\n", tag or ())
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        elif kind == "status":
            self._status_var.set(item[1])
        elif kind == "changes":
            self.changes_tree.delete(*self.changes_tree.get_children())
            for c in item[1]:
                path = Path(c.path)
                self.changes_tree.insert("", "end", tags=(c.kind,),
                                         values=(_KIND_LABEL.get(c.kind, c.kind), path.name, str(path.parent)))
            self._changes_hint.configure(
                text=f"Файлов: {len(item[1])}" if item[1] else "Изменений файлов не будет")
        elif kind == "kompas":
            _, text, level = item
            self._kompas_var.set(text)
            self._kompas_label.configure(style=_PILL[level])
        elif kind == "ask":
            _, message, event, box = item
            box["yes"] = messagebox.askyesno("Подтверждение", f"{message}\n\nПродолжить?", parent=self.root)
            event.set()
        elif kind == "done":
            _, ok, title = item
            self._set_busy(False)
            self.set_status(("Готово" if ok else "Завершено с ошибкой") if not title else
                            (f"{title}: готово" if ok else f"{title}: ошибка"))

    def _on_close(self) -> None:
        if self._busy and not messagebox.askokcancel(
                "Закрыть окно", "Операция ещё выполняется. Закрыть окно всё равно?", parent=self.root):
            return
        self.close()

    def close(self) -> None:
        """Закрыть окно: отменить отложенные вызовы и уничтожить его."""
        self._closing = True
        try:
            for after_id in self.root.tk.splitlist(self.root.tk.call("after", "info")):
                self.root.after_cancel(after_id)
            self.root.destroy()
        except tk.TclError:  # окно уже закрыто
            pass
        self._release_tk_objects()

    def _release_tk_objects(self) -> None:
        """Освободить картинки, шрифты и переменные Tk ЗДЕСЬ, в главном потоке.

        Иначе сборщик мусора мог бы удалить их позже из рабочего потока, и Tcl падает
        («main thread is not in main loop», «async handler deleted by the wrong thread»).
        """
        t = self.theme
        t.images.clear()
        t.font_title = t.font_heading = t.font_small = t.font_mono = None  # type: ignore[assignment]
        self._kompas_var = self._status_var = None  # type: ignore[assignment]
