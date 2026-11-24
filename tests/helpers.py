import json
import zipfile
from pathlib import Path


def good_manifest(**overrides):
    data = {
        "id": "demo-mod",
        "name": "Демо",
        "version": "1.2.3",
        "description": "Тестовый мод",
        "author": "tester",
        "license": "MIT",
        "kind": "macro",
        "entry": "main.py",
        "kompas_versions": [23, 24],
    }
    data.update(overrides)
    return data


def make_zip(path: Path, manifest: dict, *, main_py: str = "def run(ctx):\n    return 'ok'\n",
             prefix: str = "", extra: dict | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"{prefix}mkga-mod.json", json.dumps(manifest, ensure_ascii=False))
        zf.writestr(f"{prefix}main.py", main_py)
        for name, content in (extra or {}).items():
            zf.writestr(name, content)
    return path
