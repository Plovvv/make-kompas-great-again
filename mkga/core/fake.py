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
        self.DocumentType = 4  # ksDocumentPart
        self._top: FakePart7 | None = None
        self.Path = str(path) if path else ""
        self.saved_to: list[str] = []
        self.save_result = True  # False: имитировать отказ КОМПАСа
        self.closed_with: int | None = None
        self._owner: list | None = None  # список документов приложения (для Close)

    @property
    def TopPart(self) -> FakePart7:
        if self._top is None:
            self._top = FakePart7()
        return self._top

    def SaveAs(self, file_name: str) -> bool:
        if not self.save_result:
            return False
        Path(file_name).write_bytes(self.CONTENT)
        self.saved_to.append(file_name)
        return True

    def Save(self) -> bool:
        return self.SaveAs(self.Path) if self.Path else False

    def Close(self, close_options: int) -> bool:
        self.closed_with = close_options   # 0 = не сохранять, 1 = сохранить (DocumentCloseOptions)
        if self._owner is not None:
            self._owner.remove(self)
        return True


class FakeShape:
    """Объект эскиза или операции 3D: любые свойства записываются как атрибуты, вызовы запоминаются."""

    def __init__(self, kind: str, args: tuple = (), update_result: bool = True):
        self.kind, self.args, self.update_result = kind, args, update_result
        self.calls: list = []

    def Update(self) -> bool:
        self.calls.append("Update")
        return self.update_result

    def SetSideParameters(self, *args) -> bool:
        self.calls.append(("SetSideParameters", args))
        return True

    def _put_indexed_(self, name: str, *args) -> None:  # запись индексируемых свойств (см. model3d._put_indexed)
        self.calls.append(("put", name, args))


class FakeAdd:
    """Коллекция с методом Add (Circles, LineSegments, Extrusions и т. п.)."""

    def __init__(self, kind: str, owner: "FakePart7"):
        self.kind, self.owner = kind, owner

    def Add(self, *args) -> FakeShape:
        shape = FakeShape(self.kind, args, self.owner.update_result)
        self.owner.created.append(shape)
        return shape


class FakeView:
    def __init__(self, owner: "FakePart7"):
        self.Circles = FakeAdd("circle", owner)
        self.LineSegments = FakeAdd("line", owner)


class FakeSketch(FakeShape):
    def __init__(self, owner: "FakePart7"):
        super().__init__("sketch", (), owner.update_result)
        self.view, self.began, self.ended = FakeView(owner), False, False

    def BeginEdit(self):
        self.began = True
        views = type("Views", (), {"ActiveView": self.view})()
        return type("Fragment", (), {"ViewsAndLayersManager": type("M", (), {"Views": views})()})()

    def EndEdit(self) -> bool:
        self.ended = True
        return True


class _SketchCollection:
    def __init__(self, owner: "FakePart7"):
        self.owner = owner

    def Add(self) -> FakeSketch:
        sketch = FakeSketch(self.owner)
        self.owner.sketches.append(sketch)
        self.owner.created.append(sketch)
        return sketch


class FakePart7:
    """IPart7 без геометрии: записывает построение, а массу и плотность задаёт тест (fake_mass_g, Density)."""

    def __init__(self) -> None:
        self.created: list[FakeShape] = []
        self.sketches: list[FakeSketch] = []
        self.update_result = True      # False: имитировать отказ КОМПАСа построить операцию
        self.Name, self.Marking = "", ""
        self.Material, self.Density = "Сталь 10 ГОСТ 1050-2013", 7.856
        self.fake_mass_g = 0.0
        self.material_accepted = True
        self.Sketchs = _SketchCollection(self)
        self.Extrusions = FakeAdd("extrusion", self)
        self.Rotateds = FakeAdd("rotated", self)

    def DefaultObject(self, object_type: int):
        return ("default-object", object_type)

    def SetMaterial(self, name: str, density: float) -> bool:
        if not self.material_accepted:
            return False
        self.Material, self.Density = name, density
        return True

    def Update(self) -> bool:
        return False                   # как на реальном КОМПАСе: после успешного пересчёта бывает False

    @property
    def Mass(self) -> float:
        return self.fake_mass_g

    def features(self, kind: str) -> list[FakeShape]:
        return [s for s in self.created if s.kind == kind]


class FakeDocuments:
    """Коллекция Documents: Count, Item, Add (как на реальном КОМПАСе v24)."""

    def __init__(self, docs: list[FakeDocument]):
        self._docs = docs

    @property
    def Count(self) -> int:
        return len(self._docs)

    def Item(self, index: int) -> FakeDocument:
        return self._docs[index]

    def Add(self, doc_type: int, visible: bool = True) -> FakeDocument:
        doc = FakeDocument("")           # новый документ без имени, как в настоящем КОМПАСе
        doc.DocumentType = doc_type
        doc._owner = self._docs
        self._docs.append(doc)
        return doc


class FakeApp7:
    """IApplication: только то, что подтверждено на реальном КОМПАСе v24."""

    def __init__(self, version: tuple[int, int, int, int], documents: list[FakeDocument]):
        self._version = version
        self.documents = documents
        self.Documents = FakeDocuments(documents)
        for d in documents:
            d._owner = documents
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

    def __init__(self, study: bool = False, home: bool = False, spds: bool = False,
                 version: tuple[int, int, int, int] = (24, 0, 3, 0)) -> None:
        self.messages: list[str] = []
        self._version = version
        # свойства редакции (на реальном КОМПАСе это свойства API5, не методы)
        self.ksIsStudyVersion = study
        self.ksIsHomeVersion = home
        self.ksIsSpdsVersion = spds

    def ksMessage(self, text: str) -> None:
        self.messages.append(text)

    def ksGetSystemVersion(self, *outs) -> int:
        """Как настоящий метод API5: пишет версию в выходные параметры (.value), возвращает код результата."""
        for out, value in zip(outs, self._version):
            out.value = value
        return 1


def make_fake_kompas(
    version: tuple[int, int, int, int] = (24, 0, 3, 0),
    documents: list[FakeDocument] | None = None,
    study: bool = False,
    home: bool = False,
) -> Kompas:
    docs = list(documents or [])
    app7: Any = FakeApp7(version, docs)
    api7 = type("FakeApi7", (), {"Application": app7})()
    return Kompas(api5=_Recorder(study=study, home=home, version=version), api7=api7, app7=app7)
