"""Вызовы интерфейсов КОМПАСа, которых нет в «основном» IDispatch объекта (проверено на КОМПАС-3D v24).

КОМПАС-объект реализует сразу несколько интерфейсов (например, `IPart7` и `IFeature7`, документ и
`IPropertyKeeper`, приложение и `IPropertyMng`), но его IDispatch при позднем связывании отдаёт
члены только основного. Остальные вызываются так: запросить нужный интерфейс (QueryInterface), найти
номер члена (memid) в библиотеке типов и вызвать Invoke с этим номером.

    faces = get(part, "IFeature7", "ModelObjects", 6)        # индексируемое свойство (чтение)
    ok = call(keeper, "IPropertyKeeper", "SetPropertyValue", prop, "текст", True)

Для фейкового КОМПАСа объект может иметь метод `_iface_(iface, kind, member, args)`: тогда вызов уходит туда
(kind: "call" | "get" | "put").
"""

from __future__ import annotations

from typing import Any

from .kompas import API7_TYPELIB, KompasError, com_errors

_INFO: dict[str, Any] | None = None


def _typeinfos() -> dict[str, Any]:
    global _INFO
    if _INFO is None:
        import pythoncom

        lib = pythoncom.LoadRegTypeLib(API7_TYPELIB, 1, 0, 0)
        _INFO = {lib.GetDocumentation(i)[0]: lib.GetTypeInfo(i) for i in range(lib.GetTypeInfoCount())}
    return _INFO


def _member_id(iface: str, member: str) -> int:
    ti = _typeinfos().get(iface)
    if ti is None:
        raise KompasError(f"интерфейс {iface} не найден в библиотеке типов КОМПАСа")
    attr = ti.GetTypeAttr()
    for i in range(attr.cFuncs):
        fd = ti.GetFuncDesc(i)
        if ti.GetNames(fd.memid)[0] == member:
            return fd.memid
    raise KompasError(f"у интерфейса {iface} нет члена {member}")


def _dispatch(obj, iface: str):
    import pythoncom

    attr = _typeinfos()[iface].GetTypeAttr()
    with com_errors(f"запрос интерфейса {iface}"):
        return obj._oleobj_.QueryInterface(attr.iid, pythoncom.IID_IDispatch)


def _raw(x):
    """COM-обёртка pywin32 -> «сырой» IDispatch для передачи параметром."""
    return getattr(x, "_oleobj_", x)


def _wrap(x):
    """Вернувшийся IDispatch -> обёртка с доступом по именам; остальное без изменений."""
    import pythoncom
    from win32com.client import dynamic

    if isinstance(x, pythoncom.TypeIIDs[pythoncom.IID_IDispatch]):
        return dynamic.Dispatch(x)
    if isinstance(x, tuple):
        return tuple(_wrap(i) for i in x)
    return x


def _invoke(obj, iface: str, kind: str, member: str, args: tuple):
    hook = getattr(obj, "_iface_", None)
    if hook is not None:  # фейковый КОМПАС
        return hook(iface, kind, member, args)
    import pythoncom

    flags = {"call": pythoncom.DISPATCH_METHOD, "get": pythoncom.DISPATCH_PROPERTYGET,
             "put": pythoncom.DISPATCH_PROPERTYPUT}[kind]
    disp = _dispatch(obj, iface)
    memid = _member_id(iface, member)
    with com_errors(f"{iface}.{member}"):
        return _wrap(disp.Invoke(memid, 0, flags, True, *(_raw(a) for a in args)))


def call(obj, iface: str, member: str, *args):
    """Метод интерфейса `iface` у объекта `obj`."""
    return _invoke(obj, iface, "call", member, args)


def get(obj, iface: str, member: str, *args):
    """Свойство (в том числе с параметрами) интерфейса `iface` на чтение."""
    return _invoke(obj, iface, "get", member, args)


def put(obj, iface: str, member: str, *args):
    """Свойство интерфейса `iface` на запись: последний аргумент это значение."""
    return _invoke(obj, iface, "put", member, args)


class _PlainOut:
    """Выходной параметр без COM (для фейкового КОМПАС на машине без pywin32): значение читается через `.value`."""

    value = 0.0


def out_doubles(count: int) -> list:
    """Выходные параметры типа double для метода с [out] (читаются через `.value`)."""
    try:
        import pythoncom
        from win32com.client import VARIANT
    except ImportError:                       # нет pywin32: настоящего КОМПАСа тоже нет, значения заполняет фейк
        return [_PlainOut() for _ in range(count)]
    return [VARIANT(pythoncom.VT_R8 | pythoncom.VT_BYREF, 0.0) for _ in range(count)]


def invoke_with_outs(obj, name: str, *args):
    """Метод основного интерфейса объекта с [out]-параметрами: передавайте `out_doubles(...)` как аргументы."""
    hook = getattr(obj, "_call_with_outs_", None)
    if hook is not None:
        return hook(name, *args)
    import pythoncom

    with com_errors(name):
        ids = obj._oleobj_.GetIDsOfNames(name)
        dispid = ids[0] if isinstance(ids, (tuple, list)) else ids
        return obj._oleobj_.Invoke(dispid, 0, pythoncom.DISPATCH_METHOD, True, *args)
