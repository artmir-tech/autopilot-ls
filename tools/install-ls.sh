#!/bin/sh
# Ставит форк autopilot-ls как навык Claude Code: копия skills/autopilot → ~/.claude/skills/autopilot-ls/.
# Установленный upstream-навык autopilot (если есть) не трогается: другой каталог, другое имя.
set -eu
SRC=$(cd "$(dirname "$0")/.." && pwd -P)/skills/autopilot
DST="${HOME}/.claude/skills/autopilot-ls"
mkdir -p "$DST"
rsync -a --delete --exclude '__pycache__' "$SRC/" "$DST/"
grep -q '^name: autopilot-ls$' "$DST/SKILL.md" && echo "autopilot-ls установлен: $DST"
[ -f "${HOME}/.claude/skills/ub-mode/SKILL.md" ] || echo "! ub-mode не установлен: ~/.claude/skills/ub-mode/SKILL.md"
