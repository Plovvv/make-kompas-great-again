"""Упрощённый 2D-чертёж изделия для окна мода: вид сбоку и вид на головку с самыми нужными размерами.

Здесь нет Tk: `draw(shape_id, dims, length)` возвращает список примитивов в миллиметрах (ось Y вверх), а рисуют их
`render_tk` (окно) и `to_svg` (самопроверка и документация). Так чертёж проверяется тестами без окна.

Виды условные (не по ЕСКД): основная линия, тонкая, осевая штрихпунктиром, невидимая штрихом, размерная с стрелками.
У каждого размера подпись «буква значение»; расшифровку букв даёт `legend()`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

# виды линий
OUTLINE, THIN, CENTER, HIDDEN, DIM = "outline", "thin", "center", "hidden", "dim"


@dataclass(frozen=True)
class Line:
    x1: float
    y1: float
    x2: float
    y2: float
    kind: str = OUTLINE


@dataclass(frozen=True)
class Circle:
    cx: float
    cy: float
    r: float
    kind: str = OUTLINE


@dataclass(frozen=True)
class Arrow:
    """Стрелка размерной линии: остриё в (x, y), направление (dx, dy) от острия назад по линии."""

    x: float
    y: float
    dx: float
    dy: float


@dataclass(frozen=True)
class Text:
    x: float
    y: float
    text: str
    anchor: str = "s"        # как у Tk: "s" снизу по центру, "w" слева, "e" справа, "n" сверху
    kind: str = DIM


@dataclass(frozen=True)
class Drawing:
    prims: tuple
    width: float
    height: float
    x0: float
    y0: float
    caption: tuple[tuple[str, str], ...] = ()    # (подпись вида, где) для подсказки

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return self.x0, self.y0, self.x0 + self.width, self.y0 + self.height


def num(x: float) -> str:
    return f"{x:.2f}".rstrip("0").rstrip(".").replace(".", ",")


# --- размерные линии -----------------------------------------------------------------------------------
def _arrows_and_line(prims: list, x1: float, y1: float, x2: float, y2: float, ext: float) -> None:
    prims.append(Line(x1, y1, x2, y2, DIM))
    length = math.hypot(x2 - x1, y2 - y1) or 1.0
    ux, uy = (x2 - x1) / length, (y2 - y1) / length
    prims.append(Arrow(x1, y1, ux, uy))
    prims.append(Arrow(x2, y2, -ux, -uy))


def dim_h(prims: list, x1: float, x2: float, y_feature: float, y_dim: float, label: str, text_gap: float) -> None:
    """Горизонтальный размер между x1 и x2; выносные линии от y_feature до y_dim."""
    sign = 1.0 if y_dim >= y_feature else -1.0
    over = 0.6 * sign
    prims.append(Line(x1, y_feature + 0.4 * sign, x1, y_dim + over, DIM))
    prims.append(Line(x2, y_feature + 0.4 * sign, x2, y_dim + over, DIM))
    _arrows_and_line(prims, x1, y_dim, x2, y_dim, 0)
    prims.append(Text((x1 + x2) / 2, y_dim + text_gap * sign, label, "s" if sign > 0 else "n"))


def dim_v(prims: list, y1: float, y2: float, x_feature: float, x_dim: float, label: str, text_gap: float) -> None:
    """Вертикальный размер между y1 и y2; подпись слева или справа от линии."""
    sign = 1.0 if x_dim >= x_feature else -1.0
    over = 0.6 * sign
    prims.append(Line(x_feature + 0.4 * sign, y1, x_dim + over, y1, DIM))
    prims.append(Line(x_feature + 0.4 * sign, y2, x_dim + over, y2, DIM))
    _arrows_and_line(prims, x_dim, y1, x_dim, y2, 0)
    prims.append(Text(x_dim + text_gap * sign, (y1 + y2) / 2, label, "w" if sign > 0 else "e"))


def _center_h(prims, x1, x2, y):
    prims.append(Line(x1, y, x2, y, CENTER))


def _center_v(prims, x, y1, y2):
    prims.append(Line(x, y1, x, y2, CENTER))


def _hexagon(cx: float, cy: float, across_flats: float, kind: str = OUTLINE) -> list[Line]:
    """Шестигранник «под ключ» с вершинами на горизонтальной оси (плоскости сверху и снизу)."""
    r = across_flats / math.sqrt(3.0)
    pts = [(cx + r * math.cos(math.radians(60 * i)), cy + r * math.sin(math.radians(60 * i))) for i in range(6)]
    return [Line(*pts[i], *pts[(i + 1) % 6], kind) for i in range(6)]


def _poly(points, kind=OUTLINE, close=True) -> list[Line]:
    n = len(points)
    last = n if close else n - 1
    return [Line(*points[i], *points[(i + 1) % n], kind) for i in range(last)]


def _finish(prims: list, regions: list[tuple[float, float, float, float]], caption=()) -> Drawing:
    xs0 = min(r[0] for r in regions)
    ys0 = min(r[1] for r in regions)
    xs1 = max(r[2] for r in regions)
    ys1 = max(r[3] for r in regions)
    return Drawing(tuple(prims), xs1 - xs0, ys1 - ys0, xs0, ys0, tuple(caption))


# --- чертежи форм --------------------------------------------------------------------------------------
def _dome_points(dk: float, k: float, steps: int = 28) -> list[tuple[float, float]]:
    """Купол головки: от вершины (0, 0) до кромки (dk/2, -k), точки по дуге окружности."""
    r = ((dk / 2) ** 2 + k ** 2) / (2.0 * k)
    end = math.atan2(r - k, dk / 2)           # угол кромки от оси X
    pts = []
    for i in range(steps + 1):
        ang = math.pi / 2 - (math.pi / 2 - end) * i / steps
        pts.append((r * math.cos(ang), -r + r * math.sin(ang)))
    return pts


def draw_screw(dims: Mapping[str, float], length: float, head: str = "cap") -> Drawing:
    """Винт с шестигранным углублением: head = cap (цилиндрическая), csk (потайная), button (полукруглая)."""
    d, p, dk, k, s, t = (dims[x] for x in ("d", "P", "dk", "k", "s", "t"))
    b = dims.get("b")
    c = min(0.06 * dk, k / 3.0)
    countersunk = head == "csk"
    flange = head == "flange"
    dc = dims.get("dc", dk)
    c_fl = dims.get("c", 0.0)
    shank_end = -length if countersunk else -(k + length)   # у потайного длина считается от верха головки
    big = max(dc, abs(shank_end))
    gap = 0.07 * big
    text = 0.012 * big + 0.5
    prims: list = []
    top_y = 0.0

    # правая половина контура от верха головки до конца стержня (без точек на оси)
    if head == "cap":
        half = [(dk / 2 - c, 0.0), (dk / 2, -c), (dk / 2, -k), (d / 2, -k)]
    elif head == "csk":
        rim = k - (dk - d) / 2.0
        half = [(dk / 2, 0.0)] + ([(dk / 2, -rim)] if rim > 1e-9 else []) + [(d / 2, -k)]
    else:
        half = _dome_points(dk, k)[1:] + [(d / 2, -k)]
    half += [(d / 2, shank_end + p), (d / 2 - p, shank_end)]
    outline = [(-x, y) for x, y in reversed(half)] + half
    prims += _poly(outline, close=True)
    # углубление под ключ (невидимое): две вертикальные линии на ширине «под ключ» и дно
    prims += [Line(-s / 2, top_y, -s / 2, top_y - t, HIDDEN), Line(s / 2, top_y, s / 2, top_y - t, HIDDEN),
              Line(-s / 2, top_y - t, s / 2, top_y - t, HIDDEN)]
    # условное изображение резьбы: тонкая линия по внутреннему диаметру на длину b от конца и торцевая линия
    minor = d - 1.082532 * p
    full = b is None or b >= length
    y_thread_end = shank_end + (length if full else b)
    y_top_thread = min(y_thread_end, -k)
    prims += [Line(-minor / 2, shank_end, -minor / 2, y_top_thread, THIN),
              Line(minor / 2, shank_end, minor / 2, y_top_thread, THIN)]
    if not full:
        prims.append(Line(-d / 2, y_thread_end, d / 2, y_thread_end, OUTLINE))
    _center_v(prims, 0, top_y + gap * 0.6, shank_end - gap * 0.6)

    # размеры вида сбоку
    dim_h(prims, -dk / 2, dk / 2, top_y, top_y + gap, f"dk {num(dk)}", text)
    dim_v(prims, -k, top_y, dc / 2, dc / 2 + gap, f"k {num(k)}", text)
    if flange:
        dim_h(prims, -dc / 2, dc / 2, -k, -k - gap * 0.9, f"dc {num(dc)}", text)
    l_top = top_y if countersunk else -k
    dim_v(prims, shank_end, l_top, -dc / 2, -dc / 2 - gap, f"l {num(length)}", text)
    if not full:
        dim_v(prims, shank_end, y_thread_end, d / 2, d / 2 + gap * 1.8, f"b {num(b)}", text)
    dim_h(prims, -d / 2, d / 2, shank_end, shank_end - gap, f"d {num(d)}", text)
    side = (-dc / 2 - gap * 2.6, shank_end - gap * 2.0, dc / 2 + gap * 3.6, top_y + gap * 1.8)

    # вид на головку (справа от вида сбоку)
    cx = side[2] + gap * 1.2 + dc / 2 + gap
    cy = -k / 2
    prims.append(Circle(cx, cy, dc / 2))
    if flange:
        prims.append(Circle(cx, cy, dk / 2, THIN))
    if head == "cap":
        prims.append(Circle(cx, cy, dk / 2 - c, THIN))
    elif head == "csk":
        prims.append(Circle(cx, cy, d / 2, THIN))
    prims += _hexagon(cx, cy, s)
    _center_h(prims, cx - dc / 2 - gap * 0.6, cx + dc / 2 + gap * 0.6, cy)
    _center_v(prims, cx, cy - dc / 2 - gap * 0.6, cy + dc / 2 + gap * 0.6)
    hx = s / math.sqrt(3.0)
    dim_v(prims, cy - s / 2, cy + s / 2, cx + hx, cx + dc / 2 + gap, f"s {num(s)}", text)
    head_region = (cx - dc / 2 - gap, cy - dc / 2 - gap, cx + dc / 2 + gap * 3.6, cy + dc / 2 + gap)
    return _finish(prims, [side, head_region], (("Вид сбоку", "слева"), ("Вид на головку (под ключ)", "справа")))


def draw_cap_screw(dims, length):
    return draw_screw(dims, length, "cap")


def draw_csk_screw(dims, length):
    return draw_screw(dims, length, "csk")


def draw_button_screw(dims, length):
    return draw_screw(dims, length, "button")


def draw_flange_screw(dims, length):
    return draw_screw(dims, length, "flange")


def _arc_points(cx: float, cy: float, r: float, a0: float, a1: float, steps: int = 48) -> list[tuple[float, float]]:
    return [(cx + r * math.cos(a0 + (a1 - a0) * i / steps), cy + r * math.sin(a0 + (a1 - a0) * i / steps))
            for i in range(steps + 1)]


def draw_spring_washer(dims: Mapping[str, float], length: float | None = None) -> Drawing:
    """Пружинная шайба: вид сбоку (кольцо) и вид сверху с разрывом справа."""
    d1, b, s = dims["d1"], dims["b"], dims["s"]
    d2 = d1 + 2 * b
    r_in, r_out, gap_w = d1 / 2, d2 / 2, s            # ширина разрыва условно s
    gap = 0.18 * d2
    text = 0.03 * d2 + 0.3
    prims: list = []
    for sign in (-1, 1):
        prims += _poly([(sign * r_in, 0), (sign * r_out, 0), (sign * r_out, -s), (sign * r_in, -s)])
    prims += [Line(-r_in, 0, r_in, 0, THIN), Line(-r_in, -s, r_in, -s, THIN)]
    _center_v(prims, 0, gap * 0.5, -s - gap * 0.5)
    dim_h(prims, -r_out, r_out, 0, gap, f"d2 {num(d2)}", text)
    dim_h(prims, -r_in, r_in, -s, -s - gap, f"d1 {num(d1)}", text)
    dim_v(prims, -s, 0, r_out, r_out + gap, f"s {num(s)}", text)
    side = (-r_out - gap * 0.6, -s - gap * 1.8, r_out + gap * 2.8, gap * 1.8)
    cx = side[2] + gap + r_out
    cy = -s / 2
    half = gap_w / 2
    for r in (r_out, r_in):                           # окружности с разрывом справа
        a = math.asin(half / r)
        prims += _poly([(cx + x, cy + y) for x, y in _arc_points(0, 0, r, a, 2 * math.pi - a)], close=False)
    for z in (half, -half):                           # торцы разрыва
        prims.append(Line(cx + math.sqrt(r_in ** 2 - half ** 2), cy + z, cx + math.sqrt(r_out ** 2 - half ** 2), cy + z))
    _center_h(prims, cx - r_out - gap * 0.5, cx + r_out + gap * 0.5, cy)
    _center_v(prims, cx, cy - r_out - gap * 0.5, cy + r_out + gap * 0.5)
    dim_v(prims, cy - half, cy + half, cx + r_out, cx + r_out + gap * 0.9, f"разрыв {num(gap_w)}", text)
    top = (cx - r_out - gap * 0.6, cy - r_out - gap * 0.6, cx + r_out + gap * 3.4, cy + r_out + gap * 0.6)
    return _finish(prims, [side, top], (("Разрез по оси", "слева"), ("Вид сверху (разрыв условный)", "справа")))


def draw_washer(dims: Mapping[str, float], length: float | None = None) -> Drawing:
    d1, d2, h = dims["d1"], dims["d2"], dims["h"]
    gap = 0.18 * d2
    text = 0.03 * d2 + 0.3
    prims: list = []
    # вид сбоку (разрез по оси): два прямоугольника стенок
    for sign in (-1, 1):
        x_in, x_out = sign * d1 / 2, sign * d2 / 2
        prims += _poly([(x_in, 0), (x_out, 0), (x_out, -h), (x_in, -h)])
    prims += [Line(-d1 / 2, 0, d1 / 2, 0, THIN), Line(-d1 / 2, -h, d1 / 2, -h, THIN)]
    _center_v(prims, 0, gap * 0.5, -h - gap * 0.5)
    dim_h(prims, -d2 / 2, d2 / 2, 0, gap, f"d2 {num(d2)}", text)
    dim_h(prims, -d1 / 2, d1 / 2, -h, -h - gap, f"d1 {num(d1)}", text)
    dim_v(prims, -h, 0, d2 / 2, d2 / 2 + gap, f"h {num(h)}", text)
    side = (-d2 / 2 - gap * 0.6, -h - gap * 1.8, d2 / 2 + gap * 2.8, gap * 1.8)
    # вид сверху
    cx = side[2] + gap + d2 / 2
    cy = -h / 2
    prims += [Circle(cx, cy, d2 / 2), Circle(cx, cy, d1 / 2)]
    _center_h(prims, cx - d2 / 2 - gap * 0.5, cx + d2 / 2 + gap * 0.5, cy)
    _center_v(prims, cx, cy - d2 / 2 - gap * 0.5, cy + d2 / 2 + gap * 0.5)
    top = (cx - d2 / 2 - gap * 0.6, cy - d2 / 2 - gap * 0.6, cx + d2 / 2 + gap * 0.6, cy + d2 / 2 + gap * 0.6)
    return _finish(prims, [side, top], (("Разрез по оси", "слева"), ("Вид сверху", "справа")))


def draw_nut_hex(dims: Mapping[str, float], length: float | None = None) -> Drawing:
    d, p, s, m, dw = (dims[x] for x in ("d", "P", "s", "m", "dw"))
    bore = d - 1.082532 * p
    corner = s / math.sqrt(3.0)
    gap = 0.2 * s
    text = 0.035 * s + 0.3
    prims: list = []
    tan30 = math.tan(math.radians(30))
    drop = (s / 2 - dw / 2) * tan30
    half = m / 2
    # вид сбоку: контур со скосами фаски по краям, отверстие и резьба
    prims += _poly([(-dw / 2, half), (dw / 2, half), (s / 2, half - drop), (s / 2, -half + drop), (dw / 2, -half),
                    (-dw / 2, -half), (-s / 2, -half + drop), (-s / 2, half - drop)])
    prims += [Line(-bore / 2, half, -bore / 2, -half, HIDDEN), Line(bore / 2, half, bore / 2, -half, HIDDEN),
              Line(-d / 2, half, -d / 2, -half, HIDDEN), Line(d / 2, half, d / 2, -half, HIDDEN)]
    _center_v(prims, 0, half + gap * 0.6, -half - gap * 0.6)
    dim_h(prims, -s / 2, s / 2, half, half + gap, f"s {num(s)}", text)
    dim_v(prims, -half, half, s / 2, s / 2 + gap, f"m {num(m)}", text)
    dim_h(prims, -d / 2, d / 2, -half, -half - gap, f"d {num(d)}", text)
    side = (-s / 2 - gap * 0.6, -half - gap * 1.8, s / 2 + gap * 2.8, half + gap * 1.8)
    # вид сверху
    cx = side[2] + gap + corner
    cy = 0.0
    prims += _hexagon(cx, cy, s)
    prims += [Circle(cx, cy, dw / 2, THIN), Circle(cx, cy, bore / 2), Circle(cx, cy, d / 2, THIN)]
    _center_h(prims, cx - corner - gap * 0.6, cx + corner + gap * 0.6, cy)
    _center_v(prims, cx, cy - corner - gap * 0.6, cy + corner + gap * 0.6)
    top = (cx - corner - gap * 0.6, cy - corner - gap * 0.6, cx + corner + gap * 0.6, cy + corner + gap * 0.6)
    return _finish(prims, [side, top], (("Вид сбоку", "слева"), ("Вид сверху", "справа")))


def draw_hex_bolt(dims: Mapping[str, float], length: float | None = None) -> Drawing:
    """Болт с шестигранной головкой: вид сбоку (головка с фаской, резьба) и вид сверху."""
    from .shapes import hex_bolt_thread_length
    d, p, s, k, dw = (dims[x] for x in ("d", "P", "s", "k", "dw"))
    length = float(length)
    b = hex_bolt_thread_length(dims, length)
    corner = s / math.sqrt(3.0)
    big = max(s, length)
    gap = 0.07 * big
    text = 0.012 * big + 0.5
    prims: list = []
    drop = (corner - dw / 2) * math.tan(math.radians(30))     # срез фаски у угла шестигранника
    tip = -k - length
    prims += _poly([(-dw / 2, 0.0), (dw / 2, 0.0), (s / 2, -drop), (s / 2, -k), (d / 2, -k), (d / 2, tip + p),
                    (d / 2 - p, tip), (-d / 2 + p, tip), (-d / 2, tip + p), (-d / 2, -k), (-s / 2, -k), (-s / 2, -drop)])
    minor = d - 1.082532 * p
    full = b is None
    y_end = tip + (length if full else b)
    y_top = min(y_end, -k)
    prims += [Line(-minor / 2, tip, -minor / 2, y_top, THIN), Line(minor / 2, tip, minor / 2, y_top, THIN)]
    if not full:
        prims.append(Line(-d / 2, y_end, d / 2, y_end, OUTLINE))
    _center_v(prims, 0, gap * 0.6, tip - gap * 0.6)
    dim_h(prims, -s / 2, s / 2, 0.0, gap, f"s {num(s)}", text)
    dim_v(prims, -k, 0.0, s / 2, s / 2 + gap, f"k {num(k)}", text)
    dim_v(prims, tip, -k, -s / 2, -s / 2 - gap, f"l {num(length)}", text)
    if not full:
        dim_v(prims, tip, y_end, d / 2, d / 2 + gap * 1.8, f"b {num(b)}", text)
    dim_h(prims, -d / 2, d / 2, tip, tip - gap, f"d {num(d)}", text)
    side = (-s / 2 - gap * 2.6, tip - gap * 2.0, s / 2 + gap * 3.6, gap * 1.8)
    cx = side[2] + gap * 1.2 + corner + gap
    cy = -k / 2
    prims += _hexagon(cx, cy, s)
    prims += [Circle(cx, cy, dw / 2, THIN), Circle(cx, cy, d / 2, HIDDEN)]
    _center_h(prims, cx - corner - gap * 0.6, cx + corner + gap * 0.6, cy)
    _center_v(prims, cx, cy - corner - gap * 0.6, cy + corner + gap * 0.6)
    dim_v(prims, cy - s / 2, cy + s / 2, cx + corner, cx + corner + gap, f"s {num(s)}", text)
    top = (cx - corner - gap, cy - corner - gap, cx + corner + gap * 3.6, cy + corner + gap)
    return _finish(prims, [side, top], (("Вид сбоку", "слева"), ("Вид сверху", "справа")))


def draw_nut_nyloc(dims: Mapping[str, float], length: float | None = None) -> Drawing:
    """Самоконтрящаяся гайка: шестигранник с фаской снизу и цилиндрический буртик сверху."""
    d, p, s, m, h, dw = (dims[x] for x in ("d", "P", "s", "m", "h", "dw"))
    bore = d - 1.082532 * p
    corner = s / math.sqrt(3.0)
    gap = 0.2 * s
    text = 0.035 * s + 0.3
    prims: list = []
    drop = (s / 2 - dw / 2) * math.tan(math.radians(30))
    bottom, hex_top, top = 0.0, m, h
    prims += _poly([(-dw / 2, bottom), (dw / 2, bottom), (s / 2, bottom + drop), (s / 2, hex_top), (dw / 2, hex_top),
                    (dw / 2, top), (-dw / 2, top), (-dw / 2, hex_top), (-s / 2, hex_top), (-s / 2, bottom + drop)])
    prims += [Line(-bore / 2, bottom, -bore / 2, top, HIDDEN), Line(bore / 2, bottom, bore / 2, top, HIDDEN),
              Line(-d / 2, bottom, -d / 2, top, HIDDEN), Line(d / 2, bottom, d / 2, top, HIDDEN)]
    _center_v(prims, 0, top + gap * 0.6, bottom - gap * 0.6)
    dim_h(prims, -s / 2, s / 2, top, top + gap, f"s {num(s)}", text)
    dim_v(prims, bottom, hex_top, s / 2, s / 2 + gap, f"m {num(m)}", text)
    dim_v(prims, bottom, top, -s / 2, -s / 2 - gap, f"h {num(h)}", text)
    dim_h(prims, -d / 2, d / 2, bottom, bottom - gap, f"d {num(d)}", text)
    side = (-s / 2 - gap * 2.6, bottom - gap * 1.8, s / 2 + gap * 2.8, top + gap * 1.8)
    cx = side[2] + gap + corner
    cy = h / 2
    prims += _hexagon(cx, cy, s)
    prims += [Circle(cx, cy, dw / 2), Circle(cx, cy, bore / 2), Circle(cx, cy, d / 2, THIN)]
    _center_h(prims, cx - corner - gap * 0.6, cx + corner + gap * 0.6, cy)
    _center_v(prims, cx, cy - corner - gap * 0.6, cy + corner + gap * 0.6)
    top_view = (cx - corner - gap * 0.6, cy - corner - gap * 0.6, cx + corner + gap * 0.6, cy + corner + gap * 0.6)
    return _finish(prims, [side, top_view], (("Вид сбоку", "слева"), ("Вид сверху", "справа")))


DRAWERS = {"cap_screw": draw_cap_screw, "csk_screw": draw_csk_screw, "button_screw": draw_button_screw, "flange_button_screw": draw_flange_screw,
           "washer_flat": draw_washer, "washer_spring": draw_spring_washer, "nut_hex": draw_nut_hex,
           "hex_bolt": draw_hex_bolt, "nut_nyloc": draw_nut_nyloc}

# расшифровка букв размеров для подсказки в окне (буква, что это, ключ в таблице)
LEGENDS: dict[str, list[tuple[str, str, str]]] = {
    "cap_screw": [("d", "диаметр резьбы", "d"), ("P", "шаг резьбы", "P"), ("dk", "диаметр головки", "dk"),
                  ("k", "высота головки", "k"), ("s", "размер под ключ", "s"),
                  ("t", "глубина под ключ", "t"), ("b", "длина резьбы от конца", "b"),
                  ("l", "длина под головкой", "")],
    "csk_screw": [("d", "диаметр резьбы", "d"), ("P", "шаг резьбы", "P"), ("dk", "диаметр головки", "dk"),
                  ("k", "высота головки", "k"), ("s", "размер под ключ", "s"), ("t", "глубина под ключ", "t"),
                  ("b", "длина резьбы от конца", "b"), ("l", "длина с головкой", "")],
    "button_screw": [("d", "диаметр резьбы", "d"), ("P", "шаг резьбы", "P"), ("dk", "диаметр головки", "dk"),
                     ("k", "высота головки", "k"), ("s", "размер под ключ", "s"), ("t", "глубина под ключ", "t"),
                     ("b", "длина резьбы от конца", "b"), ("l", "длина под головкой", "")],
    "flange_button_screw": [("d", "диаметр резьбы", "d"), ("P", "шаг резьбы", "P"), ("dk", "диаметр купола", "dk"),
                            ("dc", "диаметр фланца", "dc"), ("k", "высота головки", "k"), ("c", "толщина фланца", "c"),
                            ("s", "размер под ключ", "s"), ("t", "глубина под ключ", "t"),
                            ("b", "длина резьбы от конца", "b"), ("l", "длина под головкой", "")],
    "washer_spring": [("d1", "внутренний диаметр", "d1"), ("b", "ширина кольца", "b"), ("s", "толщина (и разрыв)", "s")],
    "washer_flat": [("d1", "внутренний диаметр", "d1"), ("d2", "наружный диаметр", "d2"), ("h", "толщина", "h")],
    "hex_bolt": [("d", "диаметр резьбы", "d"), ("P", "шаг резьбы", "P"), ("s", "размер под ключ", "s"),
                 ("k", "высота головки", "k"), ("dw", "начало фаски (диаметр)", "dw"), ("b", "длина резьбы от конца", "b"),
                 ("l", "длина под головкой", "")],
    "nut_nyloc": [("d", "диаметр резьбы", "d"), ("P", "шаг резьбы", "P"), ("s", "размер под ключ", "s"),
                  ("m", "высота шестигранника", "m"), ("h", "полная высота", "h"), ("dw", "диаметр буртика и фаски", "dw")],
    "nut_hex": [("d", "диаметр резьбы", "d"), ("P", "шаг резьбы", "P"), ("s", "размер под ключ", "s"),
                ("m", "высота гайки", "m"), ("dw", "начало фаски (диаметр)", "dw")],
}


def draw(shape_id: str, dims: Mapping[str, float], length: float | None) -> Drawing:
    if shape_id not in DRAWERS:
        raise KeyError(f"для формы {shape_id} нет чертежа")
    return DRAWERS[shape_id](dims, length)


def legend(shape_id: str, dims: Mapping[str, float], length: float | None) -> list[tuple[str, str, str]]:
    """Строки «буква, смысл, значение» для таблицы рядом с чертежом."""
    rows = []
    for letter, meaning, key in LEGENDS.get(shape_id, []):
        value = length if letter == "l" else dims.get(key)
        rows.append((letter, meaning, "" if value is None else num(value)))
    return rows


# --- вывод: SVG (самопроверка) и Tk ---------------------------------------------------------------------
_SVG_STYLE = {OUTLINE: ("#1B1F27", 1.6, ""), THIN: ("#667085", 0.8, ""), CENTER: ("#667085", 0.6, "10 2 2 2"),
              HIDDEN: ("#667085", 0.8, "4 3"), DIM: ("#2563EB", 0.8, "")}


def to_svg(drawing: Drawing, width_px: int = 760) -> str:
    """Чертёж как SVG-текст (для проверки глазами и для документации)."""
    x0, y0, x1, y1 = drawing.bounds
    margin = 0.04 * max(drawing.width, drawing.height)
    w, h = drawing.width + 2 * margin, drawing.height + 2 * margin
    scale = width_px / w
    sx = lambda x: (x - x0 + margin) * scale
    sy = lambda y: (y1 - y + margin) * scale
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_px}" height="{int(h * scale)}">',
           '<rect width="100%" height="100%" fill="white"/>']
    for pr in drawing.prims:
        if isinstance(pr, Line):
            color, wd, dash = _SVG_STYLE[pr.kind]
            d = f' stroke-dasharray="{dash}"' if dash else ""
            out.append(f'<line x1="{sx(pr.x1):.1f}" y1="{sy(pr.y1):.1f}" x2="{sx(pr.x2):.1f}" y2="{sy(pr.y2):.1f}" '
                       f'stroke="{color}" stroke-width="{wd * 1.5}"{d}/>')
        elif isinstance(pr, Circle):
            color, wd, dash = _SVG_STYLE[pr.kind]
            out.append(f'<circle cx="{sx(pr.cx):.1f}" cy="{sy(pr.cy):.1f}" r="{pr.r * scale:.1f}" fill="none" '
                       f'stroke="{color}" stroke-width="{wd * 1.5}"/>')
        elif isinstance(pr, Arrow):
            a = 0.016 * max(drawing.width, drawing.height)
            nx, ny = -pr.dy, pr.dx
            p1 = (pr.x + pr.dx * a * 1.6 + nx * a * 0.45, pr.y + pr.dy * a * 1.6 + ny * a * 0.45)
            p2 = (pr.x + pr.dx * a * 1.6 - nx * a * 0.45, pr.y + pr.dy * a * 1.6 - ny * a * 0.45)
            pts = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in ((pr.x, pr.y), p1, p2))
            out.append(f'<polygon points="{pts}" fill="#2563EB"/>')
        elif isinstance(pr, Text):
            anchor = {"s": "middle", "n": "middle", "w": "start", "e": "end"}[pr.anchor]
            base = {"s": "baseline", "n": "hanging", "w": "middle", "e": "middle"}[pr.anchor]
            out.append(f'<text x="{sx(pr.x):.1f}" y="{sy(pr.y):.1f}" font-size="14" font-family="Segoe UI, sans-serif" '
                       f'fill="#2563EB" text-anchor="{anchor}" dominant-baseline="{base}">{pr.text}</text>')
    out.append("</svg>")
    return "\n".join(out)


def render_tk(canvas, drawing: Drawing, palette, font, width: int, height: int, dpi_scale: float = 1.0) -> None:
    """Нарисовать чертёж на Canvas с учётом палитры темы; масштаб подбирается под размер холста."""
    canvas.delete("all")
    x0, y0, x1, y1 = drawing.bounds
    margin_px = 26 * dpi_scale        # место под подписи размеров: в пикселях, не в миллиметрах
    scale = max(0.01, min((width - 2 * margin_px) / drawing.width, (height - 2 * margin_px) / drawing.height))
    ox = (width - drawing.width * scale) / 2
    oy = (height - drawing.height * scale) / 2
    sx = lambda x: ox + (x - x0) * scale
    sy = lambda y: oy + (y1 - y) * scale
    style = {OUTLINE: (palette.text, 2.0 * dpi_scale, None), THIN: (palette.muted, 1.0 * dpi_scale, None),
             CENTER: (palette.muted, 1.0 * dpi_scale, (10, 3, 2, 3)), HIDDEN: (palette.muted, 1.0 * dpi_scale, (5, 4)),
             DIM: (palette.accent, 1.0 * dpi_scale, None)}
    arrow = 0.016 * max(drawing.width, drawing.height)
    for pr in drawing.prims:
        if isinstance(pr, Line):
            color, wd, dash = style[pr.kind]
            kw = {"dash": dash} if dash else {}
            canvas.create_line(sx(pr.x1), sy(pr.y1), sx(pr.x2), sy(pr.y2), fill=color, width=wd, **kw)
        elif isinstance(pr, Circle):
            color, wd, _ = style[pr.kind]
            r = pr.r * scale
            canvas.create_oval(sx(pr.cx) - r, sy(pr.cy) - r, sx(pr.cx) + r, sy(pr.cy) + r, outline=color, width=wd)
        elif isinstance(pr, Arrow):
            nx, ny = -pr.dy, pr.dx
            a = arrow
            pts = [(pr.x, pr.y),
                   (pr.x + pr.dx * a * 1.6 + nx * a * 0.45, pr.y + pr.dy * a * 1.6 + ny * a * 0.45),
                   (pr.x + pr.dx * a * 1.6 - nx * a * 0.45, pr.y + pr.dy * a * 1.6 - ny * a * 0.45)]
            canvas.create_polygon([c for x, y in pts for c in (sx(x), sy(y))], fill=palette.accent, outline="")
        elif isinstance(pr, Text):
            canvas.create_text(sx(pr.x), sy(pr.y), text=pr.text, anchor=pr.anchor, fill=palette.accent, font=font)
