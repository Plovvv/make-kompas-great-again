"""Общая основа окон MKGA (хаб и окна модов): тема, потоки, журнал, статус КОМПАСа, подтверждения.

Правила потоков (подробно в docs/UI_STYLE.md):
  * действия выполняются в РАБОЧЕМ потоке (run_in_background), с подготовкой COM;
  * из рабочего потока НЕ трогайте виджеты: пользуйтесь log(), set_status(), post() и ask();
  * объекты Tk нельзя удалять из рабочего потока (gc.collect() там запрещён), при закрытии окна они
    освобождаются здесь, в главном потоке.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
import traceback
from tkinter import messagebox, ttk
from typing import Callable

from ..core.kompas import KompasError, com_thread
from ..core.safe_io import SafeIOError
from ..runner import ModContext
from .theme import ICONS, LIGHT, Palette, apply_theme, enable_dpi_awareness

_PILL = {"ok": "PillOk.TLabel", "error": "PillError.TLabel", "muted": "PillMuted.TLabel"}


class WindowBase:
    def __init__(self, ctx: ModContext, title: str, *, size: tuple[int, int], min_size: tuple[int, int],
                 palette: Palette = LIGHT):
        enable_dpi_awareness()
        self.ctx = ctx
        self.root = tk.Tk()
        self.theme = apply_theme(self.root, palette)
        t = self.theme
        self.root.title(title)
        # Размер задаётся «как при 96 DPI», но не больше 90% ширины и 82% высоты экрана: внизу остаётся место
        # под панель задач и рамку окна, иначе нижняя полоса уходит за экран.
        width = min(t.px(size[0]), int(self.root.winfo_screenwidth() * 0.9))
        height = min(t.px(size[1]), int(self.root.winfo_screenheight() * 0.82))
        # по центру экрана, чуть выше середины: окно не должно уходить за нижний край
        x = max(0, (self.root.winfo_screenwidth() - width) // 2)
        y = max(0, (self.root.winfo_screenheight() - height) // 2 - t.px(24))
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(min(t.px(min_size[0]), width), min(t.px(min_size[1]), height))

        self._queue: "queue.Queue[tuple]" = queue.Queue()
        self._busy = 0
        self._buttons: list[ttk.Button] = []
        self._closing = False
        self._handlers: dict[str, Callable[..., None]] = {}
        self._status_var: tk.StringVar | None = None
        self._kompas_var: tk.StringVar | None = None
        self._kompas_label: ttk.Label | None = None
        self._progress: ttk.Progressbar | None = None

        # Всё, что мод пишет в ctx.log, попадает в журнал окна (потокобезопасно).
        ctx.log = self.log
        # Вопросы пользователю из рабочего потока (например, о непроверенной версии КОМПАСа) задаются
        # диалогом в главном потоке (консольный вопрос из CLI в оконном режиме не подходит).
        ctx.confirm = self.ask

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(40, self._pump)

    # --- строительные блоки интерфейса ---------------------------------------------------------
    def label(self, text: str, icon: str | None = None) -> str:
        """Подпись кнопки со значком (если в системе есть шрифт значков)."""
        glyph = self.theme.icon(ICONS[icon]) if icon else ""
        return f"{glyph}  {text}" if glyph else text

    def build_kompas_pill(self, parent: tk.Misc, *, with_button: bool = True) -> tuple[ttk.Label, ttk.Button | None]:
        """Плашка статуса КОМПАСа и кнопка «Проверить»."""
        self._kompas_var = tk.StringVar(value="КОМПАС не проверялся")
        self._kompas_label = ttk.Label(parent, textvariable=self._kompas_var, style=_PILL["muted"])
        button = None
        if with_button:
            button = ttk.Button(parent, text=self.label("Проверить", "refresh"), style="Ghost.TButton",
                                command=self.check_kompas)
            self._buttons.append(button)
        return self._kompas_label, button

    def build_log_card(self, parent: tk.Misc, *, height: int = 6) -> ttk.Frame:
        """Тёмная карточка «Журнал» (консоль)."""
        t, p = self.theme, self.theme.palette
        card = ttk.Frame(parent, style="Log.TFrame", padding=t.pad_small)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(1, weight=1)
        ttk.Label(card, text="  ЖУРНАЛ", style="Log.Muted.TLabel").grid(
            row=0, column=0, sticky="w", padx=t.pad_small, pady=(t.pad_small // 2, 0))
        self.log_text = tk.Text(card, height=height, wrap="word", state="disabled", font=t.font_mono, relief="flat",
                                borderwidth=0, background=p.log_bg, foreground=p.log_text,
                                insertbackground=p.log_text, selectbackground=p.accent, highlightthickness=0,
                                padx=t.px(10), pady=t.px(6))
        self.log_text.grid(row=1, column=0, sticky="nsew")
        sb = ttk.Scrollbar(card, orient="vertical", command=self.log_text.yview)
        sb.grid(row=1, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=sb.set)
        self.log_text.tag_configure("error", foreground=p.log_error)
        self.log_text.tag_configure("ok", foreground=p.log_ok)
        self.log_text.tag_configure("muted", foreground=p.log_muted)
        return card

    def build_footer(self, parent: tk.Misc) -> ttk.Frame:
        """Нижняя полоса: статус слева, прогресс и контейнер кнопок действий справа (self._actions)."""
        t = self.theme
        footer = ttk.Frame(parent, padding=t.pad)
        footer.columnconfigure(0, weight=1)
        self._status_var = tk.StringVar(value="Готово")
        ttk.Label(footer, textvariable=self._status_var, style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self._progress = ttk.Progressbar(footer, mode="indeterminate", length=t.px(140))
        self._progress.grid(row=0, column=1, padx=t.pad)
        self._progress.grid_remove()  # показывается только пока выполняется действие
        self._actions = ttk.Frame(footer)
        self._actions.grid(row=0, column=2, sticky="e")
        return footer

    # --- публичный API ----------------------------------------------------------------------
    def register(self, kind: str, handler: Callable[..., None]) -> None:
        """Обработчик своих сообщений из рабочего потока: post(kind, ...) вызовет handler(...) в главном."""
        self._handlers[kind] = handler

    def post(self, kind: str, *args) -> None:
        """Отправить сообщение главному потоку (потокобезопасно)."""
        self._queue.put((kind, *args))

    def log(self, text: str, tag: str = "") -> None:
        """Строка в журнал. Можно вызывать из любого потока."""
        self._queue.put(("log", text, tag))

    def set_status(self, text: str) -> None:
        self._queue.put(("status", text))

    def ask(self, message: str, question: str = "Продолжить?") -> bool:
        """Вопрос пользователю из рабочего потока: диалог показывается в главном потоке."""
        event, box = threading.Event(), {}
        self._queue.put(("ask", message, question, event, box))
        event.wait()
        return bool(box.get("yes"))

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
                except Exception as e:  # ошибка действия не должна ронять окно
                    self.log(traceback.format_exc(), tag="error")
                    self.log(f"Действие завершилось с ошибкой: {type(e).__name__}: {e}", tag="error")
                finally:
                    # COM-объекты принадлежат этому потоку: отпускаем их здесь, до CoUninitialize.
                    # gc.collect() вызывать НЕЛЬЗЯ: он удалил бы объекты Tk из чужого потока (сбой Tcl).
                    self.ctx.reset_kompas()
            self._queue.put(("done", ok, title))

        threading.Thread(target=work, daemon=True).start()

    def check_kompas(self) -> None:
        """Проверить подключение к КОМПАСу и показать версию и редакцию в плашке."""
        def probe(ctx: ModContext) -> None:
            k = ctx.kompas()
            edition = "учебная" if k.is_study else "домашняя" if k.is_home else "полная"
            doc = k.active_document
            version = ".".join(map(str, k.version))
            self._queue.put(("kompas", f"●  КОМПАС-3D v{version} ({edition})", "ok", k.version))
            ctx.log(f"Активный документ: {doc.Name}" if doc else "Активного документа нет", tag="muted")

        def failed_probe(ctx: ModContext) -> None:
            try:
                probe(ctx)
            except Exception:
                self._queue.put(("kompas", "●  КОМПАС не подключён", "error", None))
                raise

        self.run_in_background(failed_probe, "Проверка КОМПАСа")

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
    def _set_busy(self, busy: bool) -> None:
        self._busy += 1 if busy else -1
        active = self._busy > 0
        for b in self._buttons:
            b.state(["disabled"] if active else ["!disabled"])
        if self._progress is not None:
            if active:
                self._progress.grid()
                self._progress.start(12)
            else:
                self._progress.stop()
                self._progress.grid_remove()
        self.on_busy_changed(active)

    def on_busy_changed(self, busy: bool) -> None:
        """Переопределяется в окнах: например, отключить свои элементы на время действия."""

    def _pump(self) -> None:
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                self._handle(item)
            except Exception:  # ошибка в обработчике не должна навсегда остановить окно
                try:
                    self._handle(("log", traceback.format_exc(), "error"))
                except Exception:
                    pass
        if not self._closing:
            self.root.after(40, self._pump)

    def _handle(self, item: tuple) -> None:
        kind = item[0]
        custom = self._handlers.get(kind)
        if custom is not None:
            custom(*item[1:])
        elif kind == "log":
            _, text, tag = item
            self.log_text.configure(state="normal")
            self.log_text.insert("end", text.rstrip("\n") + "\n", tag or ())
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        elif kind == "status":
            if self._status_var is not None:
                self._status_var.set(item[1])
        elif kind == "kompas":
            _, text, level, version = item
            if self._kompas_var is not None:
                self._kompas_var.set(text)
                self._kompas_label.configure(style=_PILL[level])
            self.on_kompas(version)
        elif kind == "ask":
            _, message, question, event, box = item
            try:
                box["yes"] = messagebox.askyesno("Подтверждение", f"{message}\n\n{question}", parent=self.root)
            finally:
                event.set()  # рабочий поток не должен зависнуть, даже если диалог не удалось показать
        elif kind == "done":
            _, ok, title = item
            self._set_busy(False)
            self.set_status(("Готово" if ok else "Завершено с ошибкой") if not title else
                            (f"{title}: готово" if ok else f"{title}: ошибка"))

    def on_kompas(self, version: tuple | None) -> None:
        """Переопределяется: версия КОМПАСа определена (или None, если не подключён)."""

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
        self._status_var = self._kompas_var = None
        for name, value in list(vars(self).items()):  # переменные Tk, созданные окном и его потомками
            if isinstance(value, tk.Variable):
                setattr(self, name, None)
