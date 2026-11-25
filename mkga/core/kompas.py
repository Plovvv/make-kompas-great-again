"""Подключение к запущенному КОМПАС-3D через COM (API5 и API7).

Работает только на Windows с установленным КОМПАСом и пакетом pywin32.
Импорт win32com отложен, поэтому остальной проект импортируется и на Linux.

Проверено на КОМПАС-3D v24 (24.0.3.0): GUID библиотек типов зарегистрированы в системе,
подключение и чтение версии работают. На v25 и учебной редакции не проверялось.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from . import versions

API7_TYPELIB = "{69AC2981-37C0-4379-84FD-5DD2F3C0A520}"
API5_TYPELIB = "{0422828C-F174-495E-AC5D-D31014DBBE87}"
CONSTANTS_TYPELIB = "{75C9F5D0-B5B8-4526-8681-9903C567D2ED}"


class KompasError(RuntimeError):
    """Любая ошибка при работе с КОМПАСом, с сообщением, понятным пользователю."""


class KompasNotAvailable(KompasError):
    """КОМПАС или pywin32 недоступны."""


class KompasVersionError(KompasError):
    """Версия КОМПАСа не подходит модулю или пользователь не подтвердил запуск."""


# Частые коды COM-ошибок (HRESULT) и что они значат для пользователя.
_COM_HINTS = {
    -2147023174: "КОМПАС закрыт или не отвечает (RPC-сервер недоступен)",
    -2147417848: "КОМПАС был закрыт во время работы",
    -2147418111: "КОМПАС занят (открыто модальное окно или идёт расчёт): закройте окно и повторите",
    -2147417846: "КОМПАС занят: повторите через несколько секунд",
    -2147221021: "КОМПАС не запущен",
}


def describe_com_error(e: BaseException) -> str:
    """Короткое понятное описание COM-ошибки (pywintypes.com_error) с кодом HRESULT."""
    code = e.args[0] if e.args and isinstance(e.args[0], int) else None
    hint = _COM_HINTS.get(code)
    text = e.args[1] if len(e.args) > 1 and isinstance(e.args[1], str) else ""
    parts = [hint or text or str(e)]
    if code is not None:
        parts.append(f"код 0x{code & 0xFFFFFFFF:08X}")
    return ", ".join(parts)


@contextmanager
def com_errors(what: str) -> Iterator[None]:
    """Превращает COM-ошибки в KompasError с понятным текстом: `with com_errors("чтение документа"):`."""
    try:
        yield
    except KompasError:
        raise
    except Exception as e:
        if type(e).__name__ == "com_error":
            raise KompasError(f"{what}: {describe_com_error(e)}") from e
        raise


@contextmanager
def com_thread() -> Iterator[None]:
    """Подготовить ПОТОК к работе с COM: `with com_thread(): ...` (нужно в рабочих потоках окна).

    COM-объекты привязаны к потоку, где созданы: подключаться к КОМПАСу и работать с ним нужно
    в одном и том же потоке. Без pywin32 ничего не делает (тесты, Linux).
    """
    try:
        import pythoncom
    except ImportError:
        yield
        return
    pythoncom.CoInitialize()
    try:
        yield
    finally:
        pythoncom.CoUninitialize()


@dataclass
class Kompas:
    api5: Any            # KompasObject
    api7: Any            # IKompasAPIObject
    app7: Any            # IApplication (api7.Application)

    @property
    def constants(self):
        """Константы КОМПАСа (mkga.core.constants): не зависят от COM и кэша gen_py."""
        from . import constants
        return constants

    def _edition_flag(self, name: str) -> bool:
        with com_errors("чтение редакции КОМПАСа"):
            return bool(getattr(self.api5, name))

    @property
    def is_study(self) -> bool:
        """Учебная версия КОМПАСа (API5 ksIsStudyVersion). На полной v24 даёт False (проверено)."""
        return self._edition_flag("ksIsStudyVersion")

    @property
    def is_home(self) -> bool:
        """Домашняя версия (API5 ksIsHomeVersion). На полной v24 даёт False (проверено)."""
        return self._edition_flag("ksIsHomeVersion")

    @property
    def is_spds(self) -> bool:
        """Версия со СПДС (API5 ksIsSpdsVersion). На полной v24 даёт False (проверено)."""
        return self._edition_flag("ksIsSpdsVersion")

    @property
    def active_document(self):
        """Активный документ (API7) или None."""
        with com_errors("чтение активного документа"):
            return self.app7.ActiveDocument

    @property
    def version(self) -> tuple[int, int, int, int]:
        """Версия КОМПАСа: (major, minor, release, build), например (24, 0, 3, 0).

        Проверено на КОМПАС-3D v24: GetSystemVersion() возвращает (True, 24, 0, 3, 0).
        """
        with com_errors("чтение версии КОМПАСа"):
            ok, major, minor, release, build = self.app7.GetSystemVersion()
        if not ok:
            raise KompasNotAvailable("КОМПАС не сообщил свою версию")
        return major, minor, release, build

    def supports(self, feature: str) -> bool:
        """Есть ли возможность в этой версии КОМПАСа (таблица core/versions.py)."""
        return versions.supports(feature, self.version)

    def save_as(self, session, doc, path: str | Path) -> None:
        """Сохранить документ в новый файл: ЕДИНСТВЕННЫЙ разрешённый для модов способ.

        Путь сначала берётся под защиту сессии (снимок существующего файла), потом
        сохраняет сам КОМПАС. При предпросмотре (dry_run) ничего не сохраняется.
        Если КОМПАС отказал, бросается KompasError, а сессия откатывается.
        """
        p = Path(path)
        session.track(p)
        if session.dry_run:
            return
        with com_errors(f"сохранение {p.name}"):
            ok = doc.SaveAs(str(p.resolve()))
        if ok is False:
            raise KompasError(f"КОМПАС не смог сохранить документ в {p}")

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
        from win32com.client import dynamic
    except ImportError as e:  # не Windows или нет pywin32
        raise KompasNotAvailable("нужен Windows и пакет pywin32 (pip install pywin32)") from e

    launched = False

    def get(progid: str):
        # Позднее связывание (dynamic): не нужен кэш gen_py, ничего не пишется в профиль
        # пользователя. Проверено на v24: API7 (GetSystemVersion, Documents) и API5 работают.
        nonlocal launched
        try:
            unk = pythoncom.GetActiveObject(progid)
        except pythoncom.com_error:
            if not launch:
                raise KompasNotAvailable(
                    "КОМПАС не запущен. Откройте КОМПАС-3D и повторите."
                ) from None
            launched = True
            return dynamic.Dispatch(progid)
        return dynamic.Dispatch(unk.QueryInterface(pythoncom.IID_IDispatch))

    try:
        api5 = get("Kompas.Application.5")
        api7 = get("Kompas.Application.7")
        app7 = api7.Application
        if launched:
            app7.Visible = True
    except KompasNotAvailable:
        raise
    except Exception as e:  # pywintypes.com_error и пр.
        raise KompasNotAvailable(f"не удалось подключиться к КОМПАСу: {e}") from e

    return Kompas(api5=api5, api7=api7, app7=app7)
