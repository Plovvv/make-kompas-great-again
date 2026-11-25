"""Иконка приложения: рисуется растеризатором (без внешних файлов), для окон Tk и для exe (.ico).

Знак: синий скруглённый квадрат с белой шестигранной гайкой (метизы и детали, то, чем занимаются моды).

    python -m mkga.ui.icon build/mkga.ico      # записать .ico (используется при сборке exe)
"""

from __future__ import annotations

import math
import struct
import sys
from pathlib import Path

from . import raster
from .theme import LIGHT

ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def draw_icon(size: int) -> raster.Image:
    """Иконка размера size x size пикселей (прозрачные углы, антиалиасинг)."""
    accent, white = LIGHT.accent, "#FFFFFF"
    img = raster.Image(size, size)
    img.rrect(0, 0, size, size, size * 0.22, accent)
    c = size / 2.0
    r = size * 0.31                                   # радиус описанной окружности гайки
    stroke = max(1.2, size * 0.085)
    hexagon = [(c + r * math.cos(math.radians(60 * i + 30)), c + r * math.sin(math.radians(60 * i + 30)))
               for i in range(6)]
    img.polyline(hexagon + [hexagon[0]], stroke, white)
    hole, ring = size * 0.13, max(1.0, size * 0.06)
    img.circle(c, c, hole, white)                     # кольцо отверстия: белый круг и синяя середина поверх
    img.circle(c, c, max(0.5, hole - ring), accent)
    return img


def png_bytes(size: int) -> bytes:
    return draw_icon(size).to_png()


def ico_bytes(sizes: tuple[int, ...] = ICO_SIZES) -> bytes:
    """Файл .ico с PNG-изображениями нужных размеров (поддерживается Windows Vista и новее)."""
    blobs = [png_bytes(s) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = b""
    for s, blob in zip(sizes, blobs):
        entries += struct.pack("<BBBBHHII", 0 if s >= 256 else s, 0 if s >= 256 else s, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    return header + entries + b"".join(blobs)


def write_ico(path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(ico_bytes())
    return path


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("mkga.ico")
    print(write_ico(target))
