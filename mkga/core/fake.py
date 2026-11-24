"""Фейковый КОМПАС: для тестов, CI и запуска модов без КОМПАСа (`mkga run-dev --fake-kompas`).

Это настоящий класс Kompas, но вместо COM-объектов в нём простые заглушки. Поэтому код ядра и
модов (версия, активный документ, save_as) выполняется тот же самый. Фейк НЕ заменяет проверку
на реальном КОМПАСе: он повторяет только то, что мы подтвердили на v24.

    k = make_fake_kompas(version=(24, 0, 3, 0), documents=[FakeDocument("Деталь.m3d")])
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .kompas import Kompas


class FakeDocument:
    """Документ-заглушка. SaveAs/Save записывают маленький файл, чтобы откат можно было проверить."""

    CONTENT = b"FAKE-KOMPAS-DOCUMENT"

    def __init__(self, name: str = "Документ1.m3d", path: str | Path | None = None):
        self.Name = name
        self.Path = str(path) if path else ""
        self.saved_to: list[str] = []
        self.save_result = True  # False: имитировать отказ КОМПАСа

    def SaveAs(self, file_name: str) -> bool:
        if not self.save_result:
            return False
        Path(file_name).write_bytes(self.CONTENT)
        self.saved_to.append(file_name)
        return True

    def Save(self) -> bool:
        return self.SaveAs(self.Path) if self.Path else False


class FakeApp7:
    """IApplication: только то, что подтверждено на реальном КОМПАСе v24."""

    def __init__(self, version: tuple[int, int, int, int], documents: list[FakeDocument]):
        self._version = version
        self.documents = documents
        self.active: FakeDocument | None = documents[0] if documents else None
        self.Visible = True

    @property
    def ActiveDocument(self) -> FakeDocument | None:
        return self.active

    def GetSystemVersion(self):
        return (True, *self._version)

    def ApplicationName(self, full_name: bool = True) -> str:
        return f"КОМПАС-3D v{self._version[0]}" if full_name else "KOMPAS-3D"


class _Recorder:
    """Заглушка API5: запоминает вызовы ksMessage и т.п. Остальное не подтверждено, не выдумываем."""

    def __init__(self, study: bool = False, home: bool = False, spds: bool = False) -> None:
        self.messages: list[str] = []
        # свойства редакции (на реальном КОМПАСе это свойства API5, не методы)
        self.ksIsStudyVersion = study
        self.ksIsHomeVersion = home
        self.ksIsSpdsVersion = spds

    def ksMessage(self, text: str) -> None:
        self.messages.append(text)


def make_fake_kompas(
    version: tuple[int, int, int, int] = (24, 0, 3, 0),
    documents: list[FakeDocument] | None = None,
    study: bool = False,
    home: bool = False,
) -> Kompas:
    docs = list(documents or [])
    app7: Any = FakeApp7(version, docs)
    api7 = type("FakeApi7", (), {"Application": app7})()
    return Kompas(api5=_Recorder(study=study, home=home), api7=api7, app7=app7)
