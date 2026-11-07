#!/usr/bin/env python3
"""Линт форка autopilot-ls: каждая ссылка на файл навыка в SKILL.md, phases/ и prompts/ существует.

Запуск из корня репозитория:  python3 tools/lint-ls.py
Ссылка — путь в обратных кавычках вида phases/…, prompts/…, standards/…, tools/… (от каталога
навыка) или CHANGES-ls.md, docs/autopilot/… (от корня репозитория). Пути проекта (interfaces.md,
docs/standards/ub-mode.md проекта и т.п.) — не файлы навыка и не проверяются.
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "autopilot")
# Пути проекта, которые совпадают по виду с путями навыка: prompts/ проекта — промпты продукта.
PROJECT_PATHS = {"prompts/CHANGELOG.md"}
REF = re.compile(r"`((?:phases|prompts|standards|tools)/[\w.\-]+\.(?:md|py|html)|CHANGES-ls\.md|docs/autopilot/[\w.\-]+\.md)`")


def main():
    files = [os.path.join(SKILL, "SKILL.md")] + sorted(glob.glob(os.path.join(SKILL, "phases", "*.md"))) \
        + sorted(glob.glob(os.path.join(SKILL, "prompts", "*.md"))) + sorted(glob.glob(os.path.join(SKILL, "standards", "*.md")))
    bad, seen = [], set()
    for f in files:
        for n, line in enumerate(open(f, encoding="utf-8"), 1):
            for ref in REF.findall(line):
                if ref in PROJECT_PATHS:
                    continue
                base = ROOT if ref.startswith(("CHANGES", "docs/")) else SKILL
                seen.add(ref)
                if not os.path.exists(os.path.join(base, ref)):
                    bad.append("%s:%d → %s" % (os.path.relpath(f, ROOT), n, ref))
    phases = {os.path.basename(p) for p in glob.glob(os.path.join(SKILL, "phases", "*.md"))}
    table = open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8").read()
    unlisted = sorted(p for p in phases if "phases/%s" % p not in table and p not in table)
    print("ссылок проверено: %d, файлов: %d" % (len(seen), len(files)))
    for b in bad:
        print("! нет файла: " + b)
    for u in unlisted:
        print("! фаза не названа в SKILL.md: phases/" + u)
    return 1 if bad or unlisted else 0


if __name__ == "__main__":
    sys.exit(main())
