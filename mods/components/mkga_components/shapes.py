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
def _dome_radius(dims: Mapping[str, float], height: float | None = None) -> float:
    """Радиус сферы головки: шаровой сегмент высотой `height` (по умолчанию k) с основанием диаметром dk."""
    h = dims["k"] if height is None else height
    return ((dims["dk"] / 2) ** 2 + h ** 2) / (2.0 * h)


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


# --- винт с полукруглой головкой и фланцем (ISO 7380-2) -----------------------------------------------------------------
def _flange_height(dims: Mapping[str, float]) -> float:
    """Высота купола: общая высота головки k минус толщина фланца c."""
    return dims["k"] - dims["c"]


def _flange_check(dims, length):
    _need(dims, ("d", "P", "dk", "dc", "k", "c", "s", "t"), "винт с фланцем")
    _positive(dims, ("d", "P", "dk", "dc", "k", "c", "s", "t"))
    if length is None or length <= dims["P"]:
        raise ShapeError("длина винта должна быть больше шага резьбы")
    if dims["dc"] <= dims["dk"] or dims["c"] >= dims["k"]:
        raise ShapeError("размеры фланца не согласованы: dc должен быть больше dk, c меньше k")
    h = _flange_height(dims)
    corner = dims["s"] / math.sqrt(3.0)
    r = _dome_radius(dims, h)
    if corner >= dims["dk"] / 2:
        raise ShapeError("шестигранное углубление не помещается в головку")
    if r - math.sqrt(r * r - corner * corner) >= dims["t"]:
        raise ShapeError("глубина углубления меньше провала купола у его углов")
    if dims["t"] > dims["k"] and corner >= dims["d"] / 2:
        raise ShapeError("углубление выходит за пределы стержня")


def _flange_tail(dims: Mapping[str, float], length: float) -> list[Point]:
    """Профиль ниже основания купола (y = -(k - c)): фланец, стержень, фаска на конце."""
    d, p, dk, dc, k, c = (dims[x] for x in ("d", "P", "dk", "dc", "k", "c"))
    base = -(k - c)
    return [(0.0, base), (dc / 2, base), (dc / 2, -k), (d / 2, -k), (d / 2, -(k + length - p)),
            (d / 2 - p, -(k + length)), (0.0, -(k + length))]


def _flange_volume(dims, length):
    h = _flange_height(dims)
    cap = math.pi * h * (3 * (dims["dk"] / 2) ** 2 + h ** 2) / 6.0
    pocket = hexagon_area(dims["s"]) * dims["t"] - dome_pocket_correction(dims["s"], _dome_radius(dims, h))
    return cap + revolved_volume(_flange_tail(dims, length)) - pocket


def _flange_planar_area(dims, length) -> float:
    """Плоские грани: дно углубления, шесть стенок под куполом, верх и низ фланца, торец стержня."""
    s_, t, d, p, dk, dc = dims["s"], dims["t"], dims["d"], dims["P"], dims["dk"], dims["dc"]
    r = _dome_radius(dims, _flange_height(dims))
    a = s_ / 2.0
    side = s_ / math.sqrt(3.0)
    c_ = math.sqrt(r * r - a * a)

    def prim(u: float) -> float:
        return 0.5 * (u * math.sqrt(c_ * c_ - u * u) + c_ * c_ * math.asin(u / c_))

    wall = t * side - (r * side - 2.0 * prim(side / 2.0))
    return (hexagon_area(s_) + 6.0 * wall + math.pi * (dc ** 2 - dk ** 2) / 4.0 + math.pi * (dc ** 2 - d ** 2) / 4.0
            + math.pi * (d / 2.0 - p) ** 2)


def _flange_verify(part, dims, length):
    part.verify_planar_area(_flange_planar_area(dims, length), 1e-4)


def _flange_build(part, dims, length):
    d, p, dk, dc, k, c = (dims[x] for x in ("d", "P", "dk", "dc", "k", "c"))
    h = _flange_height(dims)
    r = _dome_radius(dims, h)
    rim_angle = math.degrees(math.atan2(r - h, dk / 2))
    with part.sketch("XOY") as sk:
        sk.arc(0.0, -r, r, rim_angle, 90.0)                       # купол от кромки к вершине
        sk.polyline([(0.0, 0.0), (0.0, -(k + length)), (d / 2 - p, -(k + length)), (d / 2, -(k + length - p)),
                     (d / 2, -k), (dc / 2, -k), (dc / 2, -h), (dk / 2, -h)], closed=False)
    part.revolve(sk, axis="OY")
    with part.sketch("XOZ") as pocket:
        pocket.regular_polygon(6, across_flats=dims["s"])
    part.cut_extrude(pocket, dims["t"], direction="both")
    b = dims.get("b")
    tip = (d / 2, -(k + length - p), 0.0)
    part.thread(d / 2, None if b is None or b >= length else b, start_near=tip)


# --- шайба пружинная (DIN 127 B): кольцо с разрывом ---------------------------------------------------------------------
def spring_washer_dims(dims: Mapping[str, float]) -> dict[str, float]:
    """Размеры кольца: d2 = d1 + 2·b (ширина b по радиусу), толщина s, ширина разрыва = s (условно)."""
    return {"d1": dims["d1"], "d2": dims["d1"] + 2.0 * dims["b"], "h": dims["s"], "gap": dims["s"]}


def _strip_area(r_in: float, r_out: float, gap: float) -> float:
    """Площадь части кольца в полосе |z| < gap/2 при x > 0 (то, что вырезает разрыв)."""
    half = gap / 2.0

    def prim(r: float, z: float) -> float:        # первообразная sqrt(r^2 - z^2)
        return 0.5 * (z * math.sqrt(r * r - z * z) + r * r * math.asin(z / r))

    return 2.0 * (prim(r_out, half) - prim(r_in, half))


def _spring_check(dims, length):
    _need(dims, ("d1", "b", "s"), "пружинная шайба")
    _positive(dims, ("d1", "b", "s"))
    if dims["s"] >= dims["d1"]:
        raise ShapeError("разрыв шайбы шире её отверстия")


def _spring_volume(dims, length):
    w = spring_washer_dims(dims)
    r_in, r_out = w["d1"] / 2, w["d2"] / 2
    return (math.pi * (r_out ** 2 - r_in ** 2) - _strip_area(r_in, r_out, w["gap"])) * w["h"]


def _spring_planar_area(dims) -> float:
    w = spring_washer_dims(dims)
    r_in, r_out, half = w["d1"] / 2, w["d2"] / 2, w["gap"] / 2
    faces = 2.0 * (math.pi * (r_out ** 2 - r_in ** 2) - _strip_area(r_in, r_out, w["gap"]))   # верх и низ
    faces += 2.0 * w["h"] * (math.sqrt(r_out ** 2 - half ** 2) - math.sqrt(r_in ** 2 - half ** 2))   # торцы разрыва
    return faces


def _spring_verify(part, dims, length):
    part.verify_planar_area(_spring_planar_area(dims), 1e-6)


def _spring_build(part, dims, length):
    w = spring_washer_dims(dims)
    _washer_build(part, w, None)
    r_out = w["d2"] / 2
    with part.sketch("XOZ") as slit:
        slit.rect(w["d1"] / 2 - 1.0, -w["gap"] / 2.0, r_out - w["d1"] / 2 + 2.0, w["gap"])   # полоса через кольцо при x > 0
    part.cut_extrude(slit, direction="both")                                                 # сквозная по высоте


# --- болт с шестигранной головкой (DIN 933 / DIN 931, ISO 4017 / ISO 4014) --------------------------------------------
# Деталь строится симметрично относительно плоскости XOZ: головка занимает y от -k/2 до +k/2, стержень идёт вниз.
def hex_bolt_thread_length(dims: Mapping[str, float], length: float) -> float | None:
    """Длина резьбы от конца: b (l <= 125), b2 (125 < l <= 200), b3 (l > 200); None, если резьба на всю длину (DIN 933)."""
    if dims.get("b") is None:
        return None
    key = "b" if length <= 125 else "b2" if length <= 200 else "b3"
    value = dims.get(key)
    return None if value is None or value >= length else float(value)


def _bolt_shank(dims: Mapping[str, float], length: float) -> list[Point]:
    d, p, k = dims["d"], dims["P"], dims["k"]
    top = -k / 2.0
    return [(0.0, top), (d / 2, top), (d / 2, top - (length - p)), (d / 2 - p, top - length), (0.0, top - length)]


def _bolt_check(dims, length):
    _need(dims, ("d", "P", "s", "k", "dw"), "болт")
    _positive(dims, ("d", "P", "s", "k", "dw"))
    if length is None or length <= dims["P"]:
        raise ShapeError("длина болта должна быть больше шага резьбы")
    if dims["dw"] >= dims["s"] or dims["d"] >= dims["dw"]:
        raise ShapeError("размеры фаски головки не согласованы: должно быть d < dw < s")
    if (dims["s"] / math.cos(math.radians(30)) / 2 - dims["dw"] / 2) * TAN30 >= dims["k"]:
        raise ShapeError("фаска срезает головку по всей высоте")


def _bolt_volume(dims, length):
    head = hexagon_area(dims["s"]) * dims["k"] - hex_chamfer_volume(dims["s"], dims["dw"], 30.0)
    return head + revolved_volume(_bolt_shank(dims, length))


def _bolt_planar_area(dims, length) -> float:
    """Плоские грани: верх головки (круг dw), шесть боковых граней с выемкой фаски, низ головки (шестигранник без стержня), торец."""
    s, k, dw, d, p = dims["s"], dims["k"], dims["dw"], dims["d"], dims["P"]
    flat = s / math.sqrt(3.0) * k - hex_flat_notch_area(s, dw)
    return (math.pi * (dw / 2) ** 2 + 6.0 * flat + hexagon_area(s) - math.pi * (d / 2) ** 2 + math.pi * (d / 2 - p) ** 2)


def _bolt_verify(part, dims, length):
    part.verify_planar_area(_bolt_planar_area(dims, length), 1e-4)


def _bolt_build(part, dims, length):
    k, s, d, p = dims["k"], dims["s"], dims["d"], dims["P"]
    with part.sketch("XOZ") as sk:
        sk.regular_polygon(6, across_flats=s)
    part.extrude(sk, k, direction="middle")
    _revolve_profile(part, _bolt_shank(dims, length))
    rc = dims["dw"] / 2.0
    big = s / math.cos(math.radians(30)) / 2.0 + 1.0
    depth = (big - rc) * TAN30
    top = k / 2.0
    _revolve_profile(part, [(rc, top), (big, top), (big, top - depth)], cut=True)     # фаска 30° верха головки
    b = hex_bolt_thread_length(dims, length)
    tip = (d / 2, -k / 2.0 - (length - p), 0.0)
    part.thread(d / 2, b, start_near=tip)


# --- самоконтрящаяся гайка с нейлоновым кольцом (DIN 985, ISO 10511) ------------------------------------------------------
def _nyloc_collar(dims: Mapping[str, float]) -> float:
    return dims["h"] - dims["m"]


def _nyloc_check(dims, length):
    _need(dims, ("d", "P", "s", "m", "h", "dw"), "самоконтрящаяся гайка")
    _positive(dims, ("d", "P", "s", "m", "h", "dw"))
    bore = internal_minor_diameter(dims["d"], dims["P"])
    if _nyloc_collar(dims) <= 0:
        raise ShapeError("полная высота h должна быть больше высоты шестигранника m")
    if bore >= dims["dw"] or dims["dw"] > dims["s"]:
        raise ShapeError("размеры фаски гайки не согласованы")
    if (dims["s"] / math.cos(math.radians(30)) / 2 - dims["dw"] / 2) * TAN30 >= dims["m"]:
        raise ShapeError("фаска срезает шестигранник по всей высоте")


def _nyloc_volume(dims, length):
    bore = internal_minor_diameter(dims["d"], dims["P"])
    hole = math.pi * (bore / 2.0) ** 2 * dims["h"]
    collar = math.pi * (dims["dw"] / 2.0) ** 2 * _nyloc_collar(dims)
    return hexagon_area(dims["s"]) * dims["m"] + collar - hole - hex_chamfer_volume(dims["s"], dims["dw"], 30.0)


def _nyloc_planar_area(dims) -> float:
    """Плоские грани: нижний торец, шесть граней с выемкой снизу, верх шестигранника вокруг буртика, верх буртика."""
    s, m, dw = dims["s"], dims["m"], dims["dw"]
    rc = dw / 2.0
    rb = internal_minor_diameter(dims["d"], dims["P"]) / 2.0
    flat = s / math.sqrt(3.0) * m - hex_flat_notch_area(s, dw)
    return (math.pi * (rc ** 2 - rb ** 2) + 6.0 * flat + (hexagon_area(s) - math.pi * rc ** 2) + math.pi * (rc ** 2 - rb ** 2))


def _nyloc_verify(part, dims, length):
    part.verify_planar_area(_nyloc_planar_area(dims), 1e-4)


def _nyloc_build(part, dims, length):
    m, s, h = dims["m"], dims["s"], dims["h"]
    rc = dims["dw"] / 2.0
    bore = internal_minor_diameter(dims["d"], dims["P"])
    with part.sketch("XOZ") as sk:
        sk.regular_polygon(6, across_flats=s)
    part.extrude(sk, m, direction="middle")
    top = m / 2.0
    _revolve_profile(part, [(0.0, top - 0.5), (rc, top - 0.5), (rc, top - m + h), (0.0, top - m + h)])   # буртик с нейлоновым кольцом
    with part.sketch("XOZ") as hole:
        hole.circle(0, 0, bore / 2.0)
    part.cut_extrude(hole, direction="both")
    big = s / math.cos(math.radians(30)) / 2.0 + 1.0
    depth = (big - rc) * TAN30
    _revolve_profile(part, [(rc, -m / 2.0), (big, -m / 2.0), (big, -m / 2.0 + depth)], cut=True)   # фаска 30° только снизу
    part.thread(bore / 2.0)


# --- установочный винт с шестигранным углублением (DIN 913 плоский конец, DIN 914 конус, DIN 916 чашечный) ----------------
# Тело вращения: цилиндр d длиной l, конец с фаской 45° до диаметра dp (у плоского это торец, у конусного вершина).
def _set_profile(dims: Mapping[str, float], length: float) -> list[Point]:
    d, dp = dims["d"], dims["dp"]
    c = (d - dp) / 2.0
    return [(0.0, 0.0), (d / 2, 0.0), (d / 2, -(length - c)), (dp / 2, -length), (0.0, -length)]


def _set_check(dims, length):
    _need(dims, ("d", "P", "dp", "s", "t"), "установочный винт")
    _positive(dims, ("d", "P", "dp", "s", "t"))
    if dims["dp"] >= dims["d"]:
        raise ShapeError("диаметр конца dp должен быть меньше диаметра резьбы d")
    if length is None or length <= dims["t"] + (dims["d"] - dims["dp"]) / 2.0:
        raise ShapeError("длина винта должна быть больше глубины углубления плюс длины фаски конца")
    if dims["s"] / math.cos(math.radians(30)) >= dims["d"]:
        raise ShapeError("шестигранное углубление не помещается в винт")


def _set_volume(dims, length):
    return revolved_volume(_set_profile(dims, length)) - hexagon_area(dims["s"]) * dims["t"]


def _set_build(part, dims, length):
    _revolve_profile(part, _set_profile(dims, length))
    with part.sketch("XOZ") as sk:
        sk.regular_polygon(6, across_flats=dims["s"])
    part.cut_extrude(sk, dims["t"], direction="both")
    part.thread(dims["d"] / 2)                                  # резьба на всю длину


# --- штифт цилиндрический (ISO 2338, DIN 7) ------------------------------------------------------------------------------
def _pin_profile(dims: Mapping[str, float], length: float) -> list[Point]:
    r, c = dims["d"] / 2, dims["c"]
    return [(0.0, 0.0), (r - c, 0.0), (r, -c), (r, -(length - c)), (r - c, -length), (0.0, -length)]


def _pin_check(dims, length):
    _need(dims, ("d", "c"), "штифт")
    _positive(dims, ("d", "c"))
    if dims["c"] >= dims["d"] / 2:
        raise ShapeError("фаска штифта больше его радиуса")
    if length is None or length <= 2 * dims["c"]:
        raise ShapeError("длина штифта должна быть больше двух фасок")


def _pin_volume(dims, length):
    return revolved_volume(_pin_profile(dims, length))


def _pin_build(part, dims, length):
    _revolve_profile(part, _pin_profile(dims, length))


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
    "washer_spring": Shape("washer_spring", "Пружинная шайба (кольцо с разрывом, без скручивания)", ("d1", "b", "s"), False,
                           "", _spring_check, _spring_volume, _spring_build, verify=_spring_verify),
    "flange_button_screw": Shape("flange_button_screw", "Винт с полукруглой головкой и фланцем и шестигранным углублением",
                                 ("d", "P", "dk", "dc", "k", "c", "s", "t"), True, "external", _flange_check,
                                 _flange_volume, _flange_build, volume_tol=2e-3, verify=_flange_verify),
    "hex_bolt": Shape("hex_bolt", "Болт с шестигранной головкой", ("d", "P", "s", "k", "dw"), True, "external",
                      _bolt_check, _bolt_volume, _bolt_build, volume_tol=3e-2, verify=_bolt_verify),
    "nut_nyloc": Shape("nut_nyloc", "Самоконтрящаяся гайка с нейлоновым кольцом", ("d", "P", "s", "m", "h", "dw"), False,
                       "internal", _nyloc_check, _nyloc_volume, _nyloc_build, volume_tol=3e-2, verify=_nyloc_verify),
    "set_screw": Shape("set_screw", "Установочный винт с шестигранным углублением (конец с фаской 45°)",
                       ("d", "P", "dp", "s", "t"), True, "external", _set_check, _set_volume, _set_build),
    "pin_dowel": Shape("pin_dowel", "Цилиндрический штифт с фасками", ("d", "c"), True, "", _pin_check, _pin_volume,
                       _pin_build),
    "nut_hex": Shape("nut_hex", "Шестигранная гайка", ("d", "P", "s", "m", "dw"), False, "internal",
                     _nut_check, _nut_volume, _nut_build, volume_tol=3e-2, verify=_nut_verify),
}
