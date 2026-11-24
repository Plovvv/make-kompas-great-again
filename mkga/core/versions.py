"""Политика версий КОМПАСа (docs/PRINCIPLES.md, раздел «Версии КОМПАСа»).

Мод в манифесте перечисляет версии, на которых он ПРОВЕРЕН (`kompas_versions`). Ядро сверяет
с ними реальную версию запущенного КОМПАСа:

  версия из списка                                      -> OK, запуск без вопросов
  новее самой новой проверенной или «дырка» в списке    -> WARN, нужно подтверждение пользователя
  список пуст (мод не заявил проверенных версий)        -> WARN
  старше самой старой проверенной                       -> REFUSE, запуск отменяется

Различия между версиями (что в какой версии появилось) собираются в таблице FEATURES. Мод
не сравнивает номера версий сам, а спрашивает Kompas.supports("имя"). Таблицу пополняем только
подтверждёнными фактами: версию, в которой появилась возможность, нельзя угадывать.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

OK, WARN, REFUSE = "ok", "warn", "refuse"

# имя возможности -> первая версия КОМПАСа (major), где она подтверждённо есть.
# Пока пусто: нет подтверждённых фактов. Пример записи: "some_feature": 23
FEATURES: dict[str, int] = {}


@dataclass(frozen=True)
class VersionVerdict:
    level: str      # ok | warn | refuse
    message: str


def format_version(version: Sequence[int]) -> str:
    return ".".join(str(p) for p in version)


def check_version(version: Sequence[int], tested: Sequence[int]) -> VersionVerdict:
    """Оценить версию КОМПАСа `version` (major, minor, release, build) по списку проверенных major."""
    major = version[0]
    shown = format_version(version)
    if not tested:
        return VersionVerdict(
            WARN,
            f"Мод не указывает, на каких версиях КОМПАСа он проверен. У вас КОМПАС {shown}: поведение не проверено.",
        )
    if major in tested:
        return VersionVerdict(OK, f"КОМПАС {shown}: версия проверена для этого мода.")
    low, high = min(tested), max(tested)
    listed = ", ".join(f"v{v}" for v in sorted(tested))
    if major < low:
        return VersionVerdict(
            REFUSE,
            f"Мод проверен на КОМПАС {listed}, а у вас более старый КОМПАС {shown}. Запуск отменён.",
        )
    if major > high:
        return VersionVerdict(
            WARN,
            f"Мод проверен на КОМПАС {listed}, а у вас более новый КОМПАС {shown}: поведение не проверено.",
        )
    return VersionVerdict(
        WARN,
        f"Мод проверен на КОМПАС {listed}, но не на вашей версии {shown}: поведение не проверено.",
    )


def supports(feature: str, version: Sequence[int], table: dict[str, int] | None = None) -> bool:
    """Есть ли возможность `feature` в версии КОМПАСа. Неизвестное имя это ошибка (опечатка)."""
    table = FEATURES if table is None else table
    if feature not in table:
        raise ValueError(f"неизвестная возможность {feature!r}; известные: {sorted(table) or 'нет'}")
    return version[0] >= table[feature]
