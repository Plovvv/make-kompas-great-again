"""Чтение констант из зарегистрированной в системе библиотеки типов КОМПАСа.

Нужно только разработчикам: генератору `tools/gen_constants.py` и тесту сверки. Работе модов это
не требуется (константы лежат в готовом `mkga.core.constants`). Не использует кэш gen_py:
читает перечисления (enum) прямо из библиотеки типов через pythoncom. Нужны Windows, pywin32
и установленный КОМПАС (он регистрирует библиотеки).
"""

from __future__ import annotations

from .kompas import CONSTANTS_TYPELIB

CONSTANTS3D_TYPELIB = "{2CAF168C-7961-4B90-9DA2-701419BEEFE3}"  # Kompas6Constants3D (ksConstants3D.tlb)


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


def read_enums(guid: str = CONSTANTS3D_TYPELIB, major: int = 1, minor: int = 0) -> dict[str, dict[str, int]]:
    """Перечисления библиотеки по именам: {«ksDirectionTypeEnum»: {«dtNormal»: 0, ...}, ...}."""
    import pythoncom

    tlb = pythoncom.LoadRegTypeLib(guid, major, minor, 0)
    out: dict[str, dict[str, int]] = {}
    for i in range(tlb.GetTypeInfoCount()):
        ti = tlb.GetTypeInfo(i)
        attr = ti.GetTypeAttr()
        if attr.typekind != pythoncom.TKIND_ENUM:
            continue
        members = {}
        for j in range(attr.cVars):
            vd = ti.GetVarDesc(j)
            members[ti.GetNames(vd.memid)[0]] = vd.value
        out[tlb.GetDocumentation(i)[0]] = members
    return out


def typelib_available(guid: str = CONSTANTS_TYPELIB) -> bool:
    """Есть ли библиотека в системе (Windows + pywin32 + установленный КОМПАС)."""
    try:
        read_enum_constants(guid)
    except Exception:
        return False
    return True


# --- описание интерфейсов (для разработчиков и ИИ: «какие методы у IExtrusion?») -----------------

_VT = {2: "short", 3: "int", 4: "float", 5: "double", 8: "BSTR", 9: "IDispatch", 11: "bool", 12: "VARIANT",
       13: "IUnknown", 16: "char", 17: "byte", 18: "ushort", 19: "uint", 20: "int64", 22: "int", 23: "uint",
       24: "void", 25: "HRESULT", 7: "DATE", 6: "CURRENCY", 10: "SCODE", 21: "uint64"}
_BOILERPLATE = {"QueryInterface", "AddRef", "Release", "GetTypeInfoCount", "GetTypeInfo", "GetIDsOfNames", "Invoke"}
_INVKIND = {1: "метод", 2: "свойство (чтение)", 4: "свойство (запись)", 8: "свойство (запись ссылки)"}


def _type_name(ti, typedesc) -> str:
    """Читаемое имя типа из TYPEDESC: ссылки на другие типы разворачиваются, указатели помечаются *."""
    import pythoncom

    # простой тип это число (VT_I4), составной (указатель, ссылка на тип, массив) это кортеж (vt, вложенное)
    if isinstance(typedesc, int):
        return _VT.get(typedesc, f"vt{typedesc}")
    vt, inner = typedesc[0], (typedesc[1] if len(typedesc) > 1 else None)
    if vt == pythoncom.VT_PTR:
        return _type_name(ti, inner) + "*"
    if vt == pythoncom.VT_SAFEARRAY:
        return _type_name(ti, inner) + "[]"
    if vt == pythoncom.VT_USERDEFINED:
        try:
            return ti.GetRefTypeInfo(inner).GetDocumentation(-1)[0]
        except pythoncom.com_error:
            return f"ссылка:{inner}"
    return _VT.get(vt, f"vt{vt}")


def describe_interface(name: str, guid: str = "{69AC2981-37C0-4379-84FD-5DD2F3C0A520}",
                       major: int = 1, minor: int = 0) -> list[str]:
    """Строки с описанием интерфейса из библиотеки типов (по умолчанию API7).

        Метод:   Add(ObjectType: int) -> IExtrusion*          (параметры: in / out / in,out)
        Свойство чтения и записи показываются отдельными строками.

    Нужен установленный КОМПАС. Найти интерфейсы по части имени: find_types("Extrusion").
    """
    import pythoncom

    tlb = pythoncom.LoadRegTypeLib(guid, major, minor, 0)
    for i in range(tlb.GetTypeInfoCount()):
        if tlb.GetDocumentation(i)[0] != name:
            continue
        ti = tlb.GetTypeInfo(i)
        attr = ti.GetTypeAttr()
        lines = [f"{name}  ({attr.cFuncs} членов)"]
        for j in range(attr.cFuncs):
            fd = ti.GetFuncDesc(j)
            names = ti.GetNames(fd.memid)
            if names[0] in _BOILERPLATE:
                continue
            params = []
            for pname, elem in zip(names[1:], fd.args):
                flags = elem[1]
                direction = ("in," if flags & 1 else "") + ("out" if flags & 2 else "")
                direction = direction.rstrip(",") or "in"
                params.append(f"{pname}: {_type_name(ti, elem[0])} [{direction}]")
            ret = _type_name(ti, fd.rettype[0] if isinstance(fd.rettype, tuple) else fd.rettype) if fd.rettype else "?"
            lines.append(f"  {names[0]}({', '.join(params)}) -> {ret}   [{_INVKIND.get(fd.invkind, fd.invkind)}]")
        return lines
    raise KeyError(f"интерфейс {name!r} не найден в библиотеке типов")


def find_types(part: str, guid: str = "{69AC2981-37C0-4379-84FD-5DD2F3C0A520}", major: int = 1,
               minor: int = 0) -> list[str]:
    """Имена типов библиотеки, содержащие `part` (без учёта регистра): быстрый поиск нужного интерфейса."""
    import pythoncom

    tlb = pythoncom.LoadRegTypeLib(guid, major, minor, 0)
    needle = part.lower()
    return sorted({tlb.GetDocumentation(i)[0] for i in range(tlb.GetTypeInfoCount())
                   if needle in tlb.GetDocumentation(i)[0].lower()})
