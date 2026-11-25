"""«Свои детали»: добавить в каталог свой стандарт или изделие (локально у пользователя), в том числе с помощью ИИ.

Своя деталь это обычный файл-таблица (JSON), такой же, как у встроенных стандартов. Он лежит в папке данных мода
(`<данные мода>/standards`), каталог читает её при запуске и по кнопке «Обновить каталог». Файл можно показать
другим: чтобы добавить его в общий репозиторий, достаточно открыть задачу на GitHub и приложить файл.

Здесь:
- `standard_to_dict` / `template_for`: заготовка нового файла на основе существующего стандарта;
- `ai_prompt`: готовая инструкция для ИИ (формат, список форм, правила про источники);
- `open_custom_dialog`: окно с кнопками (создать заготовку, скопировать инструкцию, открыть папку, обновить каталог).
"""

from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk

from . import drawing, shapes
from .catalog import Standard

DOC_HINT = "mods/fasteners/docs/ADDING_PARTS.md"
SHARE_HINT = ("Чтобы добавить деталь в общий каталог: откройте задачу «Предложить мод или деталь» в репозитории MKGA "
              "на GitHub и приложите свой файл .json (укажите, откуда взяты размеры).")


def standard_to_dict(std: Standard) -> dict:
    """Стандарт обратно в словарь для JSON (порядок полей как в документации)."""
    data: dict = {
        "id": std.id, "category": std.category, "number": std.number, "aliases": list(std.aliases),
        "kind_name": std.kind_name, "full_name": std.full_name, "section": std.section, "shape": std.shape,
    }
    if std.has_length:
        data["lengths"] = [int(x) if float(x).is_integer() else x for x in std.lengths]
    if std.classes:
        data["classes"] = list(std.classes)
    data.update({"source": std.source, "verified": std.verified, "notes": std.notes,
                 "sizes": {k: dict(v) for k, v in std.sizes.items()}})
    return data


def template_for(std: Standard) -> tuple[str, str]:
    """(имя файла, текст JSON) заготовки на основе `std`: свой id и пометка «источник не заполнен»."""
    new_id = ("my-" + std.id)[:40].rstrip("-")
    data = standard_to_dict(std)
    data.update({"id": new_id, "number": f"{std.number} (моё)", "verified": False,
                 "source": "ЗАПОЛНИТЕ: откуда взяты размеры (стандарт, каталог производителя, ссылка)"})
    return f"{new_id}.json", json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def shapes_help() -> str:
    """Список форм с нужными размерами и их смыслом (для инструкции ИИ и документации)."""
    lines = []
    for shape in shapes.SHAPES.values():
        legend = {key: meaning for _sym, meaning, key in drawing.LEGENDS.get(shape.id, []) if key}
        dims = ", ".join(f"{k} ({legend.get(k, 'размер, мм')})" for k in shape.required)
        length = "есть длина l (поле lengths и lmin/lmax в строках)" if shape.has_length else "без длины"
        lines.append(f'- "{shape.id}": {shape.title}; размеры строки таблицы: {dims}; {length}.')
    return "\n".join(lines)


def ai_prompt(example: Standard | None) -> str:
    """Инструкция для ИИ: как оформить таблицу размеров нового изделия файлом, который понимает мод."""
    sample = ""
    if example is not None:
        small = standard_to_dict(example)
        keep = list(small["sizes"])[:2]
        small["sizes"] = {k: small["sizes"][k] for k in keep}
        if "lengths" in small:
            small["lengths"] = small["lengths"][:8]
        sample = json.dumps(small, ensure_ascii=False, indent=2)
    return f"""Помоги добавить изделие в каталог метизов для КОМПАС-3D (мод «Метизы и фитинги» проекта MKGA).
Нужен ОДИН файл JSON с таблицей размеров. Мод сам построит 3D-деталь по форме и размерам.

ПРАВИЛА
1. Размеры только из надёжного источника (сам стандарт, каталог производителя, справочник) и в мм.
   Не выдумывай и не округляй «на глаз». Если значения нет, не добавляй этот типоразмер.
2. Обязательно заполни поле "source": откуда взяты числа (название документа, ссылка).
3. Поле "verified" оставь false: его меняет человек после сверки с оригиналом.
4. Формы (поле "shape"), для которых уже есть построение:
{shapes_help()}
   Если изделию подходит одна из форм, нужна только таблица. Если нужна новая форма, так и скажи:
   её придётся добавить в код (mkga_fasteners/shapes.py).
5. "section": "standard" для стандартных изделий (раздел спецификации «Стандартные изделия»),
   "other" для покупных изделий без стандарта («Прочие изделия»).
6. "id" только латиница в нижнем регистре, цифры и дефис (например "my-din-933"). "category": один из
   screws, nuts, washers, pins, inserts, pneumatics, profiles, other.
7. "kind_name" короткое имя для имени файла («Винт»), "full_name" полное имя для поля «Наименование».
   Итоговые имена: «<kind_name> <number> - <типоразмер> x <длина>» и «<full_name> <number> - ...».
8. Строки таблицы "sizes": ключ это типоразмер («M8»), значения числа в мм; для форм с длиной добавь
   "lmin" и "lmax" (ограничение ряда длин "lengths").

ОБРАЗЕЦ ФОРМАТА (фрагмент, у настоящего файла все типоразмеры):
{sample}

Верни только готовый JSON. Файл нужно сохранить в папку своих деталей мода (кнопка «Своя деталь…» → «Открыть папку»)
и нажать «Обновить каталог».
"""


# --- окно ------------------------------------------------------------------------------------------------------
def open_custom_dialog(win) -> None:
    """Окно «Свои детали»: пошагово и с кнопками, без правки кода."""
    t = win.theme
    top = tk.Toplevel(win.root)
    top.title("Свои детали")
    top.configure(background=t.palette.bg)
    top.transient(win.root)
    top.resizable(False, False)
    frame = t.card(top)
    frame.grid(row=0, column=0, padx=t.pad, pady=t.pad)
    wrap = t.px(520)

    def text(row: int, msg: str, style: str = "Card.TLabel") -> None:
        ttk.Label(frame, text=msg, style=style, wraplength=wrap, justify="left").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(0, t.pad_small))

    def button(row: int, label: str, command, hint: str) -> None:
        ttk.Button(frame, text=label, style="Card.TButton", command=command).grid(
            row=row, column=0, sticky="w", pady=(t.pad_small, 0), padx=(0, t.pad))
        ttk.Label(frame, text=hint, style="Card.Small.Muted.TLabel", wraplength=t.px(300), justify="left").grid(
            row=row, column=1, sticky="w", pady=(t.pad_small, 0))

    ttk.Label(frame, text="Своя деталь или стандарт", style="Card.Heading.TLabel").grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, t.pad_small))
    text(1, "Своя деталь это небольшой файл-таблица размеров (JSON). Он остаётся только у вас, в каталоге такие "
            "детали помечены звёздочкой. Можно сделать файл на основе выбранного стандарта или поручить это ИИ.")
    button(2, "Заготовка из выбранного…", lambda: (win.create_template(), top.destroy()),
           "Копия выбранного стандарта с новым id: поправьте значения в текстовом редакторе.")
    button(3, "Инструкция для ИИ", lambda: win.copy_ai_prompt(),
           "Копирует в буфер обмена готовое задание: вставьте его в чат с ИИ вместе со ссылкой или таблицей размеров.")
    button(4, "Открыть папку", lambda: win.open_user_folder(), "Сюда кладутся файлы своих деталей.")
    button(5, "Обновить каталог", lambda: (win.reload_catalog(), top.destroy()),
           "Прочитать папку заново. Ошибки в файлах показываются в журнале, остальной каталог работает.")
    ttk.Label(frame, text=SHARE_HINT, style="Card.Small.Muted.TLabel", wraplength=wrap, justify="left").grid(
        row=6, column=0, columnspan=2, sticky="w", pady=(t.pad, 0))
    ttk.Label(frame, text=f"Подробно: {DOC_HINT}", style="Card.Small.Muted.TLabel").grid(
        row=7, column=0, columnspan=2, sticky="w")
    top.update_idletasks()
    x = win.root.winfo_rootx() + (win.root.winfo_width() - top.winfo_width()) // 2
    y = win.root.winfo_rooty() + t.px(80)
    top.geometry(f"+{max(0, x)}+{max(0, y)}")
    top.focus_set()
