"""Каталог метизов: загрузка таблиц стандартов (встроенных и пользовательских), проверка и имена деталей.

Один стандарт это один JSON-файл `data/standards/<id>.json` (формат: docs/ADDING_PARTS.md в папке мода):

    {
      "id": "din-912",                  латиница, цифры, дефис; уникален
      "category": "screws",             папка в дереве (data/categories.json)
      "number": "DIN 912",              обозначение стандарта, идёт в имя детали
      "aliases": ["ISO 4762"],          аналоги (только для справки в окне)
      "kind_name": "Винт",              короткое имя: идёт в имя ФАЙЛА («Винт DIN 912 - M8 x 25»)
      "full_name": "Винт с ...",        полное имя: идёт в «Наименование» детали
      "section": "standard",            standard: «Стандартные изделия»; other: «Прочие изделия»
      "shape": "cap_screw",             форма (mkga_fasteners/shapes.py)
      "lengths": [8, 10, 12, ...],      ряд длин (если у формы есть длина)
      "classes": ["8.8", "12.9"],       необязательно: классы прочности (выбор добавляет класс в имя)
      "source": "откуда размеры",       ОБЯЗАТЕЛЬНО
      "verified": false,                сверено ли с оригиналом стандарта человеком
      "sizes": {"M8": {"d": 8, "P": 1.25, "dk": 13, ..., "lmin": 12, "lmax": 120}, ...}
    }

Размеры строки таблицы: все числа в мм; `lmin`/`lmax` ограничивают ряд длин для этого типоразмера.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from . import shapes

SECTION_NAMES = {"standard": "Стандартные изделия", "other": "Прочие изделия"}
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
_BAD_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


def fmt_number(x: float) -> str:
    """25 -> «25», 2.5 -> «2,5» (запятая по русскому оформлению)."""
    text = f"{x:.4f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def size_display(label: str) -> str:
    """«M2.5» -> «M2,5»."""
    return label.replace(".", ",")


def safe_filename(text: str) -> str:
    """Имя файла: без символов, запрещённых в Windows, и без хвостовых точек и пробелов."""
    return _BAD_FILENAME_CHARS.sub("_", text).strip(" .")


@dataclass(frozen=True)
class Names:
    file_stem: str   # «Винт DIN 912 - M8 x 25»
    title: str       # «Наименование»: полное имя


@dataclass(frozen=True)
class Standard:
    id: str
    category: str
    number: str
    kind_name: str
    full_name: str
    section: str
    shape: str
    sizes: Mapping[str, Mapping[str, float]]
    lengths: tuple[float, ...] = ()
    classes: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    source: str = ""
    verified: bool = False
    notes: str = ""
    origin: str = "builtin"          # builtin | user
    path: Path | None = field(default=None, compare=False)

    @property
    def shape_obj(self) -> shapes.Shape:
        return shapes.SHAPES[self.shape]

    @property
    def has_length(self) -> bool:
        return self.shape_obj.has_length

    @property
    def section_name(self) -> str:
        return SECTION_NAMES[self.section]

    @property
    def size_labels(self) -> list[str]:
        return list(self.sizes)

    def dims(self, size: str) -> dict[str, float]:
        """Размеры типоразмера для формы (без служебных lmin/lmax)."""
        if size not in self.sizes:
            raise KeyError(f"типоразмера {size} нет в {self.number}")
        return {k: v for k, v in self.sizes[size].items() if k not in ("lmin", "lmax")}

    def lengths_for(self, size: str) -> list[float]:
        """Допустимые длины для типоразмера: ряд стандарта в пределах lmin..lmax строки."""
        if not self.has_length:
            return []
        row = self.sizes[size]
        lo, hi = row.get("lmin", float("-inf")), row.get("lmax", float("inf"))
        return [l for l in self.lengths if lo <= l <= hi]

    def names(self, size: str, length: float | None = None, strength: str | None = None) -> Names:
        tail = f" - {size_display(size)}"
        if length is not None:
            tail += f" x {fmt_number(length)}"
        if strength:
            tail += f" - {strength}"
        return Names(safe_filename(f"{self.kind_name} {self.number}{tail}"), f"{self.full_name} {self.number}{tail}")

    def volume(self, size: str, length: float | None = None) -> float:
        return self.shape_obj.volume(self.dims(size), length)


@dataclass
class Catalog:
    standards: dict[str, Standard] = field(default_factory=dict)
    categories: list[tuple[str, str]] = field(default_factory=list)   # (id, название) в порядке показа
    problems: list[str] = field(default_factory=list)                 # что не загрузилось и почему

    def in_category(self, category: str) -> list[Standard]:
        return sorted((s for s in self.standards.values() if s.category == category), key=lambda s: s.number)

    def search(self, text: str) -> list[Standard]:
        """Поиск по обозначению, аналогам и названию (без учёта регистра)."""
        q = text.strip().lower()
        if not q:
            return list(self.standards.values())
        return [s for s in self.standards.values()
                if q in " ".join((s.number, s.full_name, s.kind_name, *s.aliases)).lower()]


# --- проверка и загрузка --------------------------------------------------------------------------------
def validate(data: object) -> list[str]:
    """Список ошибок описания стандарта (пустой список: всё хорошо)."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["файл должен содержать объект JSON {...}"]
    for key in ("id", "category", "number", "kind_name", "full_name", "section", "shape", "source", "sizes"):
        if key not in data:
            errors.append(f"нет поля «{key}»")
    if errors:
        return errors
    if not isinstance(data["id"], str) or not _ID_RE.match(data["id"]):
        errors.append("«id»: латиница в нижнем регистре, цифры и дефис, 2–40 символов")
    if data["section"] not in SECTION_NAMES:
        errors.append("«section»: standard или other")
    shape = shapes.SHAPES.get(data["shape"])
    if shape is None:
        errors.append(f"«shape»: нет формы «{data['shape']}», доступны: {', '.join(shapes.SHAPES)}")
    if not str(data["source"]).strip():
        errors.append("«source»: укажите, откуда взяты размеры")
    sizes = data["sizes"]
    if not isinstance(sizes, dict) or not sizes:
        errors.append("«sizes»: нужна непустая таблица типоразмеров")
        return errors
    lengths = data.get("lengths", [])
    if shape is not None and shape.has_length:
        if not lengths or not all(isinstance(x, (int, float)) and x > 0 for x in lengths):
            errors.append("«lengths»: нужен ряд положительных длин")
        elif list(lengths) != sorted(set(lengths)):
            errors.append("«lengths»: длины по возрастанию без повторов")
    for label, row in sizes.items():
        if not isinstance(row, dict):
            errors.append(f"«{label}»: строка таблицы должна быть объектом")
            continue
        bad = [k for k, v in row.items() if isinstance(v, bool) or not isinstance(v, (int, float))]
        if bad:
            errors.append(f"«{label}»: значения должны быть числами ({', '.join(bad)})")
            continue
        if shape is None:
            continue
        probe = None
        if shape.has_length:
            ok = [l for l in lengths if row.get("lmin", 0) <= l <= row.get("lmax", 1e9)]
            if not ok:
                errors.append(f"«{label}»: в пределах lmin..lmax нет ни одной длины из «lengths»")
                continue
            probe = ok[0]
        dims = {k: v for k, v in row.items() if k not in ("lmin", "lmax")}
        try:
            shape.check(dims, probe)
        except shapes.ShapeError as e:
            errors.append(f"«{label}»: {e}")
    return errors


def _from_data(data: dict, origin: str, path: Path | None) -> Standard:
    return Standard(
        id=data["id"], category=data["category"], number=data["number"], kind_name=data["kind_name"],
        full_name=data["full_name"], section=data["section"], shape=data["shape"],
        sizes={k: dict(v) for k, v in data["sizes"].items()},
        lengths=tuple(data.get("lengths", ())), classes=tuple(data.get("classes", ())),
        aliases=tuple(data.get("aliases", ())), source=data["source"], verified=bool(data.get("verified", False)),
        notes=data.get("notes", ""), origin=origin, path=path)


def load_standard_file(path: Path, origin: str = "builtin") -> Standard:
    """Прочитать и проверить один файл. Ошибки: ValueError с понятным текстом."""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"{path.name}: не удалось прочитать ({e})") from e
    errors = validate(data)
    if errors:
        raise ValueError(f"{path.name}: " + "; ".join(errors))
    return _from_data(data, origin, path)


def load_catalog(builtin_dir: Path, user_dir: Path | None = None) -> Catalog:
    """Загрузить встроенные стандарты и (если есть) пользовательские. Плохой файл не ломает каталог.

    Пользовательский стандарт с тем же id заменяет встроенный (так можно поправить таблицу у себя).
    """
    catalog = Catalog()
    cats_file = builtin_dir / "categories.json"
    try:
        for item in json.loads(cats_file.read_text(encoding="utf-8-sig")):
            catalog.categories.append((item["id"], item["name"]))
    except (OSError, ValueError, KeyError, TypeError) as e:
        catalog.problems.append(f"categories.json: {e}")
    sources = [(builtin_dir / "standards", "builtin")]
    if user_dir is not None:
        sources.append((user_dir, "user"))
    for folder, origin in sources:
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            try:
                std = load_standard_file(path, origin)
            except ValueError as e:
                catalog.problems.append(str(e))
                continue
            if std.id in catalog.standards and origin == "user":
                catalog.problems.append(f"{path.name}: заменяет встроенный стандарт «{std.id}»")
            catalog.standards[std.id] = std
    known = {cid for cid, _ in catalog.categories}
    for std in catalog.standards.values():
        if std.category not in known:     # неизвестная папка: показываем отдельно, а не теряем стандарт
            catalog.categories.append((std.category, std.category))
            known.add(std.category)
    return catalog
