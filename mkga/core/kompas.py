"""Подключение к запущенному КОМПАС-3D через COM (API5 и API7).

Работает только на Windows с установленным КОМПАСом и пакетом pywin32.
Импорт win32com отложен, поэтому остальной проект импортируется и на Linux.

ВАЖНО: GUID библиотек типов взяты из опубликованных примеров. GUID API7
подтверждён статьёй на GitHub (Weltraum/Article-Python-in-aid-of-the-designer-
Tames-API-Kompas-3D). GUID API5 и констант ещё надо проверить на реальной
машине с КОМПАСом v22-v25: здесь, без КОМПАСа, этот код не запускался.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

API7_TYPELIB = "{69AC2981-37C0-4379-84FD-5DD2F3C0A520}"
API5_TYPELIB = "{0422828C-F174-495E-AC5D-D31014DBBE87}"
CONSTANTS_TYPELIB = "{75C9F5D0-B5B8-4526-8681-9903C567D2ED}"


class KompasNotAvailable(RuntimeError):
    """КОМПАС или pywin32 недоступны."""


@dataclass
class Kompas:
    api5: Any            # KompasObject
    api7: Any            # IKompasAPIObject
    const5: Any          # константы API5 (ksConstants)
    app7: Any            # IApplication (api7.Application)

    @property
    def active_document(self):
        """Активный документ (API7) или None."""
        return self.app7.ActiveDocument

    def message(self, text: str) -> None:
        self.api5.ksMessage(text)


def connect(visible: bool = True) -> Kompas:
    try:
        import pythoncom
        from win32com.client import Dispatch, gencache
    except ImportError as e:  # не Windows или нет pywin32
        raise KompasNotAvailable("нужен Windows и пакет pywin32 (pip install pywin32)") from e

    try:
        m5 = gencache.EnsureModule(API5_TYPELIB, 0, 1, 0)
        m7 = gencache.EnsureModule(API7_TYPELIB, 0, 1, 0)
        const5 = gencache.EnsureModule(CONSTANTS_TYPELIB, 0, 1, 0).constants
        d5 = Dispatch("Kompas.Application.5")
        d7 = Dispatch("Kompas.Application.7")
        api5 = m5.KompasObject(
            d5._oleobj_.QueryInterface(m5.KompasObject.CLSID, pythoncom.IID_IDispatch)
        )
        api7 = m7.IKompasAPIObject(
            d7._oleobj_.QueryInterface(m7.IKompasAPIObject.CLSID, pythoncom.IID_IDispatch)
        )
    except Exception as e:  # pywintypes.com_error и пр.
        raise KompasNotAvailable(f"не удалось подключиться к КОМПАСу: {e}") from e

    app7 = api7.Application
    if visible:
        app7.Visible = True
    return Kompas(api5=api5, api7=api7, const5=const5, app7=app7)
