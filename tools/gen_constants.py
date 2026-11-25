"""Генератор mkga/core/constants.py из библиотеки типов КОМПАСа, установленной на этой машине.

    python tools/gen_constants.py            # перезаписать mkga/core/constants.py
    python tools/gen_constants.py --check    # только сверить, код выхода 1 при расхождении

В репозиторий попадает НЕ вся таблица (3666 констант), а только группы из GROUPS ниже, то есть то,
что нужно модам, с запасом. Имена и значения берутся из типбиблиотеки `Kompas6Constants`, смысл
задаёт название константы в КОМПАСе. Чтобы добавить константу, допишите имя или шаблон в нужную
группу и перезапустите генератор. Нужны Windows, pywin32 и установленный КОМПАС (запускать его не нужно).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mkga.core.typelib import read_enum_constants, read_enums  # noqa: E402

OUT = ROOT / "mkga" / "core" / "constants.py"

# (заголовок группы, [регулярные выражения для ПОЛНОГО совпадения имени])
GROUPS: list[tuple[str, list[str]]] = [
    ("Типы документов", [r"ksDocument[A-Za-z]+"]),
    ("Спецификация: типы строк и варианты исполнения", [r"ksSpecification[A-Z][A-Za-z]*"]),
    ("Основная надпись: номера ячеек штампа", [r"ksSt[A-Z][A-Za-z0-9]*"]),
    ("Типы объектов 3D-модели (ksObject*)", [
        r"ksObject(Sketch|Sketchs|Point3D|Extrusion|CutExtrusion|Rotated|CutRotated|Evolution|Loft"
        r"|Fillet|FullFillet|Chamfer|Shell|Thread|ThreadPattern|MirrorPattern|Body7|Variable7"
        r"|VariableTable|MassInertiaProperties|SheetMetalBody)",
        r"ksObjectPlane3D[A-Za-z0-9]*",
        r"ksObjectAxis3D[A-Za-z0-9]*",
    ]),
    ("Типы объектов спецификации (ksObject*)", [
        r"ksObjectSpecification(Document|Object|BaseObject|BaseObjects|CommentObject|CommentObjects"
        r"|Column|Columns|ColumnItem|ColumnItems|Description|Descriptions|Subsection|Subsections"
        r"|Style|Styles|SectionStyle|SectionStyles)",
    ]),
    ("Типы операций построения 3D (pr*)", [
        r"pr(Base|Boss|Cut)(Extrusion|Rotated|Evolution|Loft)",
        r"pr(ExtrusionSurface|EvolutionSurface|Fillet3D|Chamfer3D|Hole[A-Za-z0-9]*|CutByPlane|CutBySketch)",
    ]),
    ("Размеры (ksDim*)", [r"ksDim[A-Z][A-Za-z0-9]*"]),
    ("Исполнения КОМПАСа (ksKompas*): назначение значений ещё не проверено", [r"ksKompas[A-Z][A-Za-z0-9]*"]),
]


# Константы 3D-моделирования из библиотеки Kompas6Constants3D (ksConstants3D.tlb): плоскости, оси, типы
# операций, направление и окончание выдавливания, тип вращения. Нужны mkga.core.model3d.
GROUPS_3D: list[tuple[str, list[str]]] = [
    ("3D: плоскости и оси детали по умолчанию", [r"o3d_plane(XOY|XOZ|YOZ)", r"o3d_axis(OX|OY|OZ)"]),
    ("3D: типы объектов и операций", [
        r"o3d_(sketch|part|baseExtrusion|bossExtrusion|cutExtrusion|baseRotated|bossRotated|cutRotated|cutBySketch)",
    ]),
    ("3D: направление выдавливания (ksDirectionTypeEnum)", [r"dt(Normal|Reverse|Both|MiddlePlane)"]),
    ("3D: тип окончания выдавливания (ksEndTypeEnum)", [
        r"et(Blind|ThroughAll|UpToVertexTo|UpToVertexFrom|UpToSurfaceTo|UpToSurfaceFrom|UpToNearSurface)"]),
    ("3D: тип вращения (ksRotatedTypeEnum)", [r"ksRT(Angle|Vertex|Surface)"]),
]

HEADER = '''"""Константы КОМПАС-3D, нужные модам. СГЕНЕРИРОВАНО `python tools/gen_constants.py`, вручную не править.

Источник: библиотеки типов Kompas6Constants (ksConstants.tlb) и Kompas6Constants3D (ksConstants3D.tlb)
из КОМПАС-3D v{version}. Это малая часть
всех констант КОМПАСа (отобрана группами в tools/gen_constants.py, с запасом). Имена совпадают с
именами в справке и примерах КОМПАСа, поэтому код читается рядом с документацией:

    from mkga.core import constants as C
    if doc_type == C.ksDocumentPart: ...

Не зависит от КОМПАСа и pywin32: работает в тестах и CI. Тест `tests/test_constants.py` сверяет
файл с библиотекой типов, когда КОМПАС установлен.
"""

'''


def flat_3d() -> dict[str, int]:
    """Все константы 3D-библиотеки одним словарём (имена перечислений не нужны)."""
    out: dict[str, int] = {}
    for members in read_enums().values():
        out.update(members)
    return out


def select(all_consts: dict[str, int], groups=None, taken: set[str] | None = None):
    chosen: set[str] = set(taken or ())
    out = []
    for title, patterns in (GROUPS if groups is None else groups):
        rx = [re.compile(p) for p in patterns]
        names = sorted(n for n in all_consts if n not in chosen and any(r.fullmatch(n) for r in rx))
        chosen.update(names)
        out.append((title, [(n, all_consts[n]) for n in names]))
    return out


def select_all() -> list:
    """Группы из ksConstants и из 3D-библиотеки (имена в них не пересекаются)."""
    first = select(read_enum_constants())
    taken = {n for _, items in first for n, _ in items}
    second = select(flat_3d(), GROUPS_3D, taken)
    overlap = taken & {n for _, items in second for n, _ in items}
    assert not overlap, f"одинаковые имена в двух библиотеках: {sorted(overlap)}"
    return first + second


def render(groups, version: str) -> str:
    lines = [HEADER.format(version=version)]
    all_names = []
    for title, items in groups:
        lines.append(f"# --- {title} ({len(items)}) " + "-" * max(3, 60 - len(title)))
        for name, value in items:
            lines.append(f"{name} = {value}")
            all_names.append(name)
        lines.append("")
    lines.append("# Все константы одним словарём (для проверок и поиска по значению).")
    lines.append("ALL = {")
    for name in all_names:
        lines.append(f'    "{name}": {name},')
    lines.append("}")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    groups = select_all()
    empty = [t for t, items in groups if not items]
    if empty:
        print("В группах нет ни одной константы (шаблон устарел?):", *empty, sep="\n  ", file=sys.stderr)
        return 1
    version = "24"  # версия, на которой подтверждён набор (см. docs/ROADMAP.md)
    text = render(groups, version)
    if "--check" in argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current.replace("\r\n", "\n") != text:
            print("mkga/core/constants.py расходится с библиотекой типов: перезапустите без --check", file=sys.stderr)
            return 1
        print(f"OK: {sum(len(i) for _, i in groups)} констант совпадают с библиотекой типов")
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    for title, items in groups:
        print(f"{len(items):4}  {title}")
    print(f"Записано {sum(len(i) for _, i in groups)} констант в {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
