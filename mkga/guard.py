"""Страж правил (docs/PRINCIPLES.md, п. 1): ищет в коде модов прямые изменения файлов в обход
безопасной записи (mkga.core.safe_io, ctx.session).

Что считается нарушением: запись и удаление файлов (open с режимом записи, os.remove, shutil.rmtree,
Path.write_text, ...), запуск внешних программ (subprocess, os.system) и сохранение документов
КОМПАСа напрямую (Save, SaveAs, ...). Для документов есть Kompas.save_as(session, doc, path):
он сначала берёт путь под защиту, потом сохраняет.

Исключение: строка с комментарием `# mkga: allow-unsafe-io (причина)`. Такие места не падают
в проверке, но выводятся отдельным списком, чтобы их увидел рецензент.

ВАЖНО: это защита от случайных ошибок (своих и ИИ), а не от злого умысла. Её можно обойти
(getattr, exec и т.п.), поэтому настоящая защита от вредоносного кода это проверка мода
людьми перед попаданием в реестр.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

ALLOW_MARK = "mkga: allow-unsafe-io"

_WATCHED_MODULES = {"os", "shutil", "subprocess", "io"}
_OS_FUNCS = {
    "remove", "unlink", "rmdir", "removedirs", "rename", "renames", "replace", "truncate",
    "chmod", "chown", "open", "system", "popen", "startfile",
}
_SHUTIL_FUNCS = {
    "rmtree", "move", "copy", "copy2", "copyfile", "copytree", "copymode", "copystat",
    "chown", "make_archive", "unpack_archive",
}
# Методы любых объектов (в первую очередь pathlib.Path).
_PATH_METHODS = {
    "write_text", "write_bytes", "unlink", "rmdir", "rename", "touch",
    "symlink_to", "hardlink_to", "link_to", "chmod",
}
# Сохранение документов КОМПАСа (API7 и API5).
_KOMPAS_SAVE_EXACT = {"Save", "ksSaveDocument", "ksSaveDocumentEx", "SaveDocument"}
_MODE_CHARS = set("rwxabt+U")


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    message: str
    allowed: bool = False  # помечено `# mkga: allow-unsafe-io`

    def __str__(self) -> str:
        tag = "РАЗРЕШЕНО, нужен ревью" if self.allowed else "НАРУШЕНИЕ"
        return f"{self.file}:{self.line}: {tag}: {self.message}"


def _is_write_mode(mode: str) -> bool:
    return any(c in mode for c in "wax+")


class _Visitor(ast.NodeVisitor):
    def __init__(self, filename: str, lines: list[str]):
        self.filename = filename
        self.lines = lines
        self.modules: dict[str, str] = {}   # локальное имя -> модуль («o» -> «os»)
        self.funcs: dict[str, str] = {}     # локальное имя -> «os.remove»
        self.sessions: set[str] = set()     # имена, связанные с ctx.session(...) / store.begin(...)
        self.findings: dict[tuple[int, int], Finding] = {}

    # --- сессии safe_io: их методы write_text/delete и т.п. разрешены -------------
    @staticmethod
    def _is_session_call(expr: ast.expr | None) -> bool:
        return (isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute)
                and expr.func.attr in ("session", "begin"))

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            if self._is_session_call(item.context_expr) and isinstance(item.optional_vars, ast.Name):
                self.sessions.add(item.optional_vars.id)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        if self._is_session_call(node.value):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    self.sessions.add(t.id)
        self.generic_visit(node)

    # --- импорты -----------------------------------------------------------------
    def visit_Import(self, node: ast.Import) -> None:
        for a in node.names:
            top = a.name.split(".")[0]
            if top in _WATCHED_MODULES:
                self.modules[a.asname or top] = top

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module in _WATCHED_MODULES:
            for a in node.names:
                self.funcs[a.asname or a.name] = f"{node.module}.{a.name}"

    # --- вызовы ------------------------------------------------------------------
    def visit_Call(self, node: ast.Call) -> None:
        self._check(node)
        self.generic_visit(node)

    def _qualname(self, func: ast.expr) -> str | None:
        if isinstance(func, ast.Name):
            return self.funcs.get(func.id, func.id)
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            mod = self.modules.get(func.value.id)
            if mod:
                return f"{mod}.{func.attr}"
        return None

    def _report(self, node: ast.Call, message: str) -> None:
        line = self.lines[node.lineno - 1] if node.lineno <= len(self.lines) else ""
        self.findings.setdefault(
            (node.lineno, node.col_offset),
            Finding(self.filename, node.lineno, message, allowed=ALLOW_MARK in line),
        )

    def _check_open_mode(self, node: ast.Call, mode_index: int, what: str) -> None:
        mode_node = node.args[mode_index] if len(node.args) > mode_index else None
        for kw in node.keywords:
            if kw.arg == "mode":
                mode_node = kw.value
        if mode_node is None:
            return  # режим по умолчанию: чтение
        if isinstance(mode_node, ast.Constant) and isinstance(mode_node.value, str):
            if _is_write_mode(mode_node.value):
                self._report(node, f"{what} в режиме записи ({mode_node.value!r}): используйте ctx.session()")
        else:
            self._report(node, f"{what}: режим открытия не определить по коду, используйте константу")

    def _check(self, node: ast.Call) -> None:
        func = node.func
        qual = self._qualname(func)
        if qual in ("open", "io.open"):
            self._check_open_mode(node, 1, "open()")
        elif qual and qual.startswith("os.") and qual[3:] in _OS_FUNCS:
            self._report(node, f"{qual}(): прямое изменение файлов или запуск программ, используйте ctx.session()")
        elif qual and qual.startswith("shutil.") and qual[7:] in _SHUTIL_FUNCS:
            self._report(node, f"{qual}(): прямое изменение файлов, используйте ctx.session()")
        elif qual and qual.startswith("subprocess."):
            self._report(node, f"{qual}(): запуск внешних программ запрещён без явного разрешения")
        elif isinstance(func, ast.Attribute):
            if isinstance(func.value, ast.Name) and func.value.id in self.sessions:
                return  # вызов метода сессии safe_io: это и есть правильный путь
            name = func.attr
            if name in _PATH_METHODS:
                self._report(node, f".{name}(): прямое изменение файлов, используйте ctx.session()")
            elif name == "open":
                # Path.open(mode): режим первым аргументом. Строку, не похожую на режим
                # (например адрес для webbrowser.open), не считаем режимом.
                first = node.args[0] if node.args else None
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    if set(first.value) <= _MODE_CHARS and _is_write_mode(first.value):
                        self._report(node, f".open({first.value!r}): запись, используйте ctx.session()")
                elif any(kw.arg == "mode" for kw in node.keywords):
                    self._check_open_mode(node, 99, ".open()")
            elif name in _KOMPAS_SAVE_EXACT or name.startswith("SaveAs") or name.startswith("ksSave"):
                self._report(
                    node,
                    f".{name}(): прямое сохранение документа КОМПАСа, используйте Kompas.save_as(session, doc, path)",
                )


def check_source(source: str, filename: str = "<string>") -> list[Finding]:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as e:
        return [Finding(filename, e.lineno or 0, f"файл не разобрать: {e.msg}")]
    v = _Visitor(filename, source.splitlines())
    v.visit(tree)
    return sorted(v.findings.values(), key=lambda f: f.line)


def check_path(path: str | Path) -> list[Finding]:
    """Проверить все .py под путём (файл или папка)."""
    p = Path(path)
    files = [p] if p.is_file() else sorted(p.rglob("*.py"))
    out: list[Finding] = []
    for f in files:
        out.extend(check_source(f.read_text(encoding="utf-8"), str(f)))
    return out


def violations(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if not f.allowed]
