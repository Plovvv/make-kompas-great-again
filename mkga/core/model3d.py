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

from . import com_iface
from . import constants as C
from .kompas import Kompas, KompasError, com_errors

_PLANES = {"XOY": C.o3d_planeXOY, "XOZ": C.o3d_planeXOZ, "YOZ": C.o3d_planeYOZ}
_AXES = {"OX": C.o3d_axisOX, "OY": C.o3d_axisOY, "OZ": C.o3d_axisOZ}
_DIRECTIONS = {"normal": C.dtNormal, "reverse": C.dtReverse, "both": C.dtBoth, "middle": C.dtMiddlePlane}
LINE_MAIN = 1  # стиль «основная линия» (проверено)
PROP_TITLE = 5          # свойство документа «Наименование»
PROP_OBJECT_TYPE = 14   # свойство документа «Тип объекта» (Деталь, Стандартное изделие, ...)
SPEC_STYLE_DEFAULT = 1  # стиль спецификации по умолчанию (проверено на v24)
SPEC_STANDARD, SPEC_OTHER = 25, 30   # номера разделов стиля спецификации: «Стандартные изделия», «Прочие изделия»


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

    def arc(self, cx: float, cy: float, radius: float, start_deg: float, end_deg: float) -> None:
        """Дуга окружности: центр (cx, cy), радиус, углы в градусах от оси X; идёт ПРОТИВ часовой стрелки от start к end."""
        if radius <= 0:
            raise ModelError(f"радиус дуги должен быть больше нуля, получено {radius}")
        if start_deg == end_deg:
            raise ModelError("у дуги совпадают начальный и конечный углы")
        view = self._require_open()
        with com_errors("дуга в эскизе"):
            a = view.Arcs.Add()
            a.Xc, a.Yc, a.Radius = float(cx), float(cy), float(radius)
            a.Angle1, a.Angle2, a.Direction, a.Style = float(start_deg), float(end_deg), False, LINE_MAIN   # Direction=False идёт против часовой (проверено)
            a.Update()
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

    # --- свойства документа, раздел спецификации (проверено на v24, см. docs/MODEL3D.md) -----------------------
    def _doc_property(self, prop_id: int, value: str) -> None:
        """Записать свойство документа по номеру через менеджер свойств КОМПАСа (IPropertyMng + IPropertyKeeper)."""
        with com_errors("свойства документа"):
            props = com_iface.get(self.kompas.app7, "IPropertyMng", "GetProperties", self.doc)
        found = next((p for p in props if int(p.Id) == prop_id), None)
        if found is None:
            raise ModelError(f"в КОМПАСе нет свойства документа № {prop_id}")
        if not com_iface.call(self.doc, "IPropertyKeeper", "SetPropertyValue", found, value, True):
            raise ModelError(f"КОМПАС не принял значение свойства № {prop_id}: {value!r}")

    def set_title(self, text: str) -> None:
        """Наименование детали (свойство «Наименование» № 5) и имя детали в дереве модели."""
        self._doc_property(PROP_TITLE, text)
        with com_errors("имя детали"):
            self.top.Name = text

    def set_object_type(self, text: str = "Стандартное изделие") -> None:
        """Свойство «Тип объекта» № 14: «Стандартное изделие» отправляет деталь в раздел спецификации «Стандартные изделия».

        Допустимые значения даёт КОМПАС (Деталь, Сборочная единица, Стандартное изделие, ...). Проверено на v24:
        значение записывается и сохраняется в файле.
        """
        self._doc_property(PROP_OBJECT_TYPE, text)

    def add_spec_object(self, section: int) -> None:
        """Объект спецификации детали в раздел `section` (25 «Стандартные изделия», 30 «Прочие изделия», 20 «Детали», ...).

        ЭТО И ЕСТЬ способ задать раздел: проверено на v24, что деталь с таким объектом попадает в спецификации СБОРКИ в
        указанный раздел. Номера разделов берутся из стиля спецификации (`SpecificationStyle.Sections`: Документация 5,
        Комплексы 10, Сборочные единицы 15, Детали 20, Стандартные изделия 25, Прочие изделия 30, Материалы 35,
        Комплекты 40). Тип объекта («Стандартное изделие») и свойство SPCSection раздел в сборке НЕ определяют.
        """
        with com_errors("объект спецификации"):
            description = self.doc.SpecificationDescriptions.Add("", SPEC_STYLE_DEFAULT, "")
            obj = description.BaseObjects.Add(int(section), 1.0)
            obj.IncludeGeometry(self.top, True)
            obj.Update()

    def set_spec_section_property(self, section: int, subsection: int = 0) -> None:
        """Записать свойство документа SPCSection (раздел и подраздел) в хранилище свойств детали.

        Так хранит раздел сам КОМПАС; свойство становится «сложным» (`IsComplexPropertyValue`) и остаётся в файле
        (проверено на v24). На раздел в спецификации сборки оно не влияет: для этого нужен `add_spec_object`.
        """
        import re

        with com_errors("свойство SPCSection"):
            xml = com_iface.get(self.doc, "IPropertyKeeper", "Properties")
            xml = re.sub(r'\s*<property id="SPCSection"[^>]*?(?:/>|>.*?</property>)', "", xml, flags=re.S)
            entry = ('\t<property id="SPCSection" value="%d" type="int">\n\t\t<property id="subSectionNumb" value="%d" '
                     'type="int" />\n\t</property>\n') % (int(section), int(subsection))
            com_iface.put(self.doc, "IPropertyKeeper", "Properties", xml.replace("</infObject>", entry + "</infObject>"))

    def set_spec_section(self, section: int) -> None:
        """Раздел спецификации детали: объект спецификации (определяет раздел в сборке) и свойство SPCSection (в свойствах)."""
        self.add_spec_object(section)
        self.set_spec_section_property(section)

    # --- грани и резьба ---------------------------------------------------------------------------------
    def faces(self) -> list:
        """Все грани детали (IFace). Проверено на v24."""
        with com_errors("грани детали"):
            raw = com_iface.get(self.top, "IFeature7", "ModelObjects", C.o3d_face)
        return list(raw or ())

    def cylinder_faces(self, radius: float | None = None, tol: float = 1e-6) -> list:
        """Цилиндрические грани (опционально только заданного радиуса, мм)."""
        found = []
        with com_errors("поиск цилиндров"):
            for f in self.faces():
                if f.IsCylinder and (radius is None or abs(float(f.Radius) - radius) <= tol):
                    found.append(f)
        return found

    def planar_area_mm2(self) -> float:
        """Суммарная площадь плоских граней (мм2): точная проверка геометрии там, где расчёт массы КОМПАС неточен.

        Проверено на v24: площади плоских граней совпадают с расчётом до 1e-5, в отличие от массы тел с коническими
        фасками на шестиграннике (погрешность около 1 %).
        """
        total = 0.0
        with com_errors("площадь граней"):
            for f in self.faces():
                if f.IsPlanar:
                    total += float(f.GetArea(C.ksLUnMM))
        return total

    def verify_planar_area(self, expected_mm2: float, rel_tol: float = 1e-6) -> float:
        got = self.planar_area_mm2()
        err = abs(got - expected_mm2) / expected_mm2
        if err > rel_tol:
            raise ModelError(f"площадь плоских граней {got:.4f} мм² отличается от расчётной {expected_mm2:.4f} мм² "
                             f"на {err:.2e} (допуск {rel_tol:.0e})")
        return got

    def thread_all(self, radius: float) -> int:
        """Условное изображение резьбы на КАЖДОЙ цилиндрической грани данного радиуса (например два глухих отверстия)."""
        count = len(self.cylinder_faces(radius))
        for i in range(count):
            self.thread(radius, face_index=i)
        return count

    def thread(self, radius: float, length: float | None = None, *,
               start_near: tuple[float, float, float] | None = None,
               face_index: int = 0) -> tuple[float, float, float, float, float, float]:
        """Условное изображение резьбы на цилиндре радиуса `radius` (мм): тонкая окружность на виде, объём не меняется.

        length=None: на всю длину цилиндра. Иначе резьба длиной `length` отсчитывается от торцевой кромки цилиндра,
        ближайшей к точке `start_near` (x, y, z): по умолчанию КОМПАС начинает от кромки, которая ему «первая»
        (у винта это головка), а нужно от конца. Возвращаются крайние точки резьбы (x1, y1, z1, x2, y2, z2).
        Проверено на v24: резьба от кромки конца винта идёт от самого конца (с фаской), объём детали не меняется.
        """
        faces = self.cylinder_faces(radius)
        if not faces:
            raise ModelError(f"нет цилиндрической поверхности радиуса {radius:g} мм для резьбы")
        face = faces[min(face_index, len(faces) - 1)]
        border = self._nearest_edge(face, start_near) if start_near is not None else None
        with com_errors("условное изображение резьбы"):
            t = self.top.Threads.Add()
            t.BaseObject = face
            t.AutoDiameter = True
            if length is None:
                t.AutoLenght = True
            else:
                t.AutoLenght = False
                t.Lenght = float(length)
            if border is not None:
                t.InitialBorder = border
            built = t.Update()
        if not built:
            raise ModelError("КОМПАС не смог построить условное изображение резьбы")
        outs = com_iface.out_doubles(6)
        if not com_iface.invoke_with_outs(t, "GetLimitPoints", *outs):
            raise ModelError("КОМПАС не сообщил границы резьбы")
        return tuple(round(float(o.value), 6) for o in outs)

    @staticmethod
    def _nearest_edge(face, point: tuple[float, float, float]):
        """Ограничивающее ребро грани, начальная точка которого ближе всего к `point`."""
        best, best_dist = None, math.inf
        with com_errors("рёбра грани"):
            for edge in face.LimitingEdges or ():
                outs = com_iface.out_doubles(3)
                com_iface.invoke_with_outs(edge, "GetPoint", True, *outs)
                dist = math.dist([o.value for o in outs], point)
                if dist < best_dist:
                    best, best_dist = edge, dist
        if best is None:
            raise ModelError("у цилиндрической грани нет рёбер")
        return best

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
