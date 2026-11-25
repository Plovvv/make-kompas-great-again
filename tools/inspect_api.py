"""Справочник по API КОМПАСа из установленной библиотеки типов (для разработчиков и ИИ).

    python tools/inspect_api.py find Extrusion          # найти интерфейсы по части имени
    python tools/inspect_api.py show IModelContainer    # методы и свойства интерфейса с параметрами
    python tools/inspect_api.py show IKompasDocument3D IPart7

Берёт данные из библиотеки типов API7, поэтому всегда соответствует вашей версии КОМПАСа.
Запускать КОМПАС не нужно, но он должен быть установлен.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mkga.console import ensure_utf8_output  # noqa: E402
from mkga.core.typelib import describe_interface, find_types  # noqa: E402


def main(argv: list[str]) -> int:
    ensure_utf8_output()
    if len(argv) < 2 or argv[0] not in ("find", "show"):
        print(__doc__)
        return 2
    if argv[0] == "find":
        for name in find_types(argv[1]):
            print(name)
        return 0
    for name in argv[1:]:
        try:
            for line in describe_interface(name):
                print(line)
        except KeyError as e:
            print(e, file=sys.stderr)
            return 1
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
