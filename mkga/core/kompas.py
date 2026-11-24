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

    @property
    def version(self) -> tuple[int, int, int, int]:
        """Версия КОМПАСа: (major, minor, release, build), например (24, 0, 3, 0).

        Проверено на КОМПАС-3D v24: GetSystemVersion() возвращает (True, 24, 0, 3, 0).
        """
        ok, major, minor, release, build = self.app7.GetSystemVersion()
        if not ok:
            raise KompasNotAvailable("КОМПАС не сообщил свою версию")
        return major, minor, release, build

    def message(self, text: str) -> None:
        """Показать модальное окно КОМПАСа. НЕ использовать в модах.

        Окно блокирует и КОМПАС, и вызывающий код, пока пользователь его не
        закроет (см. docs/PRINCIPLES.md, п. 1.6). Для сообщений есть ctx.log.
        """
        self.api5.ksMessage(text)


def connect(launch: bool = False) -> Kompas:
    """Подключиться к КОМПАСу.

    По умолчанию присоединяется только к УЖЕ ЗАПУЩЕННОМУ КОМПАСу (проверено на v24:
    запущенный КОМПАС виден в таблице запущенных объектов под Kompas.Application.5
    и .7). Если он не запущен, будет понятная ошибка, а новый экземпляр НЕ создаётся:
    он не видит документы пользователя и занимает лицензию (docs/PRINCIPLES.md, п. 1).

    launch=True разрешает запустить новый экземпляр через COM; в этом случае окно
    КОМПАСа делается видимым.
    """
    try:
        import pythoncom
        from win32com.client import Dispatch, GetActiveObject, gencache
    except ImportError as e:  # не Windows или нет pywin32
        raise KompasNotAvailable("нужен Windows и пакет pywin32 (pip install pywin32)") from e

    launched = False

    def get(progid: str):
        nonlocal launched
        try:
            return GetActiveObject(progid)
        except pythoncom.com_error:
            if not launch:
                raise KompasNotAvailable(
                    "КОМПАС не запущен. Откройте КОМПАС-3D и повторите."
                ) from None
            launched = True
            return Dispatch(progid)

    try:
        # EnsureModule пишет кэш типов в %TEMP%\gen_py (в планах: отказаться от gencache).
        gencache.EnsureModule(API5_TYPELIB, 0, 1, 0)
        gencache.EnsureModule(API7_TYPELIB, 0, 1, 0)
        const5 = gencache.EnsureModule(CONSTANTS_TYPELIB, 0, 1, 0).constants
        api5 = get("Kompas.Application.5")
        api7 = get("Kompas.Application.7")
        app7 = api7.Application
        if launched:
            app7.Visible = True
    except KompasNotAvailable:
        raise
    except Exception as e:  # pywintypes.com_error и пр.
        raise KompasNotAvailable(f"не удалось подключиться к КОМПАСу: {e}") from e

    return Kompas(api5=api5, api7=api7, const5=const5, app7=app7)
