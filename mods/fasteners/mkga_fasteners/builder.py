"""Создание детали из стандарта: имя, построение, спецификация, сверка объёма, сохранение, открытие.

Единая точка для окна и для тестов. Файлы пользователя меняются только через сессию отката
(`ctx.session`): новая деталь это «создан файл», существующая замена это «изменён файл» со снимком.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mkga.core.model3d import SPEC_OTHER, Part

from .catalog import Standard
from .shapes import ShapeError


class BuildError(RuntimeError):
    """Деталь создать не удалось (текст понятен пользователю)."""


@dataclass(frozen=True)
class Request:
    standard: Standard
    size: str
    length: float | None
    folder: Path
    strength: str | None = None
    open_after: bool = True
    overwrite: bool = False      # разрешено ли заменить существующий файл (со снимком для отката)


@dataclass(frozen=True)
class Plan:
    """Что будет сделано: имена, путь, существует ли файл."""

    file_stem: str
    title: str
    path: Path
    exists: bool
    section: str


@dataclass(frozen=True)
class Result:
    path: Path
    title: str
    volume_mm3: float
    expected_mm3: float
    opened: bool


def plan(req: Request) -> Plan:
    """Проверить запрос и рассчитать имена и путь (без КОМПАСа и без записи)."""
    std = req.standard
    if req.size not in std.sizes:
        raise BuildError(f"в {std.number} нет типоразмера {req.size}")
    length = req.length
    if std.has_length:
        if length is None:
            raise BuildError("выберите длину")
        if length not in std.lengths_for(req.size):
            raise BuildError(f"длина {length:g} мм недопустима для {req.size} по {std.number}")
    else:
        length = None
    if req.strength and req.strength not in std.classes:
        raise BuildError(f"класс прочности {req.strength} не предусмотрен для {std.number}")
    try:
        std.shape_obj.check(std.dims(req.size), length)
    except ShapeError as e:
        raise BuildError(str(e)) from e
    if not req.folder.is_dir():
        raise BuildError(f"папки нет: {req.folder}")
    names = std.names(req.size, length, req.strength)
    path = req.folder / f"{names.file_stem}.m3d"
    return Plan(names.file_stem, names.title, path, path.exists(), std.section_name)


def create_part(ctx, req: Request) -> Result:
    """Построить деталь в КОМПАС, сверить объём с расчётом и сохранить через сессию отката."""
    p = plan(req)
    if p.exists and not req.overwrite:
        raise BuildError(f"файл уже есть: {p.path.name}. Подтвердите замену (старый вариант сохранится в истории).")
    std = req.standard
    length = req.length if std.has_length else None
    dims = std.dims(req.size)
    shape = std.shape_obj
    expected = shape.volume(dims, length)
    kompas = ctx.kompas()
    with Part.new(kompas) as part:
        shape.build(part, dims, length)
        part.set_title(p.title)
        if std.section == "standard":
            part.set_object_type("Стандартное изделие")
        else:
            part.add_spec_object(SPEC_OTHER)
        got = part.verify_volume(expected, shape.volume_tol)
        if shape.verify is not None:
            shape.verify(part, dims, length)
        with ctx.session(f"Создать деталь «{p.file_stem}»") as session:
            part.save_as(session, p.path)
    opened = False
    if req.open_after:
        kompas.open_document(p.path, visible=True)
        opened = True
    return Result(p.path, p.title, got, expected, opened)
