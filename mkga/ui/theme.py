"""Единый стиль окон MKGA (docs/UI_STYLE.md): современная плоская тема со скруглениями.

Без внешних зависимостей: на основе ttk-темы `clam`. Все скругления, поля, галочки, полосы
прокрутки рисуются при запуске растеризатором mkga.ui.raster ПОД ТЕКУЩИЙ МАСШТАБ ЭКРАНА, поэтому
вид одинаково чёткий на 100%, 150% и 200% (в отличие от готовых тем с фиксированными PNG).

    enable_dpi_awareness()                 # ДО создания tk.Tk()
    root = tk.Tk()
    theme = apply_theme(root)              # LIGHT по умолчанию; apply_theme(root, DARK)
    ttk.Frame(root, style="Card.TFrame")   # карточка; внутри используйте Card.TLabel и т.п.

Все размеры в пикселях передавайте через theme.px(): Tk не масштабирует пиксели сам.

Стили: TButton (обычная), Primary.TButton (главное действие), Ghost.TButton (без рамки), TEntry,
TCombobox, TCheckbutton, TRadiobutton, TProgressbar, Treeview, Vertical/Horizontal.TScrollbar,
Card.TFrame (+ Card.TLabel, Card.Muted.TLabel, Card.TCheckbutton, Card.TRadiobutton),
Title.TLabel, Heading.TLabel, Muted.TLabel, PillOk/PillError/PillMuted.TLabel (плашки статуса).
"""

from __future__ import annotations

import sys
import tkinter as tk
from dataclasses import dataclass
from tkinter import font, ttk
from typing import Callable

from . import raster


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str            # фон окна
    surface: str       # фон карточек и полей
    border: str
    border_strong: str
    text: str
    muted: str
    accent: str
    accent_hover: str
    accent_press: str
    accent_soft: str   # выделение строк, наведение на «призрачные» кнопки
    on_accent: str
    ok: str
    ok_soft: str
    error: str
    error_soft: str
    disabled_bg: str
    disabled_text: str
    log_bg: str        # журнал выглядит как тёмная консоль в обеих темах
    log_text: str
    log_ok: str
    log_error: str
    log_muted: str
    dark: bool = False


LIGHT = Palette(
    name="light", bg="#F3F4F7", surface="#FFFFFF", border="#E1E4EA", border_strong="#C5CBD6",
    text="#1B1F27", muted="#667085", accent="#2563EB", accent_hover="#1D4FD8", accent_press="#1A44BC",
    accent_soft="#E6EEFF", on_accent="#FFFFFF", ok="#15803D", ok_soft="#E3F4E8", error="#C62828",
    error_soft="#FBE9E7", disabled_bg="#F0F2F5", disabled_text="#9AA3B2",
    log_bg="#111827", log_text="#E5E7EB", log_ok="#4ADE80", log_error="#F87171", log_muted="#9CA3AF",
)

DARK = Palette(
    name="dark", bg="#14161A", surface="#1D2026", border="#2C313A", border_strong="#434A57",
    text="#E8EAEE", muted="#9AA3B2", accent="#4F83F7", accent_hover="#6A97FA", accent_press="#3E6FDE",
    accent_soft="#26324A", on_accent="#FFFFFF", ok="#4ADE80", ok_soft="#1C3326", error="#F87171",
    error_soft="#3A2224", disabled_bg="#23272E", disabled_text="#6B7482",
    log_bg="#0C0E12", log_text="#E5E7EB", log_ok="#4ADE80", log_error="#F87171", log_muted="#9CA3AF",
    dark=True,
)


def system_palette() -> Palette:
    """Палитра по системной теме Windows (Параметры, Персонализация, Цвета); вне Windows светлая."""
    if sys.platform != "win32":
        return LIGHT
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            light, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return LIGHT if light else DARK
    except OSError:
        return LIGHT


def palette_by_name(name: str) -> Palette:
    """'light' | 'dark' | 'system' -> палитра (неизвестное имя даёт системную)."""
    return {"light": LIGHT, "dark": DARK}.get(name) or system_palette()


def enable_dpi_awareness() -> bool:
    """Включить поддержку высокого DPI в Windows, чтобы окно не размывалось.

    Вызывать один раз, до создания tk.Tk(). Tk не поддерживает разные масштабы на разных мониторах
    (per-monitor), поэтому берётся системный масштаб. Возвращает True, если режим включён.
    """
    if sys.platform != "win32":
        return False
    import ctypes

    try:
        # S_OK (0) или E_ACCESSDENIED (режим уже задан): оба случая нас устраивают.
        result = ctypes.windll.shcore.SetProcessDpiAwareness(1)
        return result in (0, -2147024891)
    except (AttributeError, OSError):  # старая Windows без shcore
        try:
            return bool(ctypes.windll.user32.SetProcessDPIAware())
        except (AttributeError, OSError):
            return False


@dataclass
class Theme:
    px: Callable[[int], int]          # перевод «пикселей при 96 DPI» в реальные
    pad: int                          # основной отступ
    pad_small: int
    palette: Palette
    font_title: font.Font
    font_heading: font.Font
    font_small: font.Font
    font_mono: font.Font
    icon_font: str | None             # семейство шрифта значков (Segoe Fluent Icons) или None
    images: list                      # ссылки на PhotoImage (иначе Tk их удалит)

    def card(self, parent: tk.Misc, padding: int | None = None, **kw) -> ttk.Frame:
        """Карточка (скруглённая белая панель). Внутри используйте стили Card.*."""
        pad = self.pad if padding is None else padding
        return ttk.Frame(parent, style="Card.TFrame", padding=pad, **kw)

    def icon(self, glyph: str) -> str:
        """Значок для подписи кнопки: символ из шрифта значков, а без него пустая строка."""
        return glyph if self.icon_font else ""


# Коды значков Segoe Fluent Icons / Segoe MDL2 Assets.
ICONS = {
    "refresh": "", "undo": "", "save": "", "search": "", "add": "",
    "delete": "", "view": "", "play": "", "check": "", "info": "",
}


def _first_family(root: tk.Misc, candidates: tuple[str, ...]) -> str | None:
    have = set(font.families(root))
    return next((f for f in candidates if f in have), None)


def style_titlebar(root: tk.Tk, p: Palette) -> None:
    """Цвет заголовка окна под тему (Windows 11; на старых версиях Windows молча ничего не делает)."""
    if sys.platform != "win32":
        return
    import ctypes

    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()

        def set_attr(attr: int, value: int) -> None:
            v = ctypes.c_int(value)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))

        def bgr(color: str) -> int:
            r, g, b = raster.parse_color(color)
            return int(b) << 16 | int(g) << 8 | int(r)

        set_attr(20, 1 if p.dark else 0)       # DWMWA_USE_IMMERSIVE_DARK_MODE
        set_attr(35, bgr(p.bg))                # DWMWA_CAPTION_COLOR
        set_attr(36, bgr(p.text))              # DWMWA_TEXT_COLOR
        set_attr(34, bgr(p.border))            # DWMWA_BORDER_COLOR
    except Exception:  # noqa: BLE001  косметика не должна ломать запуск
        pass


def apply_theme(root: tk.Tk, palette: Palette = LIGHT) -> Theme:
    """Применить стиль MKGA к окну: тема, шрифты, картинки элементов, именованные стили."""
    scale = root.winfo_fpixels("1i") / 96.0

    def px(n: float) -> int:
        return max(1, round(n * scale))

    p = palette
    style = ttk.Style(root)
    style.theme_use("clam")  # одинаковая основа на любой ОС
    root.configure(background=p.bg)
    images: list = []

    # --- шрифты --------------------------------------------------------------------------
    ui_family = _first_family(root, ("Segoe UI Variable Text", "Segoe UI", "Helvetica Neue", "DejaVu Sans"))
    mono_family = _first_family(root, ("Cascadia Mono", "Consolas", "DejaVu Sans Mono"))
    icon_family = _first_family(root, ("Segoe Fluent Icons", "Segoe MDL2 Assets"))
    base = 10
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkCaptionFont", "TkTooltipFont", "TkHeadingFont"):
        f = font.nametofont(name)
        f.configure(size=base, **({"family": ui_family} if ui_family else {}))
    default = font.nametofont("TkDefaultFont")
    fixed = font.nametofont("TkFixedFont")
    fixed.configure(size=base, **({"family": mono_family} if mono_family else {}))
    fam = default.cget("family")
    title = font.Font(root, family=fam, size=base + 8, weight="bold")
    heading = font.Font(root, family=fam, size=base + 1, weight="bold")
    small = font.Font(root, family=fam, size=base - 1)

    # --- картинки -------------------------------------------------------------------------
    def photo(im: raster.Image) -> tk.PhotoImage:
        ph = tk.PhotoImage(master=root, data=im.to_base64_png())
        images.append(ph)
        return ph

    tile = px(40)  # размер «середины» картинки: ttk закрашивает середину плитками этого размера

    def box(fill: str | None, border: str | None, radius: float, bw: float = 1.0):
        """Картинка со скруглением для растягиваемого элемента. Возвращает (PhotoImage, радиус в px).

        Рисуется минимальной (2r+2), затем середина размножается до tile: иначе ttk выкладывает большую
        карточку плитками по 2 пикселя (сотни тысяч отрисовок, секунды на кадр). Минимальный размер
        элемента задавайте через width/height = 2r+2.
        """
        r = px(radius)
        s0 = 2 * r + 2
        im = raster.Image(s0, s0)
        im.rrect(0, 0, s0, s0, r, fill, border, px(bw) if border else 0)
        return photo(im.stretched(r, 2 * r + tile, 2 * r + tile)), r

    bw = 1.0
    rad = 8     # радиус скругления кнопок и полей
    card_rad = 12

    # Кнопки: (fill, border) по состояниям
    def button_element(name: str, normal, hover, pressed, disabled, focus_border: str) -> None:
        imgs = {}
        r = px(rad)
        for key, (fill, border) in dict(n=normal, h=hover, p=pressed, d=disabled, f=(normal[0], focus_border)).items():
            imgs[key], _ = box(fill, border, rad, bw if key != "f" else 2.0)
        style.element_create(name, "image", imgs["n"], ("disabled", imgs["d"]), ("pressed", imgs["p"]),
                             ("active", imgs["h"]), ("focus", imgs["f"]), border=(r, r, r, r), sticky="nswe",
                             width=2 * r + 2, height=2 * r + 2)

    button_element("Mkga.Button.bg", (p.surface, p.border_strong), (p.accent_soft, p.border_strong),
                   (p.border, p.border_strong), (p.disabled_bg, p.border), p.accent)
    button_element("Mkga.Primary.bg", (p.accent, p.accent), (p.accent_hover, p.accent_hover),
                   (p.accent_press, p.accent_press), (p.disabled_bg, p.border), p.text)
    button_element("Mkga.Ghost.bg", (p.bg, p.bg), (p.accent_soft, p.accent_soft), (p.border, p.border),
                   (p.bg, p.bg), p.accent)

    def button_layout(name: str, element: str) -> None:
        style.layout(name, [(element, {"sticky": "nswe", "children": [
            ("Button.padding", {"sticky": "nswe", "children": [("Button.label", {"sticky": "nswe"})]})]})])

    style.configure(".", background=p.bg, foreground=p.text, font=default, bordercolor=p.border,
                    lightcolor=p.bg, darkcolor=p.bg, troughcolor=p.surface, focuscolor=p.bg)
    btn_pad = (px(16), px(8))
    # Фон САМОГО виджета должен совпадать с фоном родителя, иначе он закрасит скруглённые углы картинки.
    # Для кнопок внутри карточек есть варианты Card.TButton / Card.Primary.TButton / Card.Ghost.TButton.
    for prefix, around in (("", p.bg), ("Card.", p.surface)):
        for base, element, fg in (
            ("TButton", "Mkga.Button.bg", p.text),
            ("Primary.TButton", "Mkga.Primary.bg", p.on_accent),
            ("Ghost.TButton", "Mkga.Ghost.bg", p.text),
        ):
            name = prefix + base
            button_layout(name, element)
            style.configure(name, padding=btn_pad, foreground=fg, background=around, relief="flat",
                            borderwidth=0, anchor="center", font=heading if base.startswith("Primary") else default)
            style.map(name, foreground=[("disabled", p.disabled_text)], background=[("disabled", around)])

    # Боковая навигация: пункт и выбранный пункт (текст слева, выбранный залит мягким акцентом)
    button_element("Mkga.Nav.bg", (p.bg, p.bg), (p.accent_soft, p.accent_soft), (p.border, p.border),
                   (p.bg, p.bg), p.accent)
    button_element("Mkga.NavActive.bg", (p.accent_soft, p.accent_soft), (p.accent_soft, p.accent_soft),
                   (p.accent_soft, p.accent_soft), (p.accent_soft, p.accent_soft), p.accent)
    for name, element, fg, fnt in (("Nav.TButton", "Mkga.Nav.bg", p.text, default),
                                   ("NavActive.TButton", "Mkga.NavActive.bg", p.accent, heading)):
        button_layout(name, element)
        style.configure(name, padding=(px(16), px(11)), foreground=fg, background=p.bg, relief="flat",
                        borderwidth=0, anchor="w", font=fnt)
        style.map(name, foreground=[("disabled", p.disabled_text)])

    # Поля ввода
    r = px(rad)
    fld_n, _ = box(p.surface, p.border_strong, rad, bw)
    fld_f, _ = box(p.surface, p.accent, rad, 2.0)
    fld_d, _ = box(p.disabled_bg, p.border, rad, bw)
    style.element_create("Mkga.Field.bg", "image", fld_n, ("disabled", fld_d), ("focus", fld_f),
                         border=(r, r, r, r), sticky="nswe", width=2 * r + 2, height=2 * r + 2)
    style.layout("TEntry", [("Mkga.Field.bg", {"sticky": "nswe", "children": [
        ("Entry.padding", {"sticky": "nswe", "children": [("Entry.textarea", {"sticky": "nswe"})]})]})])
    style.configure("TEntry", padding=(px(10), px(7)), fieldbackground=p.surface, foreground=p.text,
                    insertcolor=p.text, selectbackground=p.accent, selectforeground=p.on_accent, background=p.bg)
    style.map("TEntry", foreground=[("disabled", p.disabled_text)], fieldbackground=[("disabled", p.disabled_bg)])
    style.configure("Card.TEntry", background=p.surface)

    chev = px(22)

    def chevron(color: str) -> tk.PhotoImage:
        im = raster.Image(chev, chev)
        c = chev / 2.0
        im.polyline([(c - px(4), c - px(2)), (c, c + px(2.5)), (c + px(4), c - px(2))], max(1.5, px(1.6)), color)
        return photo(im)

    style.element_create("Mkga.Chevron", "image", chevron(p.muted), ("disabled", chevron(p.disabled_text)),
                         ("active", chevron(p.text)), sticky="")
    style.layout("TCombobox", [("Mkga.Field.bg", {"sticky": "nswe", "children": [
        ("Mkga.Chevron", {"side": "right", "sticky": "ns"}),
        ("Combobox.padding", {"expand": "1", "sticky": "nswe", "children": [("Combobox.textarea", {"sticky": "nswe"})]})]})])
    style.configure("TCombobox", padding=(px(10), px(7)), fieldbackground=p.surface, foreground=p.text,
                    background=p.bg, arrowsize=px(12), selectbackground=p.surface, selectforeground=p.text)
    style.configure("Card.TCombobox", background=p.surface)
    style.map("TCombobox", fieldbackground=[("readonly", p.surface)], foreground=[("disabled", p.disabled_text)],
              selectbackground=[("readonly", p.surface)], selectforeground=[("readonly", p.text)])
    root.option_add("*TCombobox*Listbox.background", p.surface)
    root.option_add("*TCombobox*Listbox.foreground", p.text)
    root.option_add("*TCombobox*Listbox.selectBackground", p.accent)
    root.option_add("*TCombobox*Listbox.selectForeground", p.on_accent)
    root.option_add("*TCombobox*Listbox.font", default)

    # Карточка
    cr = px(card_rad)
    card_img, _ = box(p.surface, p.border, card_rad, bw)
    style.element_create("Mkga.Card.bg", "image", card_img, border=(cr, cr, cr, cr), sticky="nswe",
                         width=2 * cr + 2, height=2 * cr + 2)
    style.layout("Card.TFrame", [("Mkga.Card.bg", {"sticky": "nswe", "children": [
        ("Card.padding", {"sticky": "nswe"})]})])
    style.configure("Card.TFrame", background=p.bg)  # внутренний отступ задаётся виджетом: Theme.card()
    # Обычный контейнер ВНУТРИ карточки (без своей рамки): фон как у карточки
    style.configure("CardInner.TFrame", background=p.surface)
    # Тёмная «консольная» карточка для журнала
    log_img, _ = box(p.log_bg, p.log_bg, card_rad, bw)
    style.element_create("Mkga.LogCard.bg", "image", log_img, border=(cr, cr, cr, cr), sticky="nswe",
                         width=2 * cr + 2, height=2 * cr + 2)
    style.layout("Log.TFrame", [("Mkga.LogCard.bg", {"sticky": "nswe", "children": [
        ("Log.padding", {"sticky": "nswe"})]})])
    style.configure("Log.TFrame", background=p.bg)
    style.configure("Log.Muted.TLabel", background=p.log_bg, foreground=p.log_muted, font=small)
    style.configure("Card.TLabel", background=p.surface, foreground=p.text)
    style.configure("Card.Muted.TLabel", background=p.surface, foreground=p.muted)
    style.configure("Card.Small.Muted.TLabel", background=p.surface, foreground=p.muted, font=small)
    style.configure("Card.Heading.TLabel", background=p.surface, foreground=p.text, font=heading)

    # Метки
    style.configure("TLabel", background=p.bg, foreground=p.text)
    style.configure("Title.TLabel", font=title)
    style.configure("Heading.TLabel", font=heading)
    style.configure("Muted.TLabel", foreground=p.muted)
    style.configure("Small.Muted.TLabel", foreground=p.muted, font=small)

    # Плашки статуса (скруглённые)
    def pill(name: str, fill: str, fg: str) -> None:
        h = px(14)
        s = 2 * h + 2  # +2: у картинки должна быть растягиваемая середина (иначе виден только край)
        im = raster.Image(s, s)
        im.rrect(0, 0, s, s, h, fill)
        style.element_create(f"Mkga.{name}.bg", "image", photo(im), border=(h, h, h, h), sticky="nswe")
        for prefix, around in (("", p.bg), ("Card.", p.surface)):
            style.layout(f"{prefix}{name}.TLabel", [(f"Mkga.{name}.bg", {"sticky": "nswe", "children": [
                ("Label.padding", {"sticky": "nswe", "children": [("Label.label", {"sticky": "nswe"})]})]})])
            style.configure(f"{prefix}{name}.TLabel", background=around, foreground=fg,
                            padding=(px(12), px(4)), font=default)

    pill("PillOk", p.ok_soft, p.ok)
    pill("PillError", p.error_soft, p.error)
    pill("PillMuted", p.disabled_bg, p.muted)
    pill("PillAccent", p.accent_soft, p.accent)

    # Флажки и переключатели
    ind = px(18)

    gap = px(8)  # прозрачный зазор справа от значка: отступ до текста

    def check(state: str) -> tk.PhotoImage:
        im = raster.Image(ind + gap, ind)
        rr = px(5)
        if state == "off":
            im.rrect(0, 0, ind, ind, rr, p.surface, p.border_strong, px(1.5))
        elif state == "hover":
            im.rrect(0, 0, ind, ind, rr, p.accent_soft, p.accent, px(1.5))
        elif state == "off_d":
            im.rrect(0, 0, ind, ind, rr, p.disabled_bg, p.border, px(1.5))
        else:
            fill = p.accent if state == "on" else p.border_strong
            im.rrect(0, 0, ind, ind, rr, fill, fill, px(1.5))
            s = ind / 18.0
            im.polyline([(4.5 * s, 9.5 * s), (7.7 * s, 12.7 * s), (13.5 * s, 5.8 * s)], max(1.6, 2.0 * s), p.on_accent)
        return photo(im)

    style.element_create("Mkga.Check.ind", "image", check("off"),
                         ("disabled", "selected", check("on_d")), ("disabled", check("off_d")),
                         ("selected", check("on")), ("active", check("hover")), sticky="")

    def radio(state: str) -> tk.PhotoImage:
        im = raster.Image(ind + gap, ind)
        c, rr = ind / 2.0, ind / 2.0
        if state == "off":
            im.circle(c, c, rr, p.surface, p.border_strong, px(1.5))
        elif state == "hover":
            im.circle(c, c, rr, p.accent_soft, p.accent, px(1.5))
        elif state == "off_d":
            im.circle(c, c, rr, p.disabled_bg, p.border, px(1.5))
        else:
            col = p.accent if state == "on" else p.border_strong
            im.circle(c, c, rr, p.surface, col, px(2.0))
            im.circle(c, c, rr * 0.45, col)
        return photo(im)

    style.element_create("Mkga.Radio.ind", "image", radio("off"),
                         ("disabled", "selected", radio("on_d")), ("disabled", radio("off_d")),
                         ("selected", radio("on")), ("active", radio("hover")), sticky="")
    for cls, element in (("Checkbutton", "Mkga.Check.ind"), ("Radiobutton", "Mkga.Radio.ind")):
        for prefix, bg in (("T", p.bg), ("Card.T", p.surface)):
            name = f"{prefix}{cls}"
            style.layout(name, [(f"{cls}.padding", {"sticky": "nswe", "children": [
                (element, {"side": "left", "sticky": ""}),
                (f"{cls}.focus", {"side": "left", "sticky": "w", "children": [(f"{cls}.label", {"sticky": "nswe"})]})]})])
            style.configure(name, background=bg, foreground=p.text, padding=(0, px(3)), indicatorsize=ind)
            style.map(name, background=[("active", bg)], foreground=[("disabled", p.disabled_text)])
        # отступ между значком и текстом
    for name in ("TCheckbutton", "TRadiobutton", "Card.TCheckbutton", "Card.TRadiobutton"):
        style.configure(name, padding=(0, px(3)))

    # Прогресс
    ph = px(4)  # радиус: полоса толщиной 8 «логических» пикселей
    ps = 2 * ph + 2  # +2: растягиваемая середина
    trough = raster.Image(ps, ps)
    trough.rrect(0, 0, ps, ps, ph, p.border)
    bar = raster.Image(ps, ps)
    bar.rrect(0, 0, ps, ps, ph, p.accent)
    # Имена элементов обязаны оканчиваться на «.trough» / «.pbar»: по ним виджет находит свои части.
    style.element_create("Mkga.Horizontal.Progressbar.trough", "image", photo(trough),
                         border=(ph, ph, ph, ph), sticky="nswe")
    style.element_create("Mkga.Horizontal.Progressbar.pbar", "image", photo(bar),
                         border=(ph, ph, ph, ph), sticky="nswe")
    style.layout("Horizontal.TProgressbar", [("Mkga.Horizontal.Progressbar.trough", {"sticky": "nswe", "children": [
        ("Mkga.Horizontal.Progressbar.pbar", {"sticky": "ns", "side": "left"})]})])
    style.configure("Horizontal.TProgressbar", background=p.bg)
    style.configure("Card.Horizontal.TProgressbar", background=p.surface)

    # Полосы прокрутки: только тонкий ползунок, без стрелок
    tw = px(12)             # толщина полосы прокрутки
    inset = px(3)           # отступ ползунка от краёв
    cap = (tw - 2 * inset) // 2 + 1
    for orient in ("Vertical", "Horizontal"):
        vertical = orient == "Vertical"
        w, h = (tw, 2 * cap + 2 + 2 * inset) if vertical else (2 * cap + 2 + 2 * inset, tw)
        thumbs = []
        for col in (p.border_strong, p.muted, p.muted):
            im = raster.Image(w, h)
            t_ = tw - 2 * inset
            if vertical:
                im.rrect(inset, 0, t_, h, t_ / 2.0, col)
            else:
                im.rrect(0, inset, w, t_, t_ / 2.0, col)
            thumbs.append(photo(im))
        # у картинки есть растягиваемая середина только вдоль полосы
        border = (0, cap + inset, 0, cap + inset) if vertical else (cap + inset, 0, cap + inset, 0)
        # имя элемента оканчивается на «.thumb»: так виджет прокрутки находит ползунок
        style.element_create(f"Mkga.{orient}.Scrollbar.thumb", "image", thumbs[0], ("pressed", thumbs[2]),
                             ("active", thumbs[1]), border=border, sticky="nswe")
        style.layout(f"{orient}.TScrollbar", [(f"{orient}.Scrollbar.trough", {
            "sticky": "ns" if orient == "Vertical" else "we",
            "children": [(f"Mkga.{orient}.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        style.configure(f"{orient}.TScrollbar", troughcolor=p.surface, borderwidth=0, relief="flat",
                        background=p.surface)

    # Таблица
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    style.configure("Treeview", background=p.surface, fieldbackground=p.surface, foreground=p.text,
                    rowheight=default.metrics("linespace") + px(14), borderwidth=0, relief="flat")
    style.map("Treeview", background=[("selected", p.accent_soft)], foreground=[("selected", p.text)])
    style.configure("Treeview.Heading", background=p.surface, foreground=p.muted, font=small, relief="flat",
                    padding=(px(8), px(8)), borderwidth=0)
    style.map("Treeview.Heading", background=[("active", p.surface)])

    style.configure("TSeparator", background=p.border)
    style.configure("TPanedwindow", background=p.bg)

    # clam подставляет СВОЙ серый фон для состояний active/pressed (открытый список комбобокса!), readonly и
    # disabled. Он закрасил бы скруглённые углы, поэтому фон виджета закрепляется во ВСЕХ состояниях.
    pinned_states = ("disabled", "readonly", "active", "pressed", "focus", "selected")
    for prefix, around in (("", p.bg), ("Card.", p.surface)):
        for base in ("TButton", "Primary.TButton", "Ghost.TButton", "Nav.TButton", "NavActive.TButton", "TEntry", "TCombobox", "Horizontal.TProgressbar",
                     "PillOk.TLabel", "PillError.TLabel", "PillMuted.TLabel", "PillAccent.TLabel", "TCheckbutton",
                     "TRadiobutton"):
            style.map(prefix + base, background=[(state, around) for state in pinned_states])

    theme = Theme(px=px, pad=px(16), pad_small=px(8), palette=p, font_title=title, font_heading=heading,
                  font_small=small, font_mono=fixed, icon_font=icon_family, images=images)
    root._mkga_theme = theme  # type: ignore[attr-defined]  # держим картинки живыми
    style_titlebar(root, p)
    return theme
