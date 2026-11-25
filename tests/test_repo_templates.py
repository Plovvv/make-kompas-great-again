"""Целостность шаблонов GitHub и ссылок в документации (без внешних библиотек YAML)."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORMS = sorted((ROOT / ".github" / "ISSUE_TEMPLATE").glob("*.yml"))
FORMS = [f for f in FORMS if f.name != "config.yml"]
ALLOWED_TYPES = {"markdown", "textarea", "input", "dropdown", "checkboxes"}


def label_names() -> set[str]:
    text = (ROOT / ".github" / "labels.yml").read_text(encoding="utf-8")
    return set(re.findall(r"^- name: (.+)$", text, re.M))


class IssueFormTests(unittest.TestCase):
    def test_forms_exist(self):
        self.assertGreaterEqual(len(FORMS), 4)
        self.assertTrue((ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml").exists())

    def test_each_form_is_structurally_valid(self):
        for f in FORMS:
            text = f.read_text(encoding="utf-8")
            with self.subTest(form=f.name):
                for key in ("name:", "description:", "body:"):
                    self.assertRegex(text, rf"(?m)^{key}", f"{f.name}: нет верхнего ключа {key}")
                types = re.findall(r"(?m)^  - type: (\w+)", text)
                self.assertTrue(types)
                self.assertTrue(set(types) <= ALLOWED_TYPES, f"{f.name}: неизвестный тип поля {set(types) - ALLOWED_TYPES}")
                ids = re.findall(r"(?m)^    id: (\w+)", text)
                self.assertEqual(len(ids), len(set(ids)), f"{f.name}: повторяющиеся id полей")
                blocks = re.split(r"(?m)^  - type: ", text)[1:]
                for block in blocks:
                    kind = block.split("\n", 1)[0].strip()
                    if kind != "markdown":
                        self.assertIn("label:", block, f"{f.name}: у поля типа {kind} нет label")
                        self.assertRegex(block, r"(?m)^    id: ", f"{f.name}: у поля типа {kind} нет id")
                self.assertNotIn("\t", text, f"{f.name}: табуляции недопустимы в YAML")

    def test_labels_used_by_forms_are_defined(self):
        defined = label_names()
        self.assertIn("bug", defined)
        for f in FORMS:
            m = re.search(r'(?m)^labels: \[(.*)\]', f.read_text(encoding="utf-8"))
            self.assertIsNotNone(m, f"{f.name}: нет labels")
            used = {x.strip().strip('"') for x in m.group(1).split(",")}
            self.assertTrue(used <= defined, f"{f.name}: метки {used - defined} не описаны в .github/labels.yml")

    def test_config_has_no_blank_issues_and_links_exist(self):
        text = (ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml").read_text(encoding="utf-8")
        self.assertIn("blank_issues_enabled: false", text)
        for rel in re.findall(r"/blob/main/(\S+)", text):
            self.assertTrue((ROOT / rel).exists(), f"config.yml ссылается на отсутствующий файл {rel}")


class PullRequestTemplateTests(unittest.TestCase):
    def test_checklist_covers_the_principles(self):
        text = (ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md").read_text(encoding="utf-8")
        for needle in ("Не убий", "Стабильность", "Открытость", "Проверяемость", "ctx.session", "mkga check",
                       "unittest", "MKGA_LIVE_KOMPAS", "verify-registry", "АСКОН"):
            self.assertIn(needle, text)
        self.assertGreaterEqual(text.count("- [ ]"), 12)


class DocumentationLinkTests(unittest.TestCase):
    def test_relative_markdown_links_resolve(self):
        files = [ROOT / n for n in ("README.md", "CLAUDE.md", "AGENTS.md", "CONTRIBUTING.md", "SECURITY.md")]
        files += sorted((ROOT / "docs").glob("*.md"))
        files += [ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md", ROOT / "mods" / "_template" / "README.md"]
        broken = []
        for f in files:
            if not f.exists():
                continue
            for target in re.findall(r"\]\(([^)\s]+)\)", f.read_text(encoding="utf-8")):
                if target.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                path = target.split("#", 1)[0]
                if path and not (f.parent / path).resolve().exists():
                    broken.append(f"{f.relative_to(ROOT)} -> {target}")
        self.assertEqual(broken, [])

    def test_new_docs_exist_and_are_linked_from_the_entry_points(self):
        for name in ("VERIFICATION.md", "COMPATIBILITY.md", "WRITING_MODS.md", "MODEL3D.md", "UI_STYLE.md"):
            self.assertTrue((ROOT / "docs" / name).exists(), name)
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        for name in ("CLAUDE.md", "PRINCIPLES.md", "WRITING_MODS.md", "MODEL3D.md", "UI_STYLE.md", "VERIFICATION.md"):
            self.assertIn(name, agents)


if __name__ == "__main__":
    unittest.main()
