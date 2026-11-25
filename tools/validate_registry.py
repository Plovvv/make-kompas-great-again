"""Проверка registry/registry.json (запускается в CI и перед pull request)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mkga.console import ensure_utf8_output  # noqa: E402
from mkga.registry import RegistryError, load_registry  # noqa: E402


def main() -> int:
    ensure_utf8_output()  # в CI на Windows вывод идёт не в UTF-8
    path = Path(__file__).resolve().parent.parent / "registry" / "registry.json"
    try:
        entries = load_registry(path)
    except RegistryError as e:
        print(f"registry.json: {e}", file=sys.stderr)
        return 1
    print(f"registry.json: OK, записей: {len(entries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
