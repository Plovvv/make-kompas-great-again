"""Формы метизов: построение детали в КОМПАС и точный расчёт объёма для сверки.

Каждая форма описывает ОДНУ геометрию (винт с шестигранным углублением, плоская шайба, шестигранная гайка, ...)
и не знает про стандарты: размеры приходят из таблицы стандарта (data/standards/*.json). Поэтому новый стандарт на
уже существующую форму (например DIN 933 на форму шестигранного болта) это только таблица, без кода.

Правила форм:
- Деталь строится вращением профиля вокруг оси OY и выдавливанием шестигранников; верх детали лежит в плоскости
  XOZ (y = 0), всё тело ниже. Так вырезы можно делать с плоскости XOZ в обе стороны (`direction="both"`): выбор
  направления не зависит от того, куда смотрит нормаль плоскости.
- Резьба только как «Условное изображение резьбы» (без реальных витков).
- Каждая форма считает точный объём (`volume`), и построение сверяется с ним (`Part.verify_volume`).
  Фаски, радиусы и конус на дне углубления: см. комментарии у форм (что упрощено).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

Point = tuple[float, float]
TAN30 = math.tan(math.radians(30.0))


class ShapeError(ValueError):
    """Недопустимые размеры или длина (текст понятен пользователю)."""


# --- математика --------------------------------------------------------------------------------------
def revolved_volume(points: Sequence[Point]) -> float:
    """Объём тела вращения многоугольника (x >= 0, ось Y) по теореме Паппа: V = 2π · x_ц · S."""
    n = len(points)
    area2 = 0.0   # удвоенная площадь
    moment6 = 0.0  # 6 · S · x_ц
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        cross = x1 * y2 - x2 * y1
        area2 += cross
        moment6 += (x1 + x2) * cross
    return abs(2.0 * math.pi * moment6 / 6.0)


def hexagon_area(across_flats: float) -> float:
    return math.sqrt(3.0) / 2.0 * across_flats ** 2


def hex_chamfer_volume(across_flats: float, chamfer_dia: float, angle_deg: float = 30.0) -> float:
    """Объём, срезаемый с ОДНОГО торца шестигранной призмы конической фаской.

    Фаска начинается на диаметре `chamfer_dia` и идёт под углом `angle_deg` к торцу. Высота среза на радиусе ρ
    равна (ρ − r0)·tg(angle). Считается интегралом по сектору шестигранника (12 одинаковых секторов), метод Симпсона.
    """
    r0 = chamfer_dia / 2.0
    half_flat = across_flats / 2.0
    tan_a = math.tan(math.radians(angle_deg))
    n = 4000  # чётное

    def inner(phi: float) -> float:
        big_r = half_flat / math.cos(phi)
        if big_r <= r0:
            return 0.0
        return (big_r ** 3 / 3.0 - r0 * big_r ** 2 / 2.0) - (r0 ** 3 / 3.0 - r0 * r0 ** 2 / 2.0)

    h = (math.pi / 6.0) / n
    total = inner(0.0) + inner(math.pi / 6.0)
    for i in range(1, n):
        total += (4 if i % 2 else 2) * inner(i * h)
    sector = total * h / 3.0
    return 12.0 * tan_a * sector


def internal_minor_diameter(d: float, pitch: float) -> float:
    """Диаметр отверстия под метрическую резьбу D1 = d − 1,0825·P (геометрия профиля ISO 724)."""
    return d - 1.082532 * pitch


# --- общие вещи для форм -----------------------------------------------------------------------------
def _need(dims: Mapping[str, float], names: Sequence[str], what: str) -> None:
    missing = [n for n in names if dims.get(n) is None]
    if missing:
        raise ShapeError(f"{what}: в таблице нет размеров {', '.join(missing)}")


def _positive(dims: Mapping[str, float], names: Sequence[str]) -> None:
    for n in names:
        if not dims[n] > 0:
            raise ShapeError(f"размер {n} должен быть больше нуля, получено {dims[n]}")


def _revolve_profile(part, points: Sequence[Point], *, cut: bool = False) -> None:
    with part.sketch("XOY") as sk:
        sk.polyline(list(points))
    part.revolve(sk, axis="OY", cut=cut)


@dataclass(frozen=True)
class Shape:
    """Описание формы: какие размеры нужны, нужна ли длина, как строить и как считать объём."""

    id: str
    title: str
    required: tuple[str, ...]
    has_length: bool
    threaded: str  # "external" | "internal" | ""
    check: Callable[[Mapping[str, float], float | None], None]
    volume: Callable[[Mapping[str, float], float | None], float]
    build: Callable[[object, Mapping[str, float], float | None], None]
    # Допуск сверки объёма с расчётом. Обычно 1e-6. У форм с конической фаской на шестиграннике 3e-2: встроенный расчёт
    # массы КОМПАС на гиперболических кромках даёт погрешность до 1,3 % (проверено: площади плоских граней при этом
    # совпадают с расчётом до 1e-5, то есть геометрия верна, неточен именно расчёт массы). Точность таких форм держит
    # `verify` (площадь плоских граней), объём остаётся грубой проверкой «фаски вообще есть».
    volume_tol: float = 1e-6
    # Дополнительная точная проверка построенной детали (например площади плоских граней); бросает ModelError.
    verify: Callable[[object, Mapping[str, float], float | None], None] | None = None


# --- винт с цилиндрической головкой и шестигранным углублением (DIN 912, ISO 4762) -------------------------
def _cap_screw_profile(dims: Mapping[str, float], length: float) -> list[Point]:
    d, p, dk, k = dims["d"], dims["P"], dims["dk"], dims["k"]
    c = min(0.06 * dk, k / 3.0)          # фаска верха головки (в стандарте скругление/фаска без размера)
    return [(0.0, 0.0), (dk / 2 - c, 0.0), (dk / 2, -c), (dk / 2, -k), (d / 2, -k),
            (d / 2, -(k + length - p)), (d / 2 - p, -(k + length)), (0.0, -(k + length))]


def _cap_screw_check(dims, length):
    _need(dims, ("d", "P", "dk", "k", "s", "t"), "винт")
    _positive(dims, ("d", "P", "dk", "k", "s", "t"))
    if length is None or length <= dims["P"]:
        raise ShapeError("длина винта должна быть больше шага резьбы")
    if dims["s"] / math.cos(math.radians(30)) >= dims["dk"]:
        raise ShapeError("шестигранное углубление не помещается в головку")
    if dims["t"] >= dims["k"]:
        raise ShapeError("глубина углубления должна быть меньше высоты головки")


def _cap_screw_volume(dims, length):
    # Упрощение: углубление плоское на глубину t (в стандарте внизу конус сверла), t это минимальная глубина.
    return revolved_volume(_cap_screw_profile(dims, length)) - hexagon_area(dims["s"]) * dims["t"]


def _cap_screw_build(part, dims, length):
    _revolve_profile(part, _cap_screw_profile(dims, length))
    with part.sketch("XOZ") as sk:
        sk.regular_polygon(6, across_flats=dims["s"])
    part.cut_extrude(sk, dims["t"], direction="both")      # режет в тело, откуда бы ни смотрела нормаль
    thread_len = dims.get("b")
    tip = (dims["d"] / 2, -(dims["k"] + length - dims["P"]), 0.0)    # кромка стержня со стороны конца
    # Длина резьбы b отсчитывается от самого конца винта (с фаской); если b >= l, резьба на всю длину.
    part.thread(dims["d"] / 2, None if thread_len is None or thread_len >= length else thread_len, start_near=tip)


# --- шайба плоская (DIN 125, ISO 7089) -----------------------------------------------------------------------
def _washer_profile(dims):
    r1, r2, h = dims["d1"] / 2, dims["d2"] / 2, dims["h"]
    return [(r1, 0.0), (r2, 0.0), (r2, -h), (r1, -h)]


def _washer_check(dims, length):
    _need(dims, ("d1", "d2", "h"), "шайба")
    _positive(dims, ("d1", "d2", "h"))
    if dims["d2"] <= dims["d1"]:
        raise ShapeError("наружный диаметр шайбы должен быть больше внутреннего")


def _washer_volume(dims, length):
    return revolved_volume(_washer_profile(dims))


def _washer_build(part, dims, length):
    _revolve_profile(part, _washer_profile(dims))


# --- гайка шестигранная (DIN 934, ISO 4032) -----------------------------------------------------------------------
def _nut_check(dims, length):
    _need(dims, ("d", "P", "s", "m", "dw"), "гайка")
    _positive(dims, ("d", "P", "s", "m", "dw"))
    bore = internal_minor_diameter(dims["d"], dims["P"])
    if bore >= dims["dw"] or dims["dw"] > dims["s"]:
        raise ShapeError("размеры фаски гайки не согласованы")
    corner_cut = (dims["s"] / math.cos(math.radians(30)) / 2 - dims["dw"] / 2) * TAN30
    if corner_cut * 2 >= dims["m"]:
        raise ShapeError("фаски гайки срезают её по всей высоте")


def hex_flat_notch_area(across_flats: float, chamfer_dia: float, angle_deg: float = 30.0) -> float:
    """Площадь выемки на ОДНОЙ грани шестигранника от конической фаски на ОДНОМ торце (гипербола на плоскости)."""
    a = across_flats / 2.0                      # расстояние от оси до плоскости грани
    side = across_flats / math.sqrt(3.0)        # длина грани
    r0 = chamfer_dia / 2.0
    tan_a = math.tan(math.radians(angle_deg))

    def prim(u: float) -> float:                # первообразная sqrt(a^2 + u^2)
        return 0.5 * (u * math.hypot(a, u) + a * a * math.asinh(u / a))

    half = side / 2.0
    return tan_a * (prim(half) - prim(-half) - r0 * side)


def _nut_planar_area(dims) -> float:
    """Расчётная суммарная площадь плоских граней гайки: два торца-круга с отверстием и шесть граней с выемками."""
    s, m, dw = dims["s"], dims["m"], dims["dw"]
    rc = dw / 2.0
    rb = internal_minor_diameter(dims["d"], dims["P"]) / 2.0
    side = s / math.sqrt(3.0)
    flat = side * m - 2.0 * hex_flat_notch_area(s, dw)
    return 2.0 * math.pi * (rc ** 2 - rb ** 2) + 6.0 * flat


def _nut_verify(part, dims, length):
    part.verify_planar_area(_nut_planar_area(dims), 1e-4)   # КОМПАС считает площади с точностью около 1e-6


def _nut_volume(dims, length):
    bore = internal_minor_diameter(dims["d"], dims["P"])
    prism = hexagon_area(dims["s"]) * dims["m"]
    hole = math.pi * (bore / 2.0) ** 2 * dims["m"]
    return prism - hole - 2.0 * hex_chamfer_volume(dims["s"], dims["dw"], 30.0)


def _nut_build(part, dims, length):
    m, s = dims["m"], dims["s"]
    bore = internal_minor_diameter(dims["d"], dims["P"])
    with part.sketch("XOZ") as sk:
        sk.regular_polygon(6, across_flats=s)
    part.extrude(sk, m, direction="middle")                  # симметрично относительно плоскости XOZ
    with part.sketch("XOZ") as hole:
        hole.circle(0, 0, bore / 2.0)
    part.cut_extrude(hole, direction="both")                 # сквозное отверстие
    rc = dims["dw"] / 2.0
    big = s / math.cos(math.radians(30)) / 2.0 + 1.0         # заведомо за углами шестигранника
    for sign in (1.0, -1.0):                                 # фаска 30° на обоих торцах
        face_y = sign * m / 2.0
        depth = (big - rc) * TAN30
        tri = [(rc, face_y), (big, face_y), (big, face_y - sign * depth)]
        _revolve_profile(part, tri, cut=True)
    part.thread(bore / 2.0)



# --- винт с потайной головкой и шестигранным углублением (DIN 7991, ISO 10642) ---------------------------------------
def _csk_rim(dims: Mapping[str, float]) -> float:
    """Высота цилиндрического пояска под плоским верхом: k минус высота 90-градусного конуса."""
    return dims["k"] - (dims["dk"] - dims["d"]) / 2.0


def _csk_profile(dims: Mapping[str, float], length: float) -> list[Point]:
    d, p, dk, k = dims["d"], dims["P"], dims["dk"], dims["k"]
    rim = _csk_rim(dims)
    top = [(0.0, 0.0), (dk / 2, 0.0)]
    if rim > 1e-9:
        top.append((dk / 2, -rim))
    return top + [(d / 2, -k), (d / 2, -(length - p)), (d / 2 - p, -length), (0.0, -length)]


def _csk_check(dims, length):
    _need(dims, ("d", "P", "dk", "k", "s", "t"), "винт с потайной головкой")
    _positive(dims, ("d", "P", "dk", "k", "s", "t"))
    if _csk_rim(dims) < 0:
        raise ShapeError("высота головки меньше глубины конуса 90°: размеры dk, k, d не согласованы")
    if length is None or length <= dims["k"] + dims["P"]:
        raise ShapeError("длина винта должна быть больше высоты головки плюс шаг резьбы")
    cone_r = dims["dk"] / 2 - max(0.0, dims["t"] - _csk_rim(dims))
    if dims["s"] / math.sqrt(3.0) >= cone_r or dims["t"] >= dims["k"]:
        raise ShapeError("шестигранное углубление не помещается в головку")


def _csk_volume(dims, length):
    return revolved_volume(_csk_profile(dims, length)) - hexagon_area(dims["s"]) * dims["t"]


def _csk_build(part, dims, length):
    _revolve_profile(part, _csk_profile(dims, length))
    with part.sketch("XOZ") as sk:
        sk.regular_polygon(6, across_flats=dims["s"])
    part.cut_extrude(sk, dims["t"], direction="both")
    b = dims.get("b")
    tip = (dims["d"] / 2, -(length - dims["P"]), 0.0)
    part.thread(dims["d"] / 2, None if b is None or b >= length else b, start_near=tip)


# --- винт с полукруглой головкой и шестигранным углублением (ISO 7380-1) -------------------------------------------
def _dome_radius(dims: Mapping[str, float]) -> float:
    """Радиус сферы головки: шаровой сегмент высотой k с основанием диаметром dk."""
    return ((dims["dk"] / 2) ** 2 + dims["k"] ** 2) / (2.0 * dims["k"])


def _button_tail(dims: Mapping[str, float], length: float) -> list[Point]:
    """Часть профиля ниже плоскости основания головки (y = -k): пояс, стержень с фаской на конце."""
    d, p, dk, k = dims["d"], dims["P"], dims["dk"], dims["k"]
    return [(0.0, -k), (dk / 2, -k), (d / 2, -k), (d / 2, -(k + length - p)), (d / 2 - p, -(k + length)),
            (0.0, -(k + length))]


def dome_pocket_correction(across_flats: float, sphere_r: float) -> float:
    """Интеграл по шестиграннику от глубины купола δ(ρ) = R − sqrt(R² − ρ²): сколько «воздуха» над куполом внутри углубления."""
    half_flat = across_flats / 2.0

    def inner(rho: float) -> float:        # первообразная от δ(ρ)·ρ
        return sphere_r * rho ** 2 / 2.0 + (sphere_r ** 2 - rho ** 2) ** 1.5 / 3.0

    n = 4000
    h = (math.pi / 6.0) / n

    def sector(phi: float) -> float:
        return inner(half_flat / math.cos(phi)) - inner(0.0)

    total = sector(0.0) + sector(math.pi / 6.0)
    for i in range(1, n):
        total += (4 if i % 2 else 2) * sector(i * h)
    return 12.0 * total * h / 3.0


def _button_check(dims, length):
    _need(dims, ("d", "P", "dk", "k", "s", "t"), "винт с полукруглой головкой")
    _positive(dims, ("d", "P", "dk", "k", "s", "t"))
    if length is None or length <= dims["P"]:
        raise ShapeError("длина винта должна быть больше шага резьбы")
    corner = dims["s"] / math.sqrt(3.0)
    r = _dome_radius(dims)
    if corner >= dims["dk"] / 2 or dims["t"] >= dims["k"]:
        raise ShapeError("шестигранное углубление не помещается в головку")
    if r - math.sqrt(r * r - corner * corner) >= dims["t"]:
        raise ShapeError("глубина углубления меньше провала купола у его углов")


def _button_volume(dims, length):
    cap = math.pi * dims["k"] * (3 * (dims["dk"] / 2) ** 2 + dims["k"] ** 2) / 6.0
    pocket = hexagon_area(dims["s"]) * dims["t"] - dome_pocket_correction(dims["s"], _dome_radius(dims))
    return cap + revolved_volume(_button_tail(dims, length)) - pocket


def _button_planar_area(dims, length) -> float:
    """Суммарная площадь плоских граней: дно углубления, шесть стенок под куполом, подголовок-кольцо и торец стержня."""
    s_, t, d, p, dk = dims["s"], dims["t"], dims["d"], dims["P"], dims["dk"]
    r = _dome_radius(dims)
    a = s_ / 2.0                                   # расстояние от оси до стенки углубления
    side = s_ / math.sqrt(3.0)                     # ширина стенки
    c = math.sqrt(r * r - a * a)

    def prim(u: float) -> float:                   # первообразная sqrt(c^2 - u^2)
        return 0.5 * (u * math.sqrt(c * c - u * u) + c * c * math.asin(u / c))

    wall = t * side - (r * side - 2.0 * prim(side / 2.0))
    return (hexagon_area(s_) + 6.0 * wall + math.pi * (dk ** 2 - d ** 2) / 4.0 + math.pi * (d / 2.0 - p) ** 2)


def _button_verify(part, dims, length):
    part.verify_planar_area(_button_planar_area(dims, length), 1e-4)


def _button_build(part, dims, length):
    d, p, dk, k = dims["d"], dims["P"], dims["dk"], dims["k"]
    r = _dome_radius(dims)
    rim_angle = math.degrees(math.atan2(r - k, dk / 2))
    with part.sketch("XOY") as sk:
        sk.arc(0.0, -r, r, rim_angle, 90.0)                       # купол от кромки к вершине
        sk.polyline([(0.0, 0.0), (0.0, -(k + length)), (d / 2 - p, -(k + length)), (d / 2, -(k + length - p)),
                     (d / 2, -k), (dk / 2, -k)], closed=False)    # ось, конец стержня, подголовок до кромки
    part.revolve(sk, axis="OY")
    with part.sketch("XOZ") as pocket:
        pocket.regular_polygon(6, across_flats=dims["s"])
    part.cut_extrude(pocket, dims["t"], direction="both")
    b = dims.get("b")
    tip = (d / 2, -(k + length - p), 0.0)
    part.thread(d / 2, None if b is None or b >= length else b, start_near=tip)


# --- шайба пружинная (DIN 127 B): упрощённо плоское кольцо без разреза ---------------------------------------------
def spring_washer_dims(dims: Mapping[str, float]) -> dict[str, float]:
    """Размеры плоского кольца: d2 = d1 + 2·b (ширина b по радиусу), толщина s."""
    return {"d1": dims["d1"], "d2": dims["d1"] + 2.0 * dims["b"], "h": dims["s"]}


def _spring_check(dims, length):
    _need(dims, ("d1", "b", "s"), "пружинная шайба")
    _positive(dims, ("d1", "b", "s"))


def _spring_volume(dims, length):
    return _washer_volume(spring_washer_dims(dims), None)


def _spring_build(part, dims, length):
    _washer_build(part, spring_washer_dims(dims), None)


SHAPES: dict[str, Shape] = {
    "cap_screw": Shape("cap_screw", "Винт с цилиндрической головкой и шестигранным углублением",
                       ("d", "P", "dk", "k", "s", "t"), True, "external",
                       _cap_screw_check, _cap_screw_volume, _cap_screw_build),
    "washer_flat": Shape("washer_flat", "Плоская шайба", ("d1", "d2", "h"), False, "",
                         _washer_check, _washer_volume, _washer_build),
    "csk_screw": Shape("csk_screw", "Винт с потайной головкой и шестигранным углублением",
                       ("d", "P", "dk", "k", "s", "t"), True, "external", _csk_check, _csk_volume, _csk_build),
    "button_screw": Shape("button_screw", "Винт с полукруглой головкой и шестигранным углублением",
                          ("d", "P", "dk", "k", "s", "t"), True, "external", _button_check, _button_volume,
                          _button_build, volume_tol=2e-3, verify=_button_verify),
    "washer_spring": Shape("washer_spring", "Пружинная шайба (плоское кольцо без разреза)", ("d1", "b", "s"), False, "",
                           _spring_check, _spring_volume, _spring_build),
    "nut_hex": Shape("nut_hex", "Шестигранная гайка", ("d", "P", "s", "m", "dw"), False, "internal",
                     _nut_check, _nut_volume, _nut_build, volume_tol=3e-2, verify=_nut_verify),
}
