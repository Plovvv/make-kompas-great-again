"""Мини-растеризатор картинок для темы: скруглённые прямоугольники, круги, галочки. Только стандартная
библиотека (без Pillow): картинки рисуются при запуске под НУЖНЫЙ масштаб экрана, поэтому элементы
темы остаются чёткими при любом DPI.

Каждая фигура задаётся функцией расстояния до границы (SDF), покрытие пикселя получается
сглаживанием по расстоянию: край получается мягким без суперсэмплинга.

    img = Image(40, 40)
    img.rrect(0, 0, 40, 40, radius=10, fill="#FFFFFF", border="#D1D5DB", border_w=1.0)
    data = img.to_base64_png()        # tk.PhotoImage(data=data)
"""

from __future__ import annotations

import base64
import math
import struct
import zlib
from typing import Callable

Color = tuple[float, float, float]   # r, g, b в 0..255


def parse_color(value: str) -> Color:
    v = value.lstrip("#")
    if len(v) == 3:  # краткая запись #RGB
        v = "".join(ch * 2 for ch in v)
    if len(v) != 6:
        raise ValueError(f"ожидался цвет #RRGGBB, получено {value!r}")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def _clamp(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


class Image:
    """RGBA-картинка с обычным (непредумноженным) альфа-каналом."""

    def __init__(self, width: int, height: int):
        if width < 1 or height < 1:
            raise ValueError("размер картинки должен быть положительным")
        self.w, self.h = width, height
        # плоский список: [r, g, b, a] на пиксель, a в 0..1
        self._px = [0.0, 0.0, 0.0, 0.0] * (width * height)

    def flood(self, color: str | Color) -> None:
        """Залить всю картинку непрозрачным цветом (потом поверх рисуется остальное): картинка без прозрачности
        показывается Tk гораздо быстрее, чем картинка с альфа-каналом."""
        r, g, b = parse_color(color) if isinstance(color, str) else color[:3]
        px = self._px
        for i in range(0, len(px), 4):
            px[i], px[i + 1], px[i + 2], px[i + 3] = r, g, b, 1.0

    # --- низкий уровень -------------------------------------------------------------------
    def _over(self, x: int, y: int, color: Color, alpha: float) -> None:
        if alpha <= 0.0:
            return
        i = (y * self.w + x) * 4
        px = self._px
        da = px[i + 3]
        out_a = alpha + da * (1.0 - alpha)
        k = da * (1.0 - alpha)
        px[i] = (color[0] * alpha + px[i] * k) / out_a
        px[i + 1] = (color[1] * alpha + px[i + 1] * k) / out_a
        px[i + 2] = (color[2] * alpha + px[i + 2] * k) / out_a
        px[i + 3] = out_a

    def fill_sdf(self, sdf: Callable[[float, float], float], color: str | Color, alpha: float = 1.0) -> None:
        """Залить фигуру, заданную расстоянием sdf(x, y) (в пикселях; <0 внутри, >0 снаружи)."""
        c = parse_color(color) if isinstance(color, str) else color
        for y in range(self.h):
            for x in range(self.w):
                cov = _clamp(0.5 - sdf(x + 0.5, y + 0.5))
                if cov > 0.0:
                    self._over(x, y, c, alpha * cov)

    # --- фигуры -----------------------------------------------------------------------------
    def rrect(self, x: float, y: float, w: float, h: float, radius: float, fill: str | None,
              border: str | None = None, border_w: float = 0.0) -> None:
        """Скруглённый прямоугольник с заливкой и рамкой (рамка внутри габарита)."""
        radius = max(0.0, min(radius, w / 2.0, h / 2.0))
        if border and border_w > 0:
            self.fill_sdf(_rrect_sdf(x, y, w, h, radius), border)
            inner_r = max(0.0, radius - border_w)
            sdf = _rrect_sdf(x + border_w, y + border_w, w - 2 * border_w, h - 2 * border_w, inner_r)
            if fill:
                self.fill_sdf(sdf, fill)
            else:  # прозрачная середина: вычитаем внутреннюю область
                self._erase_sdf(sdf)
        elif fill:
            self.fill_sdf(_rrect_sdf(x, y, w, h, radius), fill)

    def circle(self, cx: float, cy: float, r: float, fill: str | None, border: str | None = None,
               border_w: float = 0.0) -> None:
        sdf = lambda px, py: math.hypot(px - cx, py - cy) - r  # noqa: E731
        if border and border_w > 0:
            self.fill_sdf(sdf, border)
            inner = lambda px, py: math.hypot(px - cx, py - cy) - (r - border_w)  # noqa: E731
            if fill:
                self.fill_sdf(inner, fill)
            else:
                self._erase_sdf(inner)
        elif fill:
            self.fill_sdf(sdf, fill)

    def polyline(self, points: list[tuple[float, float]], width: float, color: str) -> None:
        """Ломаная с закруглёнными концами (галочка, крестик)."""
        def sdf(px: float, py: float) -> float:
            best = 1e9
            for (ax, ay), (bx, by) in zip(points, points[1:]):
                dx, dy = bx - ax, by - ay
                t = _clamp(((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy or 1.0))
                best = min(best, math.hypot(px - (ax + t * dx), py - (ay + t * dy)))
            return best - width / 2.0
        self.fill_sdf(sdf, color)

    def _erase_sdf(self, sdf: Callable[[float, float], float]) -> None:
        for y in range(self.h):
            for x in range(self.w):
                cov = _clamp(0.5 - sdf(x + 0.5, y + 0.5))
                if cov > 0.0:
                    i = (y * self.w + x) * 4 + 3
                    self._px[i] *= 1.0 - cov

    # --- вывод ----------------------------------------------------------------------------------
    def to_png(self) -> bytes:
        raw = bytearray()
        px = self._px
        for y in range(self.h):
            raw.append(0)  # фильтр строки: нет
            base = y * self.w * 4
            for x in range(self.w):
                i = base + x * 4
                raw += bytes((round(px[i]), round(px[i + 1]), round(px[i + 2]), round(px[i + 3] * 255)))

        def chunk(tag: bytes, data: bytes) -> bytes:
            body = tag + data
            return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

        header = struct.pack(">IIBBBBB", self.w, self.h, 8, 6, 0, 0, 0)
        return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b"")

    def to_base64_png(self) -> str:
        return base64.b64encode(self.to_png()).decode("ascii")

    def stretched(self, border: int, new_w: int, new_h: int) -> "Image":
        """Растянуть картинку «девятью частями»: углы шириной border сохраняются, середина размножается.

        Нужно, чтобы у элементов темы была крупная середина: ttk закрашивает середину ПЛИТКАМИ размером
        с исходную, и картинка с серединой в 2 пикселя на большой карточке даёт сотни тысяч отрисовок
        (секунды на кадр или зависание). Середина исходной картинки должна быть однородной.
        """
        b = border
        if b < 0 or (new_w != self.w and self.w < 2 * b + 1) or (new_h != self.h and self.h < 2 * b + 1):
            raise ValueError("у картинки нет середины для растягивания")
        if new_w < self.w or new_h < self.h:
            raise ValueError("растягивать можно только в большую сторону")
        out = Image(new_w, new_h)
        src, dst = self._px, out._px
        row_len = self.w * 4
        cache: dict[int, list[float]] = {}
        for y in range(new_h):
            sy = y if (y < b or new_h == self.h) else self.h - (new_h - y) if y >= new_h - b else b
            row = cache.get(sy)
            if row is None:
                s_row = src[sy * row_len:(sy + 1) * row_len]
                if new_w == self.w:        # по горизонтали не растягиваем (ползунок вертикальной полосы)
                    row = s_row
                else:
                    row = s_row[:b * 4] + s_row[b * 4:(b + 1) * 4] * (new_w - 2 * b) + s_row[row_len - b * 4:]
                cache[sy] = row
            dst[y * new_w * 4:(y + 1) * new_w * 4] = row
        return out

    def alpha_at(self, x: int, y: int) -> float:
        return self._px[(y * self.w + x) * 4 + 3]

    def rgba_at(self, x: int, y: int) -> tuple[int, int, int, int]:
        i = (y * self.w + x) * 4
        p = self._px
        return round(p[i]), round(p[i + 1]), round(p[i + 2]), round(p[i + 3] * 255)


def _rrect_sdf(x: float, y: float, w: float, h: float, r: float) -> Callable[[float, float], float]:
    cx, cy = x + w / 2.0, y + h / 2.0
    hw, hh = w / 2.0 - r, h / 2.0 - r

    def sdf(px: float, py: float) -> float:
        qx, qy = abs(px - cx) - hw, abs(py - cy) - hh
        return math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - r
    return sdf
