"""Построение 3D-деталей через API7: эскиз, выдавливание, вырез, вращение, свойства, проверка объёма.

Единицы: длины в мм, углы в градусах, масса в граммах, плотность в г/см3 (проверено на КОМПАС-3D v24).
Всё здесь ПРОВЕРЕНО НА ЖИВОМ КОМПАСЕ (tests/test_live_model3d.py): построенные тела сверяются по массе с
расчётом по формуле. Чего тут нет (дуги, фаски, скругления, резьба, массивы), ещё не проверялось:
фаски и скругления требуют выбора рёбер, это следующий шаг.

    with Part.new(kompas) as part:                     # новый скрытый документ-деталь
        with part.sketch("XOY") as sk:                 # эскиз на плоскости XOY
            sk.regular_polygon(6, across_flats=17)     # шестигранник «под ключ» 17
        part.extrude(sk, 8)                            # выдавить на 8 мм вверх
        with part.sketch("XOY") as sk2:
            sk2.circle(0, 0, 5)
        part.cut_extrude(sk2)                          # сквозное отверстие (глубина не задана)
        part.verify_volume(expected_mm3)               # сверка с расчётом, иначе ModelError
        part.save_as(session, path)                    # сохранение только через сессию отката
    # при выходе из with созданный документ закрывается БЕЗ сохранения

Документ создаёт и закрывает мод сам (Kompas.new_document / close_document), документы пользователя
через этот слой не меняются.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Sequence

from . import constants as C
from .kompas import Kompas, KompasError, com_errors

_PLANES = {"XOY": C.o3d_planeXOY, "XOZ": C.o3d_planeXOZ, "YOZ": C.o3d_planeYOZ}
_AXES = {"OX": C.o3d_axisOX, "OY": C.o3d_axisOY, "OZ": C.o3d_axisOZ}
_DIRECTIONS = {"normal": C.dtNormal, "reverse": C.dtReverse, "both": C.dtBoth, "middle": C.dtMiddlePlane}
LINE_MAIN = 1  # стиль «основная линия» (проверено)


class ModelError(KompasError):
    """Операция построения не удалась или результат не совпал с расчётом."""


def _put_indexed(obj, name: str, *args) -> None:
    """Записать индексируемое свойство `Name(args[:-1]) = args[-1]` (например Angle(Normal) = 360).

    При позднем связывании такие свойства пишутся только через IDispatch.Invoke (проверено на v24).
    """
    hook = getattr(obj, "_put_indexed_", None)  # фейковый КОМПАС
    if hook is not None:
        hook(name, *args)
        return
    import pythoncom

    with com_errors(f"запись свойства {name}"):
        ids = obj._oleobj_.GetIDsOfNames(name)
        dispid = ids[0] if isinstance(ids, (tuple, list)) else ids
        obj._oleobj_.Invoke(dispid, 0, pythoncom.DISPATCH_PROPERTYPUT, 0, *args)


class Sketch:
    """Эскиз детали: открывается через `with part.sketch(...)`, закрывается при выходе (даже при ошибке)."""

    def __init__(self, part: "Part", plane: str):
        if plane not in _PLANES:
            raise ModelError(f"плоскость {plane!r}: допустимы {', '.join(_PLANES)}")
        self.part, self.plane = part, plane
        with com_errors("создание эскиза"):
            raw = part.top.Sketchs.Add()
            raw.Plane = part.top.DefaultObject(_PLANES[plane])
            raw.Update()
        self.raw = raw
        self._view = None
        self.shapes = 0

    def __enter__(self) -> "Sketch":
        with com_errors("открытие эскиза"):
            fragment = self.raw.BeginEdit()
            self._view = fragment.ViewsAndLayersManager.Views.ActiveView
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        with com_errors("закрытие эскиза"):
            self.raw.EndEdit()
        self._view = None
        if exc_type is None and self.shapes == 0:
            raise ModelError("эскиз пуст: добавьте контур")
        return False

    def _require_open(self):
        if self._view is None:
            raise ModelError("эскиз не открыт: используйте `with part.sketch(...) as sk:`")
        return self._view

    # --- контуры (все проверены на живом КОМПАСе) -----------------------------------------------
    def circle(self, x: float, y: float, radius: float) -> None:
        if radius <= 0:
            raise ModelError(f"радиус окружности должен быть больше нуля, получено {radius}")
        view = self._require_open()
        with com_errors("окружность в эскизе"):
            c = view.Circles.Add()
            c.Xc, c.Yc, c.Radius, c.Style = float(x), float(y), float(radius), LINE_MAIN
            c.Update()
        self.shapes += 1

    def line(self, x1: float, y1: float, x2: float, y2: float, style: int = LINE_MAIN) -> None:
        if (x1, y1) == (x2, y2):
            raise ModelError("отрезок нулевой длины")
        view = self._require_open()
        with com_errors("отрезок в эскизе"):
            s = view.LineSegments.Add()
            s.X1, s.Y1, s.X2, s.Y2, s.Style = float(x1), float(y1), float(x2), float(y2), style
            s.Update()
        self.shapes += 1

    def polyline(self, points: Sequence[tuple[float, float]], closed: bool = True) -> None:
        """Ломаная из отрезков; closed=True замыкает контур."""
        if len(points) < 2 or (closed and len(points) < 3):
            raise ModelError("в контуре слишком мало точек")
        pairs = list(zip(points, points[1:])) + ([(points[-1], points[0])] if closed else [])
        for (x1, y1), (x2, y2) in pairs:
            self.line(x1, y1, x2, y2)

    def rect(self, x: float, y: float, width: float, height: float) -> None:
        """Прямоугольник: (x, y) левый нижний угол."""
        if width <= 0 or height <= 0:
            raise ModelError("стороны прямоугольника должны быть больше нуля")
        self.polyline([(x, y), (x + width, y), (x + width, y + height), (x, y + height)])

    def regular_polygon(self, sides: int, *, cx: float = 0.0, cy: float = 0.0, circumradius: float | None = None,
                        across_flats: float | None = None, rotation: float = 0.0) -> None:
        """Правильный многоугольник: задайте ровно одно из circumradius (до вершин) или across_flats (под ключ)."""
        if sides < 3:
            raise ModelError("у многоугольника не меньше трёх сторон")
        if (circumradius is None) == (across_flats is None):
            raise ModelError("задайте ровно одно: circumradius или across_flats")
        r = circumradius if circumradius is not None else across_flats / (2 * math.cos(math.pi / sides))
        if r <= 0:
            raise ModelError("размер многоугольника должен быть больше нуля")
        pts = [(cx + r * math.cos(math.radians(rotation + 360.0 * i / sides)),
                cy + r * math.sin(math.radians(rotation + 360.0 * i / sides))) for i in range(sides)]
        self.polyline(pts)


class Part:
    """Деталь (документ-деталь) с простыми операциями построения."""

    def __init__(self, kompas: Kompas, doc, *, owned: bool = True):
        self.kompas, self.doc, self._owned = kompas, doc, owned
        with com_errors("доступ к детали"):
            self.top = doc.TopPart
        self._additive = 0  # сколько добавляющих операций уже есть: первая «основание», дальше «приклеивание»

    @classmethod
    def new(cls, kompas: Kompas, visible: bool = False) -> "Part":
        """Создать НОВЫЙ пустой документ-деталь (по умолчанию скрытый)."""
        return cls(kompas, kompas.new_document(C.ksDocumentPart, visible), owned=True)

    def __enter__(self) -> "Part":
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False

    def close(self) -> None:
        """Закрыть документ БЕЗ сохранения (только документ, созданный этим слоем)."""
        if self._owned and self.doc is not None:
            self.kompas.close_document(self.doc)
            self.doc = None

    # --- построение ---------------------------------------------------------------------------------
    def sketch(self, plane: str = "XOY") -> Sketch:
        return Sketch(self, plane)

    def extrude(self, sketch: Sketch, depth: float, *, direction: str = "normal", depth2: float | None = None) -> None:
        """Добавить материал выдавливанием эскиза. direction относительно нормали плоскости эскиза:

        normal: на depth по нормали; reverse: на depth против нормали; both: depth по нормали и depth2
        (по умолчанию тот же) против; middle: симметрично, depth это ОБЩАЯ толщина.
        """
        if depth is None or depth <= 0:
            raise ModelError(f"глубина выдавливания должна быть больше нуля, получено {depth}")
        kind = C.o3d_baseExtrusion if self._additive == 0 else C.o3d_bossExtrusion
        self._extrusion(kind, sketch, depth, direction, depth2, "выдавливание")
        self._additive += 1

    def cut_extrude(self, sketch: Sketch, depth: float | None = None, *, direction: str = "normal",
                    depth2: float | None = None) -> None:
        """Вырезать выдавливанием. Направления те же, что у extrude (normal: режет ПО нормали плоскости эскиза).

        depth=None: через всё; both с depth=None: через всё в обе стороны.
        """
        if depth is not None and depth <= 0:
            raise ModelError(f"глубина выреза должна быть больше нуля, получено {depth}")
        if self._additive == 0:
            raise ModelError("вырезать пока не из чего: сначала постройте тело")
        self._extrusion(C.o3d_cutExtrusion, sketch, depth, direction, depth2, "вырез", cut=True)

    def _extrusion(self, kind: int, sketch: Sketch, depth, direction: str, depth2, what: str, cut: bool = False) -> None:
        if direction not in _DIRECTIONS:
            raise ModelError(f"направление {direction!r}: допустимы {', '.join(_DIRECTIONS)}")
        end, d = (C.etThroughAll, 0.0) if depth is None else (C.etBlind, float(depth))
        d2 = d if depth2 is None else float(depth2)
        # Для пользователя направления одинаковы у выдавливания и выреза: normal это ПО нормали плоскости
        # эскиза. КОМПАС для вырезов трактует normal/reverse наоборот (проверено на v24), поэтому переворачиваем.
        kompas_dir = direction
        if cut and direction in ("normal", "reverse"):
            kompas_dir = "reverse" if direction == "normal" else "normal"
        # При направлении reverse КОМПАС читает глубину из параметров ОБРАТНОЙ стороны (Normal=False);
        # параметры другой стороны игнорируются (проверено: иначе операция не строится или берёт 10 мм по умолчанию).
        if kompas_dir == "reverse":
            sides = [(False, end, d)]
        elif kompas_dir == "both":
            sides = [(True, end, d), (False, end, 0.0 if depth is None else d2)]
        else:  # normal и middle: толщина в параметрах прямой стороны (для middle это общая толщина)
            sides = [(True, end, d)]
        with com_errors(what):
            ext = self.top.Extrusions.Add(kind)
            ext.Sketch = sketch.raw
            ext.Direction = _DIRECTIONS[kompas_dir]
            for normal_side, end_type, side_depth in sides:
                ext.SetSideParameters(normal_side, end_type, side_depth, 0.0, False, None)
            built = ext.Update()
        if not built:
            raise ModelError(f"КОМПАС не смог построить: {what}")

    def revolve(self, sketch: Sketch, *, axis: str = "OY", angle: float = 360.0, cut: bool = False) -> None:
        """Вращение эскиза (профиля) вокруг оси детали. Профиль должен лежать по одну сторону от оси."""
        if axis not in _AXES:
            raise ModelError(f"ось {axis!r}: допустимы {', '.join(_AXES)}")
        if not 0 < angle <= 360:
            raise ModelError(f"угол вращения от 0 до 360 градусов, получено {angle}")
        if cut and self._additive == 0:
            raise ModelError("вырезать пока не из чего: сначала постройте тело")
        kind = C.o3d_cutRotated if cut else (C.o3d_baseRotated if self._additive == 0 else C.o3d_bossRotated)
        with com_errors("вращение"):
            rot = self.top.Rotateds.Add(kind)
            rot.Profile = sketch.raw
            rot.Axis = self.top.DefaultObject(_AXES[axis])
            rot.Direction = C.dtNormal
            _put_indexed(rot, "RotatedType", True, C.ksRTAngle)
            _put_indexed(rot, "Angle", True, float(angle))
            built = rot.Update()
        if not built:
            raise ModelError("КОМПАС не смог построить: вращение")
        if not cut:
            self._additive += 1

    # --- свойства и измерения ---------------------------------------------------------------------------
    def set_properties(self, *, name: str | None = None, marking: str | None = None,
                       material: str | None = None, density: float | None = None) -> None:
        """Наименование, обозначение, материал. Материал и плотность (г/см3) задаются только вместе."""
        if (material is None) != (density is None):
            raise ModelError("материал и плотность (г/см3) задаются вместе")
        with com_errors("свойства детали"):
            if name is not None:
                self.top.Name = name
            if marking is not None:
                self.top.Marking = marking
            if material is not None and not self.top.SetMaterial(material, float(density)):
                raise ModelError(f"КОМПАС не принял материал {material!r}")

    def update(self) -> None:
        """Пересчитать деталь (возвращаемое значение КОМПАСа не показатель ошибки: после успеха бывает False)."""
        with com_errors("пересчёт детали"):
            self.top.Update()

    @property
    def mass_g(self) -> float:
        self.update()
        with com_errors("чтение массы"):
            return float(self.top.Mass)

    @property
    def density(self) -> float:
        with com_errors("чтение плотности"):
            return float(self.top.Density)

    @property
    def volume_mm3(self) -> float:
        """Объём в мм3 = масса / плотность (в КОМПАСе масса в граммах, плотность в г/см3)."""
        density = self.density
        if density <= 0:
            raise ModelError("плотность материала не положительна: объём по массе не определить")
        return self.mass_g / density * 1000.0

    def verify_volume(self, expected_mm3: float, rel_tol: float = 1e-6) -> float:
        """Сверить объём детали с расчётом. Возвращает измеренный объём; расхождение даёт ModelError."""
        got = self.volume_mm3
        if expected_mm3 <= 0:
            raise ModelError("расчётный объём должен быть положительным")
        err = abs(got - expected_mm3) / expected_mm3
        if err > rel_tol:
            raise ModelError(f"объём {got:.4f} мм³ отличается от расчётного {expected_mm3:.4f} мм³ "
                             f"на {err:.2e} (допуск {rel_tol:.0e})")
        return got

    # --- сохранение ---------------------------------------------------------------------------------------
    def save_as(self, session, path: str | Path) -> None:
        """Сохранить деталь в файл через сессию отката (см. Kompas.save_as)."""
        self.kompas.save_as(session, self.doc, path)
