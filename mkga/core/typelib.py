"""Чтение констант из зарегистрированной в системе библиотеки типов КОМПАСа.

Нужно только разработчикам: генератору `tools/gen_constants.py` и тесту сверки. Работе модов это
не требуется (константы лежат в готовом `mkga.core.constants`). Не использует кэш gen_py:
читает перечисления (enum) прямо из библиотеки типов через pythoncom. Нужны Windows, pywin32
и установленный КОМПАС (он регистрирует библиотеки).
"""

from __future__ import annotations

from .kompas import CONSTANTS_TYPELIB


def read_enum_constants(guid: str = CONSTANTS_TYPELIB, major: int = 1, minor: int = 0) -> dict[str, int]:
    """Все именованные константы всех перечислений библиотеки: {имя: значение}."""
    import pythoncom

    tlb = pythoncom.LoadRegTypeLib(guid, major, minor, 0)
    out: dict[str, int] = {}
    for i in range(tlb.GetTypeInfoCount()):
        ti = tlb.GetTypeInfo(i)
        attr = ti.GetTypeAttr()
        if attr.typekind != pythoncom.TKIND_ENUM:
            continue
        for j in range(attr.cVars):
            vd = ti.GetVarDesc(j)  # PyVARDESC: memid, value, elemdescVar, wVarFlags, varkind
            out[ti.GetNames(vd.memid)[0]] = vd.value
    return out


def typelib_available(guid: str = CONSTANTS_TYPELIB) -> bool:
    """Есть ли библиотека в системе (Windows + pywin32 + установленный КОМПАС)."""
    try:
        read_enum_constants(guid)
    except Exception:
        return False
    return True
