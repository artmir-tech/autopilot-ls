#!/usr/bin/env python3
"""Учёт прогона Autopilot: состояние, дашборд, сервер — одной командой на событие.

Агент не правит .autopilot/state.js руками. Каждое событие прогона — один вызов:

    python3 .autopilot/ap.py init --slug S --title "…" --mode semi --depth normal \\
                                  --memory-file AGENTS.md --memory-owner autopilot --skill-dir /abs
    python3 .autopilot/ap.py stage spec                 # открыть этап (прошлые закроются сами)
    python3 .autopilot/ap.py stage briefing skip --note "полный автомат — самобрифинг"
    python3 .autopilot/ap.py set tier=T2 baseCommit=a1b2c3d
    python3 .autopilot/ap.py tickets                    # опубликовать таски из <dir>/tickets/*.md
    python3 .autopilot/ap.py check-plan                 # гейт G3: трасса манифест ↔ таски
    python3 .autopilot/ap.py ticket 02 03 start         # волна ушла
    python3 .autopilot/ap.py ticket 02 review
    python3 .autopilot/ap.py ticket 02 repair --note "пустой адрес проходит — R01.1"
    python3 .autopilot/ap.py ticket 02 done --tests 34/0 --commit a1b2c3d
    python3 .autopilot/ap.py ticket 03 retry | fail --note "…" | reset   # retry и repair — не больше двух
    python3 .autopilot/ap.py ticket 03 reset --by-user "«давай ещё раз, ключ добавил»"   # упавший — только так
    python3 .autopilot/ap.py stage build done | fail --note "…"
    python3 .autopilot/ap.py add concerns "src/notify.ts:40 — два формата даты"
    python3 .autopilot/ap.py add debt.emptyEnv TELEGRAM_BOT_TOKEN
    python3 .autopilot/ap.py coverage found=2 fixed=1 deferred=1 --item "R07 — отложено: …"
    python3 .autopilot/ap.py add report "Два формата даты в уведомлениях — оставлено"
    python3 .autopilot/ap.py blind checked=12 matched=11 --mismatch "R07 — статус не виден"   # два раза за прогон
    python3 .autopilot/ap.py tests 34/0                 # последний полный прогон
    python3 .autopilot/ap.py ask briefing --note "три вопроса в чате"   # ждём пользователя
    python3 .autopilot/ap.py answered                   # ответил (stage/ticket закрывают сами)
    python3 .autopilot/ap.py finish --result "Бот принимает заявки и пишет их в таблицу"
    python3 .autopilot/ap.py finish --result "…" --by-user "«сдавай как есть»"   # если finish отказал
    python3 .autopilot/ap.py reopen                     # второй бриф в сданном прогоне
    python3 .autopilot/ap.py commits                    # коммиты сданных тасков ещё в истории?
    python3 .autopilot/ap.py                            # просто синхронизировать

Форк autopilot-ls, команды всего проекта (state.js им не нужен):

    python3 .autopilot/ap.py scout verify | check       # гейт GS: что брать готовым
    python3 .autopilot/ap.py arch start | round --file F [--kind confirm|delta|as-built] | status | delta | waive
    python3 .autopilot/ap.py program [check | plan --result "…" | P05 block --note "…" | P05 pending]
    python3 .autopilot/ap.py project [now | change | spend | next-list | url | run | lint]
    python3 .autopilot/ap.py question add | answer N --by-user "…" | list
    python3 .autopilot/ap.py manual add KEY | done KEY --by-user "…"

После каждой команды: updatedAt = сейчас (и метка в журнале beats), строка в ленте log,
счётчики и список требований — из manifest.md, гейты G1–G4 — из событий, которые их решают,
пройденные этапы закрыты, снимок вписан в dashboard.html, сервер жив. Время
ставит сам скрипт, с секундами и поясом, — агент его не пишет никогда.

Флаги: --check-update (сверить версию навыка с GitHub), --no-serve, --stop, --help.
Работает на macOS, Linux и Windows (в том числе из Git Bash).
"""

import datetime as dt
import glob
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

for _s in (sys.stdout, sys.stderr):                       # cp1251-консоль Windows
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

A = os.path.dirname(os.path.abspath(__file__))          # .autopilot этого проекта
ROOT = os.path.dirname(A)
STATE = os.path.join(A, "state.js")
PAGE = os.path.join(A, "dashboard.html")
README = os.path.join(A, "README.md")
PIDF = os.path.join(A, "serve.pid")
LOG = os.path.join(A, "serve.log")
BEGIN, END = "/*STATE-BEGIN*/", "/*STATE-END*/"
WIN = os.name == "nt"
REPO = "nick-vels/skills"
REMOTE_SKILL = "https://raw.githubusercontent.com/%s/main/skills/autopilot/SKILL.md" % REPO
STOP_DELAY = 12
BEATS_KEPT = 2000
LOG_KEPT = 300
QUOTE_MAX = 240
WAIT_KINDS = ("briefing", "spec", "plan", "action", "stop")
# Команды, которые значат «работа пошла дальше»: ожидание пользователя ими закрывается,
# даже если `answered` забыли.
MOVES_ON = {"stage", "ticket", "tickets", "check-plan", "coverage", "blind", "tests", "finish", "reopen"}
ORDER = ["preflight", "manifest", "briefing", "scout", "architecture", "spec", "plan", "build", "review", "final"]
# Этап, чей результат лежит на диске, пройден — даже если его забыли отметить.
ARTIFACT = {"manifest": "manifest.md", "spec": "spec.md", "plan": "tickets/*.md"}
TICKET_STATUSES = {"start": "in-progress", "review": "review", "repair": "repair",
                   "done": "done", "fail": "failed", "retry": "in-progress", "reset": "pending",
                   "await": "awaiting_owner"}      # форк: промпт ждёт владельца (phases/5-prompts.md)
LISTS = {"concerns", "additions", "report", "debt.placeholders", "debt.assumptions", "debt.emptyEnv"}


def now():
    return dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def die(msg):
    print("ошибка: " + msg)
    sys.exit(1)


# ── состояние ───────────────────────────────────────────────────────────────

def read_state():
    try:
        raw = open(STATE, encoding="utf-8").read()
    except FileNotFoundError:
        return None
    body = raw.split("=", 1)[1] if "=" in raw.split("\n", 1)[0] else raw
    try:
        return json.loads(body.strip().rstrip(";"))
    except json.JSONDecodeError as e:
        die("state.js не разбирается (строка %d: %s) — перезапиши его командой init "
            "или поправь строку" % (e.lineno, e.msg))


def save(state):
    state["rev"] = (state.get("rev") or 0) + 1        # дашборд перерисовывается по нему
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("window.STATE =\n" + json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, STATE)


def beat(state):
    """Журнал пульса: каждое событие оставляет метку. updatedAt перезаписывается,
    и без журнала дашборд знал о прошлых событиях, только если сам их видел, —
    уснул экран или упал сервер, и рабочее время между редкими метками
    обрезалось как простой."""
    beats = state.setdefault("beats", [])
    if state["updatedAt"] not in beats:
        beats.append(state["updatedAt"])
    del beats[:-BEATS_KEPT]


def log(state, event, **kw):
    """Лента событий для дашборда: что случилось, словами страницы, а не агента.
    Пишет скрипт сам, по команде, — от агента ничего сверх обычного вызова не нужно."""
    entry = {"t": state["updatedAt"], "k": event}
    entry.update({k: v for k, v in kw.items() if v not in (None, "", [])})
    state.setdefault("log", []).append(entry)
    del state["log"][:-LOG_KEPT]


def set_gate(state, g, ok, **kw):
    """Гейт решается событием, которое его проверяет: G1 — манифестом (refresh_g1),
    G2 — coverage, G3 — check-plan, G4 — blind. Повторная проверка перезаписывает."""
    rec = {"ok": bool(ok), "at": state["updatedAt"]}
    rec.update({k: v for k, v in kw.items() if v is not None})
    state.setdefault("gates", {})[g] = rec
    log(state, "gate", g=g, ok=bool(ok), **kw)


def close_wait(state):
    """Ожидание пользователя кончилось: интервал уходит в waits — часы дашборда
    его не считают, это не работа сборки."""
    w = state.get("waiting")
    if not w:
        return
    state.setdefault("waits", []).append({"kind": w.get("kind"), "from": w.get("since"),
                                          "to": state["updatedAt"]})
    state["waiting"] = None
    log(state, "answered", kind=w.get("kind"))


def run_dir(state):
    return os.path.join(A, state.get("dir") or "")


def fresh_state(a):
    t = now()
    return {
        "version": 2,
        "slug": a["slug"], "dir": "%s-%s--wip" % (t[:10], a["slug"]),
        "title": a.get("title") or a["slug"],
        "mode": a.get("mode") or "semi", "depth": a.get("depth") or "normal",
        "tier": None, "briefFile": a.get("brief-file"),
        "memoryFile": a.get("memory-file") or "AGENTS.md",
        "memoryOwner": a.get("memory-owner") or "autopilot",
        "skillDir": a.get("skill-dir"), "baseCommit": None,
        "startedAt": t, "updatedAt": t, "finishedAt": None,
        "stages": [{"id": "preflight", "status": "active", "startedAt": t}]
                  + [{"id": s, "status": "pending"} for s in ORDER[1:]],
        "requirements": {"total": 0, "done": 0, "inTicket": 0, "inSpec": 0,
                         "placeholder": 0, "deferred": 0, "dropped": 0},
        "tickets": [], "tests": None,
        "debt": {"placeholders": [], "assumptions": [], "emptyEnv": []},
        "additions": [], "coverage": None, "concerns": [], "blind": None, "beats": [t],
        "rev": 0, "waiting": None, "waits": [], "log": [], "reqList": [], "gates": {}, "result": None,
    }


# ── манифест и таски ────────────────────────────────────────────────────────

ROW_ID = re.compile(r"^[RGD]\d+[a-z]?$")
PIPE = re.compile(r"(?<!\\)\|")          # «\|» внутри цитаты — не граница колонки


def cells_of(line):
    return PIPE.split(line.strip().strip("|"))
STATUS_KEY = {"done": "done", "in-ticket": "inTicket", "in-spec": "inSpec",
              "placeholder": "placeholder", "deferred": "deferred", "dropped": "dropped"}


def plain(cell):
    """Ячейка манифеста как текст для страницы: без разметки, «\\|» — обратно в «|»."""
    t = re.sub(r"\*+|`", "", cell.replace("\\|", "|")).strip()
    return t if len(t) <= QUOTE_MAX else t[:QUOTE_MAX - 1].rstrip() + "…"


def manifest_table(state):
    """Строки manifest.md: ID в первой колонке, цитата во второй, статус в третьей,
    основание в четвёртой."""
    try:
        text = open(os.path.join(run_dir(state), "manifest.md"), encoding="utf-8").read()
    except OSError:
        return None
    rows = []
    for line in text.splitlines():
        raw = cells_of(line)
        cells = [c.strip().strip("`*") for c in raw]
        if len(cells) >= 3 and ROW_ID.match(cells[0]):
            rows.append({"id": cells[0], "text": plain(raw[1]) if len(raw) > 1 else "",
                         "status": cells[2].split()[0].lower() if cells[2] else "open",
                         "why": plain(raw[3]) if len(raw) > 3 else ""})
    return rows


def manifest_rows(state):
    """[(id, status)] из таблицы manifest.md."""
    rows = manifest_table(state)
    return None if rows is None else [(r["id"], r["status"]) for r in rows]


def refresh_g1(state, create=False):
    """G1 решает манифест, а его правят и после спецификации: гейт идёт за таблицей,
    иначе остаётся красным про вопросы, которых давно нет, — или зелёным про закрытые,
    которые открылись снова."""
    g = (state.get("gates") or {}).get("G1")
    if g is None and not create:
        return
    rows = [r for r in manifest_table(state) or [] if not r["id"].startswith("D")]
    if not rows:
        return
    n = sum(1 for r in rows if r["status"] == "open")
    if g is None or (g["ok"], g.get("open")) != (n == 0, n):
        set_gate(state, "G1", n == 0, open=n, total=len(rows))
    else:
        g["total"] = len(rows)


def recount(state):
    table = manifest_table(state)
    if table is None:
        return
    refresh_g1(state)
    # Список для страницы — слова пользователя и что с ними стало. Основание нужно
    # только там, где требование не сделано как написано.
    state["reqList"] = [dict({"id": r["id"], "text": r["text"], "status": r["status"]},
                             **({"why": r["why"]} if r["status"] in ("placeholder", "deferred", "dropped")
                                and r["why"] not in ("", "—", "-") else {}))
                        for r in table if not r["id"].startswith("D")]
    rows = [(r["id"], r["status"]) for r in table]
    rows = [(i, st) for i, st in rows if not i.startswith("D")]   # D## — ограничение, не требование
    r = {"total": len(rows), "done": 0, "inTicket": 0, "inSpec": 0,
         "placeholder": 0, "deferred": 0, "dropped": 0}
    for _, st in rows:
        if st in STATUS_KEY:
            r[STATUS_KEY[st]] += 1
    state["requirements"] = r


def manifest_update(state, changes):
    """Переписывает статус (третья колонка) и «Где» (пятая) у строк манифеста.
    changes: {id: (статус, добавка к «Где»)}. Возвращает список изменённых id."""
    path = os.path.join(run_dir(state), "manifest.md")
    try:
        lines = open(path, encoding="utf-8").read().split("\n")
    except OSError:
        return []
    touched = []
    for n, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            continue
        cells = cells_of(line)
        rid = cells[0].strip().strip("`*") if cells else ""
        if rid not in changes or len(cells) < 3:
            continue
        status, where = changes[rid]
        cells[2] = " %s " % status
        if where and len(cells) >= 5:
            cur = cells[4].strip()
            cells[4] = " %s " % (where if cur in ("", "—", "-") else
                                 cur if where in cur else "%s → %s" % (cur, where))
        lines[n] = "|" + "|".join(cells) + "|"
        touched.append(rid)
    if touched:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    return touched


FIELD = re.compile(r"^\*\*([^*:]+):?\*\*:?\s*(.*)$")


def parse_ticket(path):
    text = open(path, encoding="utf-8").read()
    base = os.path.basename(path)
    tid = re.match(r"(\w+?)[-_.]", base)
    tid = tid.group(1) if tid else base[:2]
    title = ""
    f = {}
    for line in text.splitlines():
        s = line.strip()
        if not title and s.startswith("# "):
            title = re.sub(r"^#\s*\w+\s*[—–-]\s*", "", s).strip() or s[2:]
        m = FIELD.match(s)
        if m:
            f[m.group(1).strip().lower()] = m.group(2).strip()

    def ids(v):
        return [x for x in re.findall(r"[A-Za-z]*\d+[a-z]?(?:\.\d+)?", v or "")]

    def get(*names):
        for n in names:
            if n in f:
                return f[n]
        return ""
    wave = re.search(r"\d+", get("волна", "wave"))
    return {
        "id": tid, "title": title,
        "requirements": ids(get("требования", "requirements")),
        "blockedBy": re.findall(r"[A-Za-z]*\d+[a-z]?", get("зависит от", "blocked by")),
        "wave": int(wave.group()) if wave else None,
        "zone": re.findall(r"`([^`]+)`", get("зона", "zone")),
        "review": get("ревью", "review") or None,
        "model": get("модель", "model").lower() or None,
        "type": get("тип", "type").lower() or None,
        "effort": get("усилие", "effort").lower() or None,
        "attention": get("внимание", "attention").lower() or None,
        "architecture": get("архитектура", "architecture") or None,
        "night_ok": yes_no(get("ночью", "night")),
    }


# ── форк autopilot-ls: поля таска, лестница моделей, проверки ──────────────
# Всё, что форк добавил к учёту, — в этом блоке и в cmd_ls_*: так upstream вливается
# без раскопок. Правила — phases/4-plan.md (поля), 5-repair.md (лестница).

LS_FIELDS = (("type", "Тип", ("code", "prompt", "migration", "e2e", "infra")),
             ("model", "Модель", ("opus", "sonnet", "haiku")),
             ("effort", "Усилие", ("low", "medium", "high", "xhigh")),
             ("attention", "Внимание", ("none", "review", "owner")))
LADDER = [("haiku", "low"), ("sonnet", "medium"), ("opus", "high"), ("opus", "xhigh")]
LS_KEEP = ("attempts", "gates", "base", "session")


def yes_no(v):
    """«Ночью: да/нет» → True/False; пусто или непонятно → None (check-plan скажет)."""
    v = (v or "").strip().lower()
    return True if v in ("да", "yes", "true") else False if v in ("нет", "no", "false") else None


def ls_field_problems(t):
    out = []
    for key, name, allowed in LS_FIELDS:
        v = t.get(key)
        if not v:
            out.append("у таска %s нет поля %s" % (t["id"], name))
        elif v not in allowed:
            out.append("таск %s: %s «%s» — не из %s" % (t["id"], name, v, " | ".join(allowed)))
    if t.get("night_ok") is None:
        out.append("у таска %s нет поля Ночью (да | нет)" % t["id"])
    elif t["night_ok"] and t.get("attention") == "owner":
        out.append("таск %s: «Ночью: да» при «Внимание: owner» — ночью владельца нет" % t["id"])
    return out


def ls_wave_problems(tickets):
    out = []
    for m in [t for t in tickets if t.get("type") == "migration" and t.get("wave") is not None]:
        mates = [t["id"] for t in tickets if t is not m and t.get("wave") == m["wave"]]
        if mates:
            out.append("таск %s (migration) делит волну %s с %s — миграция летит одна"
                       % (m["id"], m["wave"], ", ".join(mates)))
    return out


PROMPT_ZONE = ("prompts/", "evals/")


def ls_zone_problems(t):
    """prompts/** — только prompt-таскам; prompt-таск — только prompts/ и evals/ (phases/5-prompts.md)."""
    out = []
    for z in t.get("zone") or []:
        z = z.lstrip("./")
        inside = z.startswith(PROMPT_ZONE) or z.rstrip("/") + "/" in PROMPT_ZONE
        if t.get("type") == "prompt" and not inside:
            out.append("таск %s (prompt) пишет в %s — prompt-таск правит только prompts/ и evals/" % (t["id"], z))
        elif t.get("type") != "prompt" and z.startswith("prompts/"):
            out.append("таск %s (%s) пишет в %s — зона промптов только у prompt-тасков"
                       % (t["id"], t.get("type") or "?", z))
    return out


def ls_night_row_problems(state, tickets):
    """«Ночью: да» при открытом требовании — ночью некому ответить (phases/4-plan.md, «Night»)."""
    rows = dict(manifest_rows(state) or [])
    return ["таск %s: «Ночью: да», а %s ещё open — вопрос владельцу не закрыт" % (t["id"], r)
            for t in tickets if t.get("night_ok")
            for r in sorted({x.split(".")[0] for x in t.get("requirements", [])}) if rows.get(r) == "open"]


def ls_plan_problems(state, tickets):
    return ([p for t in tickets for p in ls_field_problems(t) + ls_zone_problems(t)]
            + ls_wave_problems(tickets) + ls_night_row_problems(state, tickets)
            + ls_arch_ticket_problems(tickets))


# ── форк autopilot-ls: ночная очередь (phases/5-night.md) ──────────────────

def queue_skip_reason(t, by, queued, dropped):
    if t["id"] in dropped:
        return dropped[t["id"]]
    if t.get("status") == "failed":
        return "упал"
    if not t.get("night_ok"):
        return "Ночью: нет"
    if t.get("status") not in (None, "pending"):
        return "в работе"
    for b in t.get("blockedBy") or []:
        if not landed(by.get(b) or {}) and b not in queued:
            return "ждёт %s" % b
    return None


def landed(tk):
    """Влит и не в ремонте: сдан, или на точечном ревью с коммитом — на нём уже строят."""
    return tk.get("status") == "done" or (tk.get("status") == "review" and bool(tk.get("commit")))


def build_queue(state):
    """Очередь ночи: ночные таски, чьи родители сданы или стоят в очереди раньше, по волнам."""
    q = state.get("queue") or {}
    dropped = q.get("dropped") or {}
    tickets = [t for t in state.get("tickets") or [] if t.get("status") != "done"]
    by = {t["id"]: t for t in state.get("tickets") or []}
    queued, skipped = [], []
    for t in sorted(tickets, key=lambda x: (x.get("wave") or 99, x["id"])):
        why = queue_skip_reason(t, by, queued, dropped)
        if why:
            skipped.append({"id": t["id"], "why": why})
        else:
            queued.append(t["id"])
    state["queue"] = {"tickets": queued, "skipped": skipped, "dropped": dropped, "builtAt": state["updatedAt"]}
    return ["в очереди %d%s" % (len(queued), (": " + ", ".join(queued)) if queued else "")] + \
           ["мимо: %s — %s" % (s["id"], s["why"]) for s in skipped]


def cmd_queue(state, pos, opt):
    if pos[:1] == ["drop"]:
        if not pos[1:] or not isinstance(opt.get("note"), str):
            die("queue drop <id…> --note \"почему не ночью\"")
        q = state.setdefault("queue", {})
        q.setdefault("dropped", {}).update({i: opt["note"] for i in pos[1:]})
    elif pos:
        die("queue | queue drop <id…> --note \"…\"")
    notes = build_queue(state)
    log(state, "queue", n=len(state["queue"]["tickets"]))
    return notes


def night_start(state, n):
    """Новая ночь — или продолжение той, что встала на паузу по окну. Ночь, остановленная
    падением или недельным капом, до утреннего отчёта (`night end`) не перезапускается."""
    if n.get("status") == "stopped":
        die("ночь остановлена (%s) — сначала отчёт и `night end --report …`, потом новая ночь"
            % (n.get("stop") or "?"))
    notes = build_queue(state)
    if n.get("status") in ("paused", "running"):
        n.update(status="running", resume_at=None)
        notes.append("ночь продолжается: сделано %d" % len(n.get("done") or []))
    else:
        state["night"] = {"date": state["updatedAt"][:10], "status": "running", "startedAt": state["updatedAt"],
                          "done": [], "failed": [], "stop": None, "report": None,
                          "weekly_at_start": (state.get("pacing") or {}).get("weekly_used_pct")}
    log(state, "night", act="start", n=len(state["queue"]["tickets"]))
    return notes


def cmd_night(state, pos, opt):
    act = pos[0] if pos else ""
    n = state.get("night") or {}
    if act == "start":
        return night_start(state, n)
    if act == "stop" and isinstance(opt.get("note"), str) and n:
        n.update(status="stopped", stop=opt["note"])
    elif act == "end" and isinstance(opt.get("report"), str) and n:
        n.update(status="finished", endedAt=state["updatedAt"], report=opt["report"])
    else:
        die("night start | night stop --note \"…\" | night end --report night-<дата>.md")
    log(state, "night", act=act)
    return []


def ls_night_guard(state, act, ids):
    """Ночью летит только очередь, и после первого упавшего — ничего (phases/5-night.md)."""
    n = state.get("night") or {}
    if n.get("status") not in ("running", "stopped", "paused") or act not in ("start", "retry"):
        return
    if n["status"] == "stopped":
        die("ночь остановлена (%s) — новых запусков до утра нет: отчёт и `night end`" % (n.get("stop") or "?"))
    if n["status"] == "paused":
        die("ночь на паузе до %s (окно лимитов) — запусков нет, пока продолжение не скажет `night start`"
            % (n.get("resume_at") or "сброса окна"))
    q = set((state.get("queue") or {}).get("tickets") or [])
    outside = [i for i in ids if i not in q]
    if outside:
        die("ночью летит только очередь: %s не в ней — `queue` покажет почему" % ", ".join(outside))


# ── форк autopilot-ls: пейсинг лимитов (phases/5-subagents.md, «Pacing») ───

EST_BY_RUNG = {("haiku", "low"): 2, ("sonnet", "medium"): 5, ("opus", "high"): 10, ("opus", "xhigh"): 14}
PACING_KEYS = {"window": "window_used_pct", "weekly": "weekly_used_pct", "reserve": "reserve_pct",
               "night-weekly-max-pct": "night_weekly_max_pct"}
WINDOW_TWO, WINDOW_STOP, SHARE = 60, 85, 0.8
WEEK_TWO, WEEK_STOP = 80, 95        # окна 5 ч нет (часть тарифов) — темп по неделе


def pace_basis(p):
    """(занято %, порог «двое», порог «стоп», название, ключ сброса): окно 5 ч, а без него — неделя."""
    if p.get("window_used_pct") is not None:
        return p["window_used_pct"], WINDOW_TWO, WINDOW_STOP, "окно", "window_reset_at"
    if p.get("weekly_used_pct") is not None:
        return p["weekly_used_pct"], WEEK_TWO, WEEK_STOP, "неделя", "weekly_reset_at"
    return None, WINDOW_TWO, WINDOW_STOP, "окно", "window_reset_at"


def num(v):
    try:
        f = float(str(v).replace(",", ".").rstrip("%"))
    except ValueError:
        die("pacing: «%s» — не число" % v)
    return int(f) if f == int(f) else f


def ticket_est(p, tk):
    if str(tk["id"]) in (p.get("est_cost_by_ticket") or {}):
        return p["est_cost_by_ticket"][str(tk["id"])]
    last = (tk.get("attempts") or [{}])[-1]
    rung = LADDER[rung_of(last.get("model") or tk.get("model"), last.get("effort") or tk.get("effort"))]
    return EST_BY_RUNG[rung]


def pacing_room(p):
    used = pace_basis(p)[0] or 0
    return round(SHARE * (100 - used - p.get("reserve_pct", 15)))


def resume_at(p, key="window_reset_at"):
    try:
        t = dt.datetime.fromisoformat(p.get(key) or "")
    except ValueError:
        return None
    return (t + dt.timedelta(minutes=5)).isoformat(timespec="seconds")


def pacing_verdict(state, p):
    used, two, stop, name, reset_key = pace_basis(p)
    used = used or 0
    head = "" if name == "окно" else "окна 5 ч нет — темп по неделе: "
    if used >= stop:
        out = ["%sстоп: %s %s %% — новых запусков нет; летящие довести до посадки, синк, продолжить в %s"
               % (head, name, used, resume_at(p, reset_key) or "сброс + 5 мин")]
    else:
        out = ["%s%s %s %% · в полёте не больше %d · место под таск %d %%"
               % (head, name, used, 2 if used > two else 3, pacing_room(p))]
    n = state.get("night") or {}
    if n.get("status") != "running":
        return out
    spent = (p.get("weekly_used_pct") or 0) - (n.get("weekly_at_start") or 0)
    cap = p.get("night_weekly_max_pct", 15)
    if n.get("weekly_at_start") is not None and spent >= cap:
        n.update(status="stopped", stop="неделя +%s %% из %s %%" % (spent, cap))
        out.append("стоп ночи: неделя +%s %% из %s %%" % (spent, cap))
    elif used >= stop and name == "окно":
        n.update(status="paused", resume_at=resume_at(p))
    elif used >= stop:
        n.update(status="stopped", stop="неделя %s %%" % used)
    return out


def cmd_pacing(state, pos, opt, multi):
    """Окно лимитов из get_usage (или measure-run.py) — в state.js.pacing; вердикт — сколько
    в полёт и влезает ли таск. Решает арифметика, а не настроение длинного прогона."""
    p = state.setdefault("pacing", {})
    p.setdefault("reserve_pct", 15)
    for flag, key in PACING_KEYS.items():
        if opt.get(flag) not in (None, True):
            p[key] = num(opt[flag])
    for flag, key in (("reset", "window_reset_at"), ("weekly-reset", "weekly_reset_at"), ("source", "source")):
        if isinstance(opt.get(flag), str):
            p[key] = opt[flag]
    for pair in multi.get("est", []):
        k, eq, v = pair.partition("=")
        if not eq:
            die("pacing --est 03=8 — оценка таска в процентах окна")
        p.setdefault("est_cost_by_ticket", {})[k] = num(v)
    p["at"] = state["updatedAt"]
    if pos[:1] == ["check"]:
        known = {t["id"]: t for t in state.get("tickets") or []}
        room = pacing_room(p)
        return ["%s %s·%s ≈%s %% — %s (место %d %%)"
                % (i, known[i].get("model"), known[i].get("effort"), ticket_est(p, known[i]),
                   "можно" if ticket_est(p, known[i]) <= room else "нельзя", room)
                for i in pos[1:] if i in known]
    log(state, "pacing", window=p.get("window_used_pct"), weekly=p.get("weekly_used_pct"))
    return pacing_verdict(state, p)


# ── форк autopilot-ls: воркеры-сессии (phases/5-sessions.md, экспериментально) ──

LEASE_HOURS = 2


def record_session(state, tk, act, opt):
    if act != "start" or not isinstance(opt.get("session"), str):
        return
    until = dt.datetime.fromisoformat(state["updatedAt"]) + dt.timedelta(hours=LEASE_HOURS)
    tk["session"] = {"id": opt["session"], "name": opt.get("name") if isinstance(opt.get("name"), str) else None,
                     "lease_until": until.isoformat(timespec="seconds")}


def read_status(state, tid):
    try:
        return json.load(open(os.path.join(run_dir(state), "status", "%s.json" % tid), encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_board(state):
    """Доска для режима dispatch: sessions — вне worktree воркеров, пишет только ap.py
    оркестратора: учёт из state.js плюс то, что воркер сам сказал в status/NN.json."""
    if state.get("dispatch") != "sessions" or not state.get("dir"):
        return
    rows = []
    for t in state.get("tickets") or []:
        s, st = t.get("session") or {}, read_status(state, t["id"])
        rows.append({"id": t["id"], "status": t.get("status"), "worker_status": st.get("status"),
                     "session_id": s.get("id"), "name": s.get("name"), "branch": st.get("branch"),
                     "worktree": st.get("worktree"), "lease_until": s.get("lease_until"),
                     "attempts": t.get("attempts") or [], "model": t.get("model"), "effort": t.get("effort")})
    path = os.path.join(run_dir(state), "board.json")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump({"updatedAt": state["updatedAt"], "tickets": rows}, f, ensure_ascii=False, indent=2)
    os.replace(path + ".tmp", path)


# ── форк autopilot-ls: e2e L2 (phases/8a-e2e.md) ───────────────────────────

def cmd_e2e(state, pos, multi):
    """Прогон L2 — числа целиком или ничего, как у blind: пропавшее число — не ноль."""
    d = {}
    for p in pos:
        k, eq, v = p.partition("=")
        if not eq or k not in ("dialogues", "passed", "usd"):
            die("e2e dialogues=N passed=M usd=X [--regression \"…\"]")
        d[k] = num(v)
    if set(d) != {"dialogues", "passed", "usd"}:
        die("e2e: нужны все три — dialogues=N passed=M usd=X")
    d.update(regressions=multi.get("regression", []), at=state["updatedAt"])
    state["e2e"] = d
    log(state, "e2e", n=d["dialogues"], ok=d["passed"])
    return ["L2: %s из %s, $%s%s" % (d["passed"], d["dialogues"], d["usd"],
                                    " · регрессий %d" % len(d["regressions"]) if d["regressions"] else "")]


# ── форк autopilot-ls: программа прогонов (phases/0-program.md) ────────────

PROGRAM = os.path.join(A, "program.md")
PROGRAM_ROW = re.compile(r"^\|\s*P\d+[a-z]?\s*\|")


def program_lines():
    try:
        return open(PROGRAM, encoding="utf-8").read().splitlines()
    except OSError:
        return None


def int_of(cell):
    m = re.search(r"\d+", cell)
    return int(m.group()) if m else None


def blank(cell):
    return "" if cell in ("", "—", "-") else cell


def program_rows(lines):
    rows = []
    for i, line in enumerate(lines):
        if PROGRAM_ROW.match(line):
            got = [x.strip() for x in cells_of(line)]
            c = got + [""] * 12
            rows.append({"i": i, "n": len(got), "id": c[0], "title": c[1], "deps": re.findall(r"P\d+[a-z]?", c[2]),
                         "status": c[3], "dir": c[4].strip("`"), "result": c[5],
                         "tickets": int_of(c[6]), "days": int_of(c[7]), "plain": blank(c[8]), "gives": blank(c[9]),
                         "started": blank(c[10]), "landed": blank(c[11])})
    return rows


def program_set(pid, status, d=None, result=None, **plan):
    """Строка программы меняется только здесь: статус, папка, итог, факт дат и число тасков."""
    lines = program_lines()
    if lines is None:
        return "! программы нет — .autopilot/program.md"
    hit = [r for r in program_rows(lines) if r["id"] == pid]
    if not hit:
        return "! в программе нет %s" % pid
    r = hit[0]
    cells = [r["id"], r["title"], ", ".join(r["deps"]) or "—", status,
             "`%s`" % d if d else (("`%s`" % r["dir"]) if r["dir"] not in ("", "—") else "—"),
             result or r["result"] or "—"]
    if r["n"] > 6:
        r.update(plan)
        cells += [str(r[k]) if r[k] else "—" for k in ("tickets", "days", "plain", "gives", "started", "landed")]
    lines[r["i"]] = "| " + " | ".join(cells) + " |"
    with open(PROGRAM, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return "программа: %s → %s" % (pid, status)


def cmd_program(pos, opt, multi=None):
    if pos[:1] == ["plan"]:
        return cmd_program_plan(opt)
    if pos[:1] == ["check"]:
        problems = program_problems(read_state())
        return ["! " + p for p in problems] or ["мастер-план сходится: прогонов %d" % len(program_rows(program_lines()))]
    lines = program_lines()
    if lines is None:
        die("программы нет — .autopilot/program.md пишется по phases/0-program.md")
    if len(pos) >= 2 and pos[1] in ("block", "pending"):
        if pos[1] == "block" and not isinstance(opt.get("note"), str):
            die("program P03 block --note \"что блокирует\"")
        return [program_set(pos[0], "blocked" if pos[1] == "block" else "pending",
                            result=opt.get("note") if isinstance(opt.get("note"), str) else None)]
    rows = program_rows(lines)
    landed = {r["id"] for r in rows if r["status"] == "landed"}
    out, nxt = [], None
    for r in rows:
        if r["status"] == "blocked":
            out.append("%s blocked — %s" % (r["id"], r["result"]))
        elif r["status"] == "pending":
            wait = [d for d in r["deps"] if d not in landed]
            if wait:
                out.append("%s ждёт %s" % (r["id"], ", ".join(wait)))
            elif nxt is None:
                nxt = r
    head = ("следующий: %s — %s" % (nxt["id"], nxt["title"])) if nxt else (
        "программа сдана" if rows and all(r["status"] == "landed" for r in rows) else "следующего нет")
    flying = [r["id"] for r in rows if r["status"] == "in-flight"]
    return [head] + (["в работе: " + ", ".join(flying)] if flying else []) + out


# ── форк autopilot-ls: поиск готового (phases/2a-scout.md) ──────────────────

PRIOR_ART = os.path.join(A, "prior-art.json")
SCOUT_DECISIONS = ("adopt", "adapt", "fork", "learn", "build")
# Что можно подключить зависимостью и что можно копировать в свой код. Всё остальное — только изучать.
LICENSE_COPY = {"MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "ISC", "0BSD", "Unlicense", "Zlib"}
LICENSE_DEP = LICENSE_COPY | {"MPL-2.0", "LGPL-2.1", "LGPL-3.0", "PSF-2.0", "Python-2.0"}
SCOUT_STALE_DAYS = 540


def scout_read():
    try:
        with open(PRIOR_ART, encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return None
    except ValueError as e:
        die("prior-art.json не разбирается: %s" % e)


def scout_write(data):
    tmp = PRIOR_ART + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PRIOR_ART)


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "autopilot-ls", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def repo_json(repo):
    try:
        r = subprocess.run(["gh", "api", "repos/" + repo], capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return json.loads(r.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    try:
        return fetch_json("https://api.github.com/repos/" + repo)
    except (OSError, ValueError):
        return None


def repo_facts(repo):
    """Лицензия, живость и сам факт существования — из GitHub, а не из памяти модели."""
    data = repo_json(repo)
    if not isinstance(data, dict) or "full_name" not in data:
        return None
    return {"license": (data.get("license") or {}).get("spdx_id") or "none",
            "stars": data.get("stargazers_count"), "pushedAt": (data.get("pushed_at") or "")[:10],
            "archived": bool(data.get("archived")), "checkedAt": now()[:10]}


def package_exists(ref):
    """pypi:aiogram · npm:grammy. True / False / None (реестр не ответил или экосистема не из этих двух)."""
    eco, _, name = ref.partition(":")
    template = {"pypi": "https://pypi.org/pypi/%s/json", "npm": "https://registry.npmjs.org/%s"}.get(eco)
    if not template or not name:
        return None
    try:
        fetch_json(template % urllib.parse.quote(name, safe="@/"))
        return True
    except urllib.error.HTTPError as e:
        return False if e.code == 404 else None
    except (OSError, ValueError):
        return None


def scout_candidates(data):
    for p in data.get("products") or []:
        yield p
    for c in data.get("capabilities") or []:
        for x in c.get("candidates") or []:
            yield x


def cmd_scout_verify(data):
    out = []
    for x in scout_candidates(data):
        if not text_of(x.get("repo")):
            out.append("! кандидат без поля repo: %s" % (x.get("what") or x))
            continue
        facts = repo_facts(x["repo"])
        if facts is None:
            x.pop("facts", None)
            out.append("! %s: GitHub такого репозитория не знает — убери кандидата" % x["repo"])
            continue
        if text_of(x.get("package")):
            facts["package"] = package_exists(x["package"])
            if facts["package"] is False:
                out.append("! %s: в реестре нет пакета %s — убери его" % (x["repo"], x["package"]))
        x["facts"] = facts
    data.pop("checked", None)
    scout_write(data)
    n = sum(1 for x in scout_candidates(data) if x.get("facts"))
    return out + ["проверено кандидатов: %d" % n]


def scout_candidate_problems(label, decision, x):
    facts = x.get("facts")
    if not facts:
        return ["%s: %s не проверен — scout verify" % (label, x.get("repo"))]
    out = []
    if facts.get("archived") and decision != "learn":
        out.append("%s: %s в архиве — брать нельзя, можно только изучать" % (label, x["repo"]))
    if facts.get("package") is False:
        out.append("%s: у %s нет такого пакета в реестре" % (label, x["repo"]))
    allowed = LICENSE_DEP if decision == "adopt" else LICENSE_COPY if decision in ("adapt", "fork") else None
    if allowed is not None and facts.get("license") not in allowed:
        out.append("%s: лицензия %s не разрешает «%s» — только изучать" % (label, facts.get("license"), decision))
    return out


def scout_capability_problems(c):
    label = c.get("id") or c.get("name") or "?"
    decision = c.get("decision")
    out = []
    if decision not in SCOUT_DECISIONS:
        return ["%s: решение — %s" % (label, " | ".join(SCOUT_DECISIONS))]
    if not text_of(c.get("why")):
        out.append("%s: решение без причины" % label)
    if not c.get("requirements"):
        out.append("%s: не названы требования, которые оно закрывает" % label)
    if not isinstance(c.get("core"), bool):
        out.append("%s: не сказано, отличает ли это продукт (core: true/false)" % label)
    if decision == "build":
        if not c.get("candidates") and not text_of(c.get("searched")):
            out.append("%s: пишем сами, а что искали — не сказано (searched)" % label)
        return out
    chosen = next((x for x in c.get("candidates") or [] if x.get("repo") == c.get("choice")), None)
    if chosen is None:
        return out + ["%s: выбран %s, но его нет среди кандидатов" % (label, c.get("choice"))]
    out += scout_candidate_problems(label, decision, chosen)
    if c.get("core") and decision in ("adopt", "fork") and not text_of(c.get("byUser")):
        out.append("%s отличает продукт: брать готовым можно только словами владельца (byUser)" % label)
    if decision == "fork" and not text_of(c.get("byUser")):
        out.append("%s: чужой проект за основу — решение владельца (byUser)" % label)
    if decision in ("adapt", "fork") and not (c.get("spike") or {}).get("result"):
        out.append("%s: перед «%s» нужна проба (spike.result)" % (label, decision))
    return out


def scout_problems(data):
    caps = data.get("capabilities")
    if not isinstance(caps, list) or not caps:
        return ["нет списка capabilities"]
    out = []
    for c in caps:
        out += scout_capability_problems(c)
    return out


def scout_stale(data, today=None):
    """Давно не обновлялось — не отказ: у зрелой маленькой библиотеки это норма, но сказать надо."""
    today = today or dt.date.fromisoformat(now()[:10])
    out = []
    for c in data.get("capabilities") or []:
        chosen = next((x for x in c.get("candidates") or [] if x.get("repo") == c.get("choice")), {})
        pushed = (chosen.get("facts") or {}).get("pushedAt")
        if pushed and (today - dt.date.fromisoformat(pushed)).days > SCOUT_STALE_DAYS and c.get("decision") != "learn":
            out.append("%s: %s не обновлялся с %s — проверь, зрелость это или заброшенность" % (c.get("id"), chosen["repo"], pushed))
    return out


def mirror_gate(gate, ok, **kw):
    """Идёт прогон — проектный гейт виден на его дашборде."""
    state = read_state()
    if state is None or state.get("finishedAt"):
        return
    state["updatedAt"] = now()
    beat(state)
    set_gate(state, gate, ok, **kw)
    save(state)
    write_snapshot(state)


def scout_counts(data):
    caps = data.get("capabilities") or []
    taken = [c for c in caps if c.get("decision") in ("adopt", "adapt", "fork")]
    return {"capabilities": len(caps), "taken": len(taken), "own": len(caps) - len(taken)}


def cmd_scout(pos, opt, multi=None):
    act = pos[0] if pos else "status"
    data = scout_read()
    if data is None:
        die("нет .autopilot/prior-art.json — его пишет разведчик (prompts/scout.md)")
    if act == "verify":
        return cmd_scout_verify(data)
    if act == "check":
        problems = scout_problems(data)
        counts = scout_counts(data)
        data["checked"] = {"ok": not problems, "at": now()}
        scout_write(data)
        mirror_gate("GS", not problems, problems=len(problems), **counts)
        if problems:
            return ["! " + p for p in problems]
        return ["GS пройден: частей %(capabilities)d, берём готовым %(taken)d, пишем сами %(own)d" % counts] \
            + ["! " + p for p in scout_stale(data)]
    if act == "status":
        return ["частей %(capabilities)d, берём готовым %(taken)d, пишем сами %(own)d" % scout_counts(data),
                "проверка: " + ("пройдена" if (data.get("checked") or {}).get("ok") else "не пройдена")]
    die("scout verify | check | status")


def scout_passed():
    return bool(((scout_read() or {}).get("checked") or {}).get("ok"))


def ls_scout_guard(state):
    """Архитектор проектирует, зная, что уже есть готовым, — или записано, почему искать незачем."""
    s = next((x for x in state.get("stages") or [] if x.get("id") == "scout"), None)
    if s is None or s.get("status") == "skipped" or scout_passed():
        return
    die("поиск готового не закончен: `scout check`. Искать незачем — `stage scout skip --note \"почему\"`")


# ── форк autopilot-ls: архитектура и её аудит (phases/2b-architecture.md) ───

ARCH_DOC = os.path.join(A, "architecture.md")
ARCH_AUDITS = os.path.join(A, "architecture-audit")
ARCH_STATE = os.path.join(ARCH_AUDITS, "state.json")
# Рубрика — standards/architecture-rubric.md: ключ, вес, слова для владельца, можно ли «не применимо».
ARCH_CRITERIA = (
    ("product_fit", 3, "Соответствие продукту", False),
    ("qualities", 2, "Главные качества и их цифры", False),
    ("boundaries", 2, "Границы частей и зависимости", False),
    ("domain", 2, "Ядро и источник истины", True),
    ("data", 2, "Данные и их изменение", True),
    ("flows", 2, "Потоки и одновременность", True),
    ("failure", 2, "Отказы и внешние сервисы", False),
    ("security", 2, "Безопасность и личные данные", False),
    ("ops", 1, "Эксплуатация и наблюдаемость", True),
    ("testability", 2, "Проверяемость", False),
    ("performance", 1, "Нагрузка и стоимость", True),
    ("evolution", 1, "Развитие продукта", True),
    ("simplicity", 2, "Простота и соразмерность", False),
    ("delivery", 2, "Сборка по частям", False),
    ("decisions", 1, "Записанные решения", False),
    ("reuse", 2, "Готовое и своё", True),
    ("llm", 2, "Слой языковых моделей", True),
    ("legacy", 1, "Наследие и уроки прошлого", True),
)
ARCH_PASS = 9.0          # общий балл, который надо набрать
ARCH_FLOOR = 8           # ниже этого не может быть ни один критерий: среднее не прячет дыру
ARCH_MAX_ROUNDS = 6      # кругов аудита и подтверждения на архитектуру
ARCH_DELTA_ROUNDS = 3    # кругов на одно изменение принятой архитектуры
ARCH_MIN_SCENARIOS = 5
ARCH_SEVERITIES = ("blocking", "major", "minor")
ARCH_KINDS = ("audit", "confirm", "delta", "as-built")


def arch_read():
    try:
        with open(ARCH_STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def arch_write(a):
    os.makedirs(ARCH_AUDITS, exist_ok=True)
    tmp = ARCH_STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(a, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ARCH_STATE)


def arch_accepted():
    return bool(((arch_read() or {}).get("gate") or {}).get("ok"))


def text_of(v):
    return v.strip() if isinstance(v, str) else ""


def arch_criteria_problems(crit):
    out = []
    for key, _, name, may_na in ARCH_CRITERIA:
        c = crit.get(key)
        if not isinstance(c, dict):
            out.append("нет оценки по критерию %s (%s)" % (key, name))
        elif "na" in c:
            if not may_na:
                out.append("%s (%s) нельзя пропустить как «не применимо»" % (key, name))
            elif not text_of(c["na"]):
                out.append("%s: «не применимо» без причины" % key)
        elif isinstance(c.get("score"), bool) or not isinstance(c.get("score"), (int, float)) \
                or not 0 <= c["score"] <= 10:
            out.append("%s: оценка должна быть числом от 0 до 10" % key)
        else:
            if not text_of(c.get("evidence")):
                out.append("%s: оценка без доказательства из документа" % key)
            if c["score"] < ARCH_PASS and not text_of(c.get("gap")):
                out.append("%s: %s — не сказано, чего не хватает до 9" % (key, c["score"]))
    return out


def arch_finding_problems(findings, crit):
    out, known = [], {k for k, _, _, _ in ARCH_CRITERIA}
    for f in findings:
        label = f.get("id") or "находка без id"
        for field in ("id", "what", "fix"):
            if not text_of(f.get(field)):
                out.append("%s: пустое поле %s" % (label, field))
        if f.get("severity") not in ARCH_SEVERITIES:
            out.append("%s: важность — blocking, major или minor" % label)
        if f.get("criterion") not in known:
            out.append("%s: неизвестный критерий %s" % (label, f.get("criterion")))
        elif f.get("severity") == "blocking" and (crit.get(f["criterion"]) or {}).get("score", 0) > 7:
            out.append("%s блокирует сборку, а критерий %s оценён выше 7" % (label, f["criterion"]))
    return out


def arch_audit_problems(audit, expected_prior):
    """Файл аудита принимается целиком или не принимается: балл считает ap.py, и только по полному файлу."""
    if not isinstance(audit, dict) or not isinstance(audit.get("criteria"), dict):
        return ["в файле нет раздела criteria"]
    out = arch_criteria_problems(audit["criteria"])
    findings = audit.get("findings")
    if not isinstance(findings, list):
        return out + ["нет списка findings (пустой список — тоже список)"]
    out += arch_finding_problems(findings, audit["criteria"])
    scenarios = audit.get("scenarios") or []
    if len(scenarios) < ARCH_MIN_SCENARIOS:
        out.append("сценариев %d, нужно хотя бы %d" % (len(scenarios), ARCH_MIN_SCENARIOS))
    for s in scenarios:
        if not text_of(s.get("name")) or s.get("verdict") not in ("проходит", "ломается"):
            out.append("сценарий без имени или без вердикта «проходит»/«ломается»: %s" % s.get("name"))
    seen = {p.get("id") for p in audit.get("prior") or []}
    missing = [i for i in expected_prior if i not in seen]
    if missing:
        out.append("не сказано, закрыты ли прошлые находки: " + ", ".join(missing))
    if not text_of(audit.get("summary")):
        out.append("нет summary — итога простыми словами")
    return out


def arch_score(audit):
    """Общий балл — взвешенное среднее по применимым критериям; минимум и всё, что ниже порога."""
    total = weight = 0
    scored = []
    for key, w, _, _ in ARCH_CRITERIA:
        c = audit["criteria"][key]
        if "na" not in c:
            total += w * c["score"]
            weight += w
            scored.append((key, c["score"]))
    below = ["%s %s" % pair for pair in scored if pair[1] < ARCH_FLOOR]
    return round(total / weight, 2), min(s for _, s in scored), below


def arch_used(a, kinds):
    return sum(1 for r in a.get("rounds") or [] if r.get("kind") in kinds)


def arch_expected_prior(a, kind):
    """Прошлые находки сверяет только обычный круг: подтверждающий критик их не видит — он слепой."""
    if kind not in ("audit", "delta"):
        return []
    rounds = [r for r in a.get("rounds") or [] if r.get("kind") != "as-built"]
    if not rounds or rounds[-1].get("passed"):
        return []
    return rounds[-1].get("blocking", []) + rounds[-1].get("major", [])


def arch_record(a, kind, rel, audit):
    overall, floor, below = arch_score(audit)
    findings = audit["findings"]
    earlier = [r for r in a.get("rounds") or [] if r.get("kind") != "as-built"][-1:]
    was_blocking = set(earlier[0].get("blocking", [])) if earlier else set()
    unclosed = [p["id"] for p in audit.get("prior") or [] if not p.get("closed") and p.get("id") in was_blocking]
    broken = [s["name"] for s in audit.get("scenarios") or [] if s.get("verdict") == "ломается"]
    blocking = [f["id"] for f in findings if f["severity"] == "blocking"]
    return {"n": len(a.get("rounds") or []) + 1, "kind": kind, "at": now(), "file": rel,
            "overall": overall, "floor": floor, "below": below, "blocking": blocking,
            "major": [f["id"] for f in findings if f["severity"] == "major"],
            "unclosed": unclosed, "broken": broken, "summary": audit["summary"],
            "owner": [f["id"] for f in findings if f.get("owner")],
            "passed": overall >= ARCH_PASS and floor >= ARCH_FLOOR
            and not blocking and not unclosed and not broken}


def arch_line(r):
    tail = []
    if r["below"]:
        tail.append("ниже %d: %s" % (ARCH_FLOOR, ", ".join(r["below"])))
    if r["blocking"]:
        tail.append("блокирующих находок: %d" % len(r["blocking"]))
    if r["unclosed"]:
        tail.append("не закрыто с прошлого круга: " + ", ".join(r["unclosed"]))
    if r["broken"]:
        tail.append("ломаются сценарии: " + "; ".join(r["broken"]))
    return "круг %d (%s): %s из 10, минимум %s%s" % (
        r["n"], r["kind"], r["overall"], r["floor"], " · " + " · ".join(tail) if tail else "")


def arch_set_gate(a, rec, ok):
    a["gate"] = {"ok": ok, "score": rec["overall"], "floor": rec["floor"], "at": rec["at"], "round": rec["n"]}


def arch_gate_step(a, rec):
    """Что круг значит для гейта и что делать дальше. Подтверждает только второй, независимый критик."""
    kind, passed = rec["kind"], rec["passed"]
    if kind == "as-built":
        return "сверка с кодом записана, на принятие архитектуры не влияет"
    if kind == "confirm" and passed:
        arch_set_gate(a, rec, True)
        return "GA пройден: %s из 10, подтверждено независимым критиком" % rec["overall"]
    if kind == "delta" and passed:
        arch_set_gate(a, rec, True)
        a.pop("delta", None)
        return "GA пройден: изменение принято, %s из 10" % rec["overall"]
    arch_set_gate(a, rec, False)
    if kind == "audit" and passed:
        return "порог взят — теперь подтверждение: новый критик вслепую, `arch round --kind confirm`"
    if arch_used(a, ("delta",)) - a.get("deltaBase", 0) >= ARCH_DELTA_ROUNDS and kind == "delta":
        return "! потолок кругов на изменение (%d): вопрос владельцу — `ask stop`, затем `arch waive --by-user`" % ARCH_DELTA_ROUNDS
    if arch_used(a, ("audit", "confirm")) >= ARCH_MAX_ROUNDS:
        return "! потолок кругов (%d): вопрос владельцу — `ask stop`, затем `arch waive --by-user`" % ARCH_MAX_ROUNDS
    return "ещё круг: архитектор чинит находки, потом новый критик"


def arch_round(a, opt):
    kind = opt.get("kind") if isinstance(opt.get("kind"), str) else "audit"
    if kind not in ARCH_KINDS:
        die("arch round --kind audit|confirm|delta|as-built")
    if not isinstance(opt.get("file"), str):
        die("arch round --file .autopilot/architecture-audit/NN.json — файл критика")
    if kind != "as-built":
        arch_round_allowed(a, kind)
    path = opt["file"] if os.path.isabs(opt["file"]) else os.path.join(ROOT, opt["file"])
    try:
        with open(path, encoding="utf-8") as f:
            audit = json.load(f)
    except OSError:
        die("нет файла %s" % opt["file"])
    except ValueError as e:
        die("файл аудита — не JSON: %s" % e)
    problems = arch_audit_problems(audit, arch_expected_prior(a, kind))
    if problems:
        die("аудит не принят — верни его критику:\n  ! " + "\n  ! ".join(problems))
    rec = arch_record(a, kind, os.path.relpath(path, ROOT), audit)
    a.setdefault("rounds", []).append(rec)
    step = arch_gate_step(a, rec)
    arch_write(a)
    arch_mirror(a)
    return [arch_line(rec), step]


def arch_round_allowed(a, kind):
    if a.get("delta") and kind != "delta":
        die("идёт изменение архитектуры — круг только --kind delta")
    if kind == "delta":
        if not a.get("delta"):
            die("изменения нет — сначала arch delta --note \"что меняется\"")
        if arch_used(a, ("delta",)) - a.get("deltaBase", 0) >= ARCH_DELTA_ROUNDS:
            die("потолок кругов на изменение — вопрос владельцу: ask stop, затем arch waive --by-user")
        return
    if (a.get("gate") or {}).get("ok"):
        die("архитектура уже принята; изменить её — arch delta --note \"что меняется\"")
    if arch_used(a, ("audit", "confirm")) >= ARCH_MAX_ROUNDS:
        die("потолок кругов (%d): вопрос владельцу — ask stop, затем arch waive --by-user \"«…»\"" % ARCH_MAX_ROUNDS)
    last = [r for r in a.get("rounds") or [] if r.get("kind") != "as-built"][-1:]
    if kind == "confirm" and not (last and last[0].get("passed") and last[0].get("kind") == "audit"):
        die("подтверждать нечего: сначала обычный круг, набравший порог")


def arch_mirror(a):
    """Идёт прогон — принятие архитектуры видно на его дашборде как гейт GA."""
    state = read_state()
    if state is None or state.get("finishedAt") or not a.get("rounds"):
        return
    state["updatedAt"] = now()
    beat(state)
    g = a.get("gate") or {}
    set_gate(state, "GA", bool(g.get("ok")), score=g.get("score"), floor=g.get("floor"),
             rounds=len(a["rounds"]), waived=g.get("waived"))
    save(state)
    write_snapshot(state)


def arch_status(a):
    g = a.get("gate") or {}
    head = "архитектура принята: %s из 10%s" % (g.get("score"), " (с оговоркой владельца)" if g.get("waived") else "") \
        if g.get("ok") else "архитектура ещё не принята"
    return [head] + [arch_line(r) for r in a.get("rounds") or []]


def cmd_arch(pos, opt, multi=None):
    act = pos[0] if pos else "status"
    a = arch_read()
    if act == "start":
        scope = opt.get("scope") if opt.get("scope") in ("project", "run") else "run"
        if a is not None:
            return ["аудит уже начат — " + arch_status(a)[0]]
        arch_write({"scope": scope, "startedAt": now(), "rounds": [], "gate": {"ok": False}})
        return ["архитектура: документ `.autopilot/architecture.md`, аудиты `.autopilot/architecture-audit/`"]
    if a is None:
        die("аудита ещё не было — arch start")
    if act == "round":
        return arch_round(a, opt)
    if act == "status":
        return arch_status(a)
    if act == "waive":
        if not isinstance(opt.get("by-user"), str):
            die("arch waive --by-user \"«слова владельца»\" — ниже порога только его словами")
        if not a.get("rounds"):
            die("принимать нечего: ни одного круга аудита")
        a["gate"] = {"ok": True, "waived": opt["by-user"], "score": a["rounds"][-1]["overall"],
                     "floor": a["rounds"][-1]["floor"], "at": now(), "round": a["rounds"][-1]["n"]}
        a.pop("delta", None)
        arch_write(a)
        arch_mirror(a)
        return ["архитектура принята словами владельца при оценке %s" % a["gate"]["score"]]
    if act == "delta":
        if not isinstance(opt.get("note"), str):
            die("arch delta --note \"что меняется и почему\"")
        a["delta"] = {"note": opt["note"], "at": now()}
        a["deltaBase"] = arch_used(a, ("delta",))
        a["gate"]["ok"] = False
        arch_write(a)
        arch_mirror(a)
        return ["изменение архитектуры открыто: архитектор правит документ, потом `arch round --kind delta`"]
    die("arch start | round | status | waive | delta")


def ls_arch_guard(state):
    """Спецификация пишется поверх принятой архитектуры — или с записанной причиной, почему её нет."""
    s = next((x for x in state.get("stages") or [] if x.get("id") == "architecture"), None)
    if s is None or s.get("status") == "skipped" or arch_accepted():
        return
    die("архитектура не принята: `arch status`. Маленькая сборка — `stage architecture skip --note \"почему не нужна\"`")


def ls_arch_ticket_problems(tickets):
    """Принятая архитектура — договор: таск называет разделы, которые строит."""
    if not arch_accepted():
        return []
    return ["у таска %s нет поля Архитектура" % t["id"]
            for t in tickets if t.get("type") != "prompt" and not t.get("architecture")]


def ls_arch_landing(state):
    s = next((x for x in state.get("stages") or [] if x.get("id") == "architecture"), None)
    if s is None or s.get("status") == "skipped" or arch_accepted():
        return []
    return ["GA: архитектура не принята"]


# ── форк autopilot-ls: обзор владельцем (phases/5-prompts.md, «The owner's look») ──

def ls_owner_guard(state, act, ids, opt):
    """await — только закоммиченный таск; из awaiting_owner в done — только словами владельца."""
    known = {t["id"]: t for t in state.get("tickets") or []}
    for i in ids:
        tk = known.get(i) or {}
        if act == "await" and not isinstance(opt.get("commit"), str) and not tk.get("commit"):
            die("таск %s: нет --commit — владельцу показывают только влитый таск" % i)
        if act == "await" and not isinstance(opt.get("page"), str):
            die("таск %s: await --page prompt-reviews/NN-<slug>.html — без страницы обзора владельцу нечего смотреть" % i)
        if act == "done" and tk.get("status") == "awaiting_owner" and not isinstance(opt.get("by-user"), str):
            die("таск %s ждёт владельца — done только его словами: ticket %s done --by-user \"«…»\"; "
                "его правки — ticket %s repair --note \"…\"" % (i, i, i))


def record_owner(state, tk, act, opt):
    if act == "await":
        tk["page"] = opt["page"]
        record_landing(tk, opt)
        n = state.get("night") or {}
        if n.get("status") == "running" and tk["id"] not in n.setdefault("awaiting", []):
            n["awaiting"].append(tk["id"])
    elif act == "done" and tk.get("status") == "awaiting_owner":
        tk.setdefault("approvedByUser", []).append(opt["by-user"])


IN_FLIGHT = ("in-progress", "repair")


def ls_pacing_guard(state, act, ids):
    """Окно ≥85 % — запусков нет; иначе в полёте не больше, чем окно позволяет (3 или 2).
    Цифры устарели — сначала get_usage и `pacing`, а не обход отказа."""
    p = state.get("pacing") or {}
    used, two, stop, name, _ = pace_basis(p)
    if used is None or act not in ("start", "retry"):
        return
    if used >= stop:
        die("%s %s %% — новых запусков нет: летящие довести, продолжить после сброса. "
            "Уже сброшено — свежие цифры: get_usage → `pacing`" % (name, used))
    cap = 2 if used > two else 3
    flying = {t["id"] for t in state.get("tickets") or [] if t.get("status") in IN_FLIGHT}
    total = len(flying | set(ids))
    if act == "start" and total > cap:
        die("в полёте было бы %d, %s %s %% позволяет %d — запусти меньше" % (total, name, used, cap))


def ls_night_record(state, act, ids):
    n = state.get("night") or {}
    if n.get("status") != "running" or act not in ("done", "fail"):
        return
    queued = set((state.get("queue") or {}).get("tickets") or [])
    ids = [i for i in ids if i in queued]          # ревью дневного таска, закрытое ночью, — не ночная работа
    if not ids:
        return
    n["done" if act == "done" else "failed"].extend(i for i in ids if i not in n["done"] + n["failed"])
    if act == "fail":
        n.update(status="stopped", stop="упал таск %s" % ", ".join(ids))


def rung_of(model, effort):
    if (model, effort) in LADDER:
        return LADDER.index((model, effort))
    return {"haiku": 0, "sonnet": 1}.get(model, 3 if effort in ("xhigh", "max") else 2)


def next_rung(tk):
    """Ретрай 1 — та же ступень (haiku поднимается до sonnet); ретрай 2 — на ступень выше
    ступени ретрая 1. Выше opus·xhigh ступени нет: max — только словами пользователя."""
    last = (tk.get("attempts") or [{}])[-1]
    cur = rung_of(last.get("model") or tk.get("model"), last.get("effort") or tk.get("effort"))
    return LADDER[max(cur, 1) if tk.get("retries", 0) == 0 else min(cur + 1, len(LADDER) - 1)]


def record_attempt(state, tk, act, opt):
    """Ступень каждой попытки — в attempts: по ней следующий план узнаёт, что sonnet не тянет."""
    if act == "start" and tk.get("attempts") and tk.get("status") != "pending":
        return None
    if act == "retry":
        model, effort = next_rung(tk)
    elif act == "start":
        model, effort = tk.get("model"), tk.get("effort")
    else:
        return None
    model = opt.get("model") if isinstance(opt.get("model"), str) else model
    effort = opt.get("effort") if isinstance(opt.get("effort"), str) else effort
    tk.setdefault("attempts", []).append({"model": model, "effort": effort, "at": state["updatedAt"]})
    if act == "retry":
        return "таск %s, ретрай %d: %s · %s" % (tk["id"], tk.get("retries", 0) + 1, model, effort)
    return None


def record_landing(tk, opt):
    if isinstance(opt.get("gates"), str):
        tk["gates"] = opt["gates"]
    if isinstance(opt.get("base"), str):
        tk.setdefault("base", opt["base"][:12])


def ub_mode_installed():
    roots = (os.path.expanduser("~/.claude/skills"), os.path.join(ROOT, ".claude", "skills"))
    return any(os.path.isfile(os.path.join(r, "ub-mode", "SKILL.md")) for r in roots)


def cmd_ls_check(state):
    """Что форку нужно: навык чистого кода, игнор worktree, make gates."""
    out = []
    if not ub_mode_installed():
        out.append("! не установлен скилл ub-mode — без него исполнители не начнут: "
                   "tools/install-ls.sh в репозитории навыка (github.com/unclebob/ub-mode)")
    try:
        ignore = open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read()
    except OSError:
        ignore = ""
    if not re.search(r"^/?\.claude/worktrees/?\s*$", ignore, re.M):
        out.append("! .gitignore без .claude/worktrees/ — допиши строку")
    try:
        make = open(os.path.join(ROOT, "Makefile"), encoding="utf-8").read()
    except OSError:
        make = ""
    out.append("make gates есть" if re.search(r"^gates\s*:", make, re.M)
               else "make gates ещё нет — его строит таск 01 по standards/gates.md")
    return out


def dep_id(ref, ids):
    """Ссылка из «Зависит от» → id таска. `2`, `02`, `T2` — это таск 02; ссылка, которая
    сама есть id таска (`F1`, `E34`), остаётся как есть; любая другая — тоже как есть,
    и check-plan назовёт её несуществующей. Цифры из чужой ссылки не вынимаются никогда."""
    if ref in ids:
        return ref
    m = re.match(r"^[Tt]?(\d+)$", ref)
    return m.group(1).zfill(2) if m else ref


def publish_tickets(state):
    files = sorted(glob.glob(os.path.join(run_dir(state), "tickets", "*.md")))
    if not files:
        return "в %s/tickets/ нет файлов" % state.get("dir")
    old = {t["id"]: t for t in state.get("tickets") or []}
    out = []
    for p in files:
        t = parse_ticket(p)
        prev = old.get(t["id"], {})
        for k in ("status", "startedAt", "finishedAt", "retries", "repairs", "repairFindings",
                  "tests", "commit", "concerns") + LS_KEEP:
            if k in prev:
                t[k] = prev[k]
        t.setdefault("status", "pending")
        t.setdefault("retries", 0)
        t.setdefault("repairs", 0)
        out.append(t)
    ids = {t["id"] for t in out}
    for t in out:
        t["blockedBy"] = [dep_id(b, ids) for b in t["blockedBy"]]
    state["tickets"] = out
    rows = dict(manifest_rows(state) or [])
    where = {}
    for t in out:
        for r in {x.split(".")[0] for x in t["requirements"]}:
            where.setdefault(r, []).append("T" + t["id"])
    moved = manifest_update(state, {r: ("in-ticket", ", ".join(w)) for r, w in where.items()
                                    if rows.get(r) == "in-spec"})
    return "тасков опубликовано: %d%s" % (len(out), (" · в манифесте in-ticket: %d" % len(moved)) if moved else "")


def check_plan(state):
    """G3 механически: каждое живое требование — в таске, каждый таск — от требования,
    у каждого таска зона и волна, в одной волне зоны не пересекаются."""
    problems = []
    rows = manifest_rows(state) or []
    publish_tickets(state)
    tickets = state.get("tickets") or []
    named = {r for t in tickets for r in t["requirements"]}
    base = {r.split(".")[0] for r in named}
    for rid, st in rows:
        if st in ("in-spec", "in-ticket", "placeholder") and not rid.startswith("D") and rid not in base:
            problems.append("требование %s (%s) не попало ни в один таск" % (rid, st))
    known = {rid for rid, _ in rows}
    ids = {t["id"] for t in tickets}
    for t in tickets:
        own = [r for r in t["requirements"] if r.split(".")[0][:1] in "RGD"]
        if not t["requirements"]:
            problems.append("таск %s ни к чему не привязан — работа, которую никто не заказывал" % t["id"])
        for r in own:
            if r.split(".")[0] not in known:
                problems.append("таск %s ссылается на %s, которого нет в манифесте" % (t["id"], r))
        if not t["zone"]:
            problems.append("у таска %s нет зоны" % t["id"])
        if t["wave"] is None:
            problems.append("у таска %s нет волны" % t["id"])
        for b in t["blockedBy"]:
            if b not in ids:
                problems.append("таск %s зависит от несуществующего %s" % (t["id"], b))
    wave_of = {t["id"]: t["wave"] for t in tickets}
    for t in tickets:
        need = 1 + max([wave_of.get(b) or 0 for b in t["blockedBy"]] or [0])
        if t["wave"] is not None and t["wave"] < need:
            problems.append("таск %s в волне %s, но его зависимости позволяют не раньше %d"
                            % (t["id"], t["wave"], need))
    for i, a in enumerate(tickets):
        for b in tickets[i + 1:]:
            if a["wave"] is None or a["wave"] != b["wave"]:
                continue
            for za in a["zone"]:
                for zb in b["zone"]:
                    x, y = za.rstrip("/") + "/", zb.rstrip("/") + "/"
                    if x.startswith(y) or y.startswith(x):
                        problems.append("таски %s и %s в одной волне пишут в %s"
                                        % (a["id"], b["id"], za if len(za) >= len(zb) else zb))
    return problems + ls_plan_problems(state, tickets)


# ── этапы ───────────────────────────────────────────────────────────────────

def stage(state, sid):
    for s in state.get("stages") or []:
        if s.get("id") == sid:
            return s
    s = {"id": sid, "status": "pending"}
    state.setdefault("stages", []).append(s)
    return s


def close_passed(state):
    """Инвариант: раньше открытого этапа не бывает другого открытого. Прошлый
    закрывается временем открытия ближайшего следующего. Этап, который прогон
    проскочил, не отметив, закрывается, если его файл лежит на диске.
    skipped и failed — осознанные состояния, их не трогаем."""
    rank = {v: i for i, v in enumerate(ORDER)}
    stages = [s for s in state.get("stages") or [] if s.get("id") in rank]
    live = [s for s in stages if s.get("status") == "active"]
    closed = []
    for s in live:
        later = sorted(o["startedAt"] for o in live
                       if rank[o["id"]] > rank[s["id"]] and o.get("startedAt"))
        if later:
            s["status"], s["finishedAt"] = "done", later[0]
            closed.append("%s закрыт (%s)" % (s["id"], later[0][11:19]))
    reached = [rank[s["id"]] for s in stages if s.get("status") in ("active", "done")]
    if not reached:
        return closed
    edge = max(reached)
    for s in stages:
        art = ARTIFACT.get(s["id"])
        if s.get("status") != "pending" or rank[s["id"]] >= edge or not art or not state.get("dir"):
            continue
        if glob.glob(os.path.join(run_dir(state), art)):
            nxt = [o["startedAt"] for o in stages if rank[o["id"]] > rank[s["id"]] and o.get("startedAt")]
            when = min(nxt) if nxt else state.get("updatedAt")
            s["status"], s["startedAt"], s["finishedAt"] = "done", s.get("startedAt") or when, when
            closed.append("%s отмечен пройденным по файлу %s" % (s["id"], art))
    return closed


def audit(state):
    out = []
    rank = {v: i for i, v in enumerate(ORDER)}
    stages = state.get("stages") or []
    live = [rank[s["id"]] for s in stages if s.get("status") == "active" and s.get("id") in rank]
    if live:
        for s in stages:
            if s.get("status") == "pending" and rank.get(s.get("id"), 99) < max(live):
                out.append("этап %s пропущен в учёте: был — `stage %s done`, не было — `stage %s skip "
                           "--note причина`. Это бухгалтерия, не расследуй" % ((s["id"],) * 3))
    return out


# ── страница и сервер ───────────────────────────────────────────────────────

def write_snapshot(state):
    try:
        page = open(PAGE, encoding="utf-8").read()
    except FileNotFoundError:
        return "страницы нет — перекопируй dashboard.html из навыка"
    i, j = page.find(BEGIN), page.find(END)
    if i < 0 or j < 0:
        return "страница без маркеров снимка — перекопируй dashboard.html из навыка"
    payload = "window.STATE=" + json.dumps(state, ensure_ascii=False).replace("</", "<\\/") + ";"
    new = page[: i + len(BEGIN)] + payload + page[j:]
    if new != page:
        tmp = PAGE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(new)
        os.replace(tmp, PAGE)
    return "дашборд обновлён"


def _run(args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=10,
                              encoding="utf-8", errors="replace").stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _ps(script):
    return _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])


def cmdline(pid):
    if WIN:
        return _ps("(Get-CimInstance Win32_Process -Filter 'ProcessId=%d').CommandLine" % int(pid)).strip()
    return _run(["ps", "-p", str(pid), "-o", "command="]).strip()


def processes():
    out = []
    if WIN:
        text = _ps("Get-CimInstance Win32_Process -Filter \"Name LIKE 'python%'\" | "
                   "ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }")
        for line in text.splitlines():
            num, _, cmd = line.partition("\t")
            if num.strip().isdigit():
                out.append((int(num), cmd))
    else:
        for line in _run(["ps", "-Ao", "pid=,command="]).splitlines():
            num, _, cmd = line.strip().partition(" ")
            if num.isdigit():
                out.append((int(num), cmd))
    return out


def _norm(path):
    return os.path.normcase(os.path.normpath(path)).replace("\\", "/")


_OURS = re.compile(r"--directory\s+\"?" + re.escape(_norm(A)) + r"\"?(?=\s|$)")


def is_ours(cmd):
    """Сервер этого проекта — и только он: `-m http.server` и ровно наш --directory.
    Узко намеренно: широкая проверка уже убивала чужие серверы."""
    c = cmd.replace("\\", "/")
    c = c.lower() if WIN else c
    return bool(re.search(r"-m\s+http\.server\b", c)) and bool(_OURS.search(c))


def kill(pid):
    try:
        os.kill(int(pid), 15)
    except (OSError, ValueError):
        pass


def recorded():
    try:
        port, pid = open(PIDF, encoding="utf-8").read().split()
        return int(port), int(pid)
    except (OSError, ValueError):
        return None, None


def http_ok(port):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/dashboard.html" % port, timeout=2) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def free_port(prefer):
    """Прежний порт — в первую очередь: открытая вкладка опрашивает именно его и
    оживает сама, когда сервер вернулся. Убитый сервер оставляет порт в TIME_WAIT,
    и без SO_REUSEADDR проверка считала его занятым — сервер уезжал на новый порт,
    а вкладка оставалась мёртвой. http.server сам ставит этот флаг, так что порт
    ему достанется. На Windows флаг значит другое (захват чужого порта) — там без него."""
    for p in ([prefer] if prefer else []) + [0]:
        s = socket.socket()
        if not WIN:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", p))
            return s.getsockname()[1]
        except OSError:
            continue
        finally:
            s.close()
    return None


def kill_orphans(keep=None):
    n = 0
    for pid, cmd in processes():
        if pid not in (keep, os.getpid()) and is_ours(cmd):
            kill(pid)
            n += 1
    return n


def _detached():
    if WIN:
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {"start_new_session": True}


def serve(state):
    port, pid = recorded()
    if state.get("finishedAt"):
        kill_orphans(keep=pid)
        return "прогон закрыт"
    if os.environ.get("SSH_CONNECTION") or os.environ.get("CI"):
        return "удалённая сессия — без сервера, дашборд: %s" % PAGE
    if port and pid and http_ok(port) and is_ours(cmdline(pid)):
        return "http://localhost:%d/dashboard.html" % port
    kill_orphans()
    port = free_port(port)
    if not port:
        return "порт не нашёлся — дашборд открывается файлом: %s" % PAGE
    try:
        with open(LOG, "a", encoding="utf-8") as log:
            srv = subprocess.Popen([sys.executable, "-m", "http.server", str(port),
                                    "--bind", "127.0.0.1", "--directory", A],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=log, **_detached())
    except OSError as e:
        return "сервер не запустился (%s) — дашборд открывается файлом: %s" % (e, PAGE)
    for _ in range(10):
        if http_ok(port):
            with open(PIDF, "w", encoding="utf-8") as f:
                f.write("%d %d\n" % (port, srv.pid))
            return "сервер поднят: http://localhost:%d/dashboard.html" % port
        try:
            srv.wait(timeout=0.5)
            break
        except subprocess.TimeoutExpired:
            continue
    srv.terminate()
    return "сервер не ответил — дашборд открывается файлом: %s" % PAGE


def stop_now():
    time.sleep(STOP_DELAY)
    port, pid = recorded()
    if pid and is_ours(cmdline(pid)):
        kill(pid)
    kill_orphans()
    for f in (PIDF, LOG):
        try:
            os.remove(f)
        except OSError:
            pass


def stop_later():
    """Гасит сервер через STOP_DELAY секунд из отдельного процесса: страница
    опрашивает state.js раз в 10 секунд и должна успеть забрать финал."""
    subprocess.Popen([sys.executable, os.path.abspath(__file__), "--stop-now"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, **_detached())
    return "сервер погаснет через %d с" % STOP_DELAY


# ── версия навыка ───────────────────────────────────────────────────────────

_VER = re.compile(r"^\s*version:\s*[\"']?(\d+(?:\.\d+)*)", re.M)


def _version(text):
    m = _VER.search(text.split("\n---", 1)[0] if text.startswith("---") else "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def check_update(state):
    """Строка, если на GitHub навык новее. Без сети — молчит.
    AUTOPILOT_NO_UPDATE_CHECK=1 выключает."""
    if os.environ.get("AUTOPILOT_NO_UPDATE_CHECK"):
        return None
    skill = state.get("skillDir") or ""
    try:
        local = _version(open(os.path.join(skill, "SKILL.md"), encoding="utf-8").read())
    except OSError:
        return None
    try:
        with urllib.request.urlopen(REMOTE_SKILL, timeout=3) as r:
            remote = _version(r.read(65536).decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if not remote or (local and remote <= local):
        return None
    home = _norm(os.path.expanduser("~"))
    flag = " -g" if _norm(skill).startswith(home + "/.") else ""
    v = lambda t: ".".join(map(str, t))
    # Форк autopilot-ls: обновление upstream не ставится поверх, а вливается в форк руками.
    del flag
    return ("в upstream вышла версия Autopilot %s (форк autopilot-ls основан на %s) — "
            "влить в форк вручную, что нового — github.com/%s/blob/main/CHANGELOG.md"
            % (v(remote), v(local) if local else "без номера", REPO))


# ── реестр прогонов (.autopilot/README.md) ──────────────────────────────────

README_TEXT = """# Как читать эту папку

- `dashboard.html` — открывается сам в начале сборки; можно и двойным кликом.
  Этапы, прогресс, время, что осталось. Обновляется сам, пока сборка идёт.
  `index.html` рядом — тот же файл под другим именем, открывать его не нужно.
- `<дата>-<проект>/` — папка одной сборки. Дата — день, когда сборка началась.
  Суффикс `--wip` значит «ещё делается»; когда сборка сдана, он снимается. Внутри:
  - `<дата>-brief.md` — твоя задача слово в слово и «Дополнения» — всё, что ты сказал позже.
  - `manifest.md` — список требований и что с каждым стало.
  - `spec.md` — спецификация. `tickets/` — таски, на которые разбита сборка.
- `PROGRESS.md` — что осталось после последней сборки: не доделано, известные баги,
  о чём договорились. Мелкие правки без автопилота дописываются сюда же.

Если сборка прервалась — набери `/autopilot-ls` без слов, агент поднимет состояние отсюда.

## Прогоны

| Начат | Папка | Статус | Итог |
|---|---|---|---|
"""


def register_row(state, status, result):
    d = state.get("dir") or ""
    base = re.sub(r"--wip$", "", d)
    try:
        text = open(README, encoding="utf-8").read()
    except OSError:
        text = README_TEXT
    if "## Прогоны" not in text:
        text = text.rstrip("\n") + "\n\n## Прогоны\n\n| Начат | Папка | Статус | Итог |\n|---|---|---|---|\n"
    row = "| %s | `%s` | %s | %s |" % (d[:10], d, status, result or "—")
    lines = text.splitlines()
    hit = [i for i, l in enumerate(lines) if l.startswith("|") and ("`%s`" % base in l or "`%s--wip`" % base in l)]
    if hit:
        lines[hit[-1]] = row
    else:
        lines.append(row)
    with open(README, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def git_mv(src, dst):
    if subprocess.run(["git", "-C", A, "mv", src, dst], capture_output=True).returncode == 0:
        return True
    try:
        os.rename(os.path.join(A, src), os.path.join(A, dst))
        return True
    except OSError:
        return False


def ensure_gitignore():
    g = os.path.join(ROOT, ".gitignore")
    try:
        text = open(g, encoding="utf-8").read()
    except OSError:
        text = ""
    if re.search(r"^\.autopilot/serve\.\*", text, re.M):
        return
    with open(g, "a", encoding="utf-8") as f:
        f.write(("" if not text or text.endswith("\n") else "\n") + ".autopilot/serve.*\n")


# ── форк autopilot-ls: мастер-план и страница всего проекта (phases/0-program.md) ──

PROJECT_DIR = os.path.join(A, "project")
PROJECT_STATE = os.path.join(PROJECT_DIR, "state.json")
QUESTIONS = os.path.join(PROJECT_DIR, "questions.json")
BRIEFS = os.path.join(A, "briefs")
MILESTONE_ROW = re.compile(r"^\|\s*M\d+\s*\|")
PROGRAM_DEFAULT_TICKETS = 8
PROGRAM_DEFAULT_DAYS = 3
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
          "сентября", "октября", "ноября", "декабря")
RU_STAGE = {"preflight": "Подготовка", "manifest": "Требования", "briefing": "Брифинг", "scout": "Поиск готового",
            "architecture": "Архитектура", "spec": "Спецификация", "plan": "План", "build": "Разработка",
            "review": "Код-ревью", "final": "Приёмка"}
GLOSSARY = [
    ["Прогон", "Большой кусок проекта со своей задачей, планом и приёмкой. Проект собирается из нескольких прогонов.", "прогон"],
    ["Таск", "Один кусок работы внутри прогона. Его делает отдельный исполнитель.", "таск"],
    ["Волна", "Таски, которые можно делать одновременно. Следующая волна начинается после предыдущей.", "волн"],
    ["Архитектура", "Как продукт устроен внутри: из каких частей, как они связаны и что будет при сбоях.", "архитектур"],
    ["Оркестратор", "Главный чат, который ведёт разработку и раздаёт работу исполнителям.", "оркестратор"],
]
LINT_KEYS_SKIP = {"id", "run", "start", "end", "at", "asOf", "tz", "key", "url", "listDate", "kind", "group",
                  "status", "state", "file", "choice", "repo"}
PAGE_LINT = (
    (re.compile(r"\b[RGAD]\d{2}(?:\.\d+)?\b"), "код требования"),
    (re.compile(r"\b[TP]\d{2}[a-z]?\b"), "внутренний номер"),
    (re.compile(r"\b(?:main|master|worktree|rebase|fast-forward|git push|git merge)\b", re.I), "слово разработчика"),
    (re.compile(r"/Users/|/home/|[A-Za-z]:\\\\"), "путь на диске"),
    (re.compile(r"sk-[A-Za-z0-9_-]{12,}|ghp_[A-Za-z0-9]{20,}|\b\d{8,10}:[A-Za-z0-9_-]{30,}|AKIA[0-9A-Z]{12,}"), "похоже на секрет"),
    (re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"), "адрес сервера"),
)


def json_read(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def json_write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def date_of(v):
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def day_text(d):
    return "%d %s" % (d.day, MONTHS[d.month - 1])


def span_text(a, b):
    if a == b:
        return day_text(a)
    if (a.year, a.month) == (b.year, b.month):
        return "%d–%d %s" % (a.day, b.day, MONTHS[a.month - 1])
    return "%s – %s" % (day_text(a), day_text(b))


def plural_ru(n, one, few, many):
    tail, tens = n % 10, n % 100
    if tail == 1 and tens != 11:
        return one
    return few if 2 <= tail <= 4 and not 12 <= tens <= 14 else many


def next_runnable(rows):
    landed = {r["id"] for r in rows if r["status"] == "landed"}
    return next((r for r in rows if r["status"] == "pending" and all(d in landed for d in r["deps"])), None)


def program_parallel(lines):
    m = next((re.search(r"Параллельно[^0-9]*(\d+)", x) for x in lines if x.startswith("Параллельно")), None)
    return max(1, int(m.group(1))) if m else 1


def program_milestones(lines):
    out = []
    for line in lines:
        if MILESTONE_ROW.match(line):
            c = [x.strip() for x in cells_of(line)] + [""] * 4
            out.append({"id": c[0], "title": c[1], "after": re.findall(r"P\d+[a-z]?", c[2]), "gives": c[3]})
    return out


def program_schedule(rows, today, parallel):
    """Даты для диаграммы: сданное — по факту, остальное — оценка из дней, зависимостей и дорожек."""
    lanes, ends, out = [today] * parallel, {}, {}
    day = dt.timedelta(days=1)
    for r in rows:
        days = max(1, r["days"] or PROGRAM_DEFAULT_DAYS)
        if r["status"] == "landed":
            end = date_of(r["landed"]) or today
            out[r["id"]], ends[r["id"]] = (date_of(r["started"]) or end, end), end
            continue
        lane = lanes.index(min(lanes))
        if r["status"] == "in-flight":
            start = date_of(r["started"]) or today
            end = max(start + day * (days - 1), today)
        else:
            start = max([lanes[lane]] + [ends[d] + day for d in r["deps"] if d in ends])
            end = start + day * (days - 1)
        lanes[lane], out[r["id"]], ends[r["id"]] = end + day, (start, end), end
    return out


def program_problems(state=None):
    """Мастер-план записан целиком: у каждого прогона размер, срок, слова для владельца, свой бриф."""
    lines = program_lines()
    if lines is None:
        return ["нет .autopilot/program.md"]
    rows = program_rows(lines)
    if not rows:
        return ["в программе нет ни одного прогона"]
    out, seen = [], set()
    for r in rows:
        if r["id"] in seen:
            out.append("%s встречается дважды" % r["id"])
        out += ["%s зависит от %s, а он ниже по таблице или его нет" % (r["id"], d) for d in r["deps"] if d not in seen]
        seen.add(r["id"])
        missing = [n for n, k in (("Тасков", "tickets"), ("Дней", "days"), ("Простыми словами", "plain"), ("Что даёт", "gives"))
                   if not r[k]]
        if missing:
            out.append("%s: не заполнено — %s" % (r["id"], ", ".join(missing)))
        if not os.path.isfile(os.path.join(BRIEFS, r["id"] + ".md")):
            out.append("%s: нет брифа .autopilot/briefs/%s.md" % (r["id"], r["id"]))
    return out + program_manifest_problems(state, seen)


def program_manifest_problems(state, ids):
    """Ни одно живое требование не осталось без прогона: колонка «Где» называет P##."""
    if not state or not state.get("dir") or state.get("program"):
        return []
    out = []
    for r in manifest_where(state):
        if r["status"] not in ("dropped", "deferred") and not set(re.findall(r"P\d+[a-z]?", r["where"])) & ids:
            out.append("требование %s не попало ни в один прогон (колонка «Где»)" % r["id"])
    return out


def manifest_where(state):
    try:
        text = open(os.path.join(run_dir(state), "manifest.md"), encoding="utf-8").read()
    except OSError:
        return []
    rows = []
    for line in text.splitlines():
        c = [x.strip() for x in cells_of(line)] if line.lstrip().startswith("|") else []
        if len(c) >= 5 and ROW_ID.match(c[0].strip("`*")) and not c[0].startswith("D"):
            rows.append({"id": c[0].strip("`*"), "status": c[2], "where": c[4]})
    return rows


def cmd_program_plan(opt):
    """План программы записан — прогон планирования закрывается без кода, на его месте остаётся план."""
    state = read_state()
    if state is None or state.get("finishedAt"):
        die("закрыть план программы можно только из идущего прогона планирования")
    if not isinstance(opt.get("result"), str):
        die("program plan --result \"сколько прогонов и что в итоге будет\"")
    problems = program_problems(state)
    if not arch_accepted():
        problems.append("архитектура проекта не принята: arch status")
    if problems:
        die("план программы не закрыт:\n  ! " + "\n  ! ".join(problems))
    state["updatedAt"] = t = now()
    beat(state)
    for s in state.get("stages") or []:
        if s.get("status") in ("pending", "active") and s.get("id") in ("spec", "plan", "build", "review", "final"):
            s.update(status="skipped", note="это план программы: код строят её прогоны", finishedAt=t)
            s.setdefault("startedAt", t)
    state["programPlan"] = True
    notes = land_run(state, opt["result"], [], None, "план программы")
    save(state)
    write_snapshot(state)
    stop_later()
    return notes + project_refresh()


def load_state_file(path):
    try:
        raw = open(path, encoding="utf-8").read()
        return json.loads(raw.split("=", 1)[1].strip().rstrip(";"))
    except (OSError, ValueError, IndexError):
        return None


def run_states(rows):
    """Состояние каждого прогона: живой — из state.js, сданные — из их папок."""
    live = read_state()
    out = {}
    for r in rows:
        if live and live.get("program") == r["id"]:
            out[r["id"]] = live
        elif r["dir"] and r["dir"] != "—":
            found = load_state_file(os.path.join(A, r["dir"], "state.js"))
            if found:
                out[r["id"]] = found
    return out


def brief_text(st):
    files = sorted(glob.glob(os.path.join(A, st.get("dir") or "", "*-brief.md")))
    if not files:
        return ""
    body = open(files[0], encoding="utf-8").read().split("## Дополнения")[0]
    lines = [x.strip() for x in body.splitlines() if x.strip() and not x.startswith(("#", ">"))]
    text = " ".join(lines)
    return text if len(text) <= 500 else text[:499].rstrip() + "…"


def ticket_minutes(t):
    a, b = t.get("startedAt"), t.get("finishedAt")
    if not a or not b:
        return None
    return max(1, round((dt.datetime.fromisoformat(b) - dt.datetime.fromisoformat(a)).total_seconds() / 60))


def run_plan(st):
    """План прогона по волнам — диаграмма внутри отчёта."""
    bucket = {"done": "done", "in-progress": "now", "repair": "now", "review": "rev",
              "awaiting_owner": "rev", "failed": "bad"}
    waves = {}
    for t in st.get("tickets") or []:
        waves.setdefault(t.get("wave") or 1, []).append(
            {"title": t.get("title") or t["id"], "k": bucket.get(t.get("status"), "wait"), "minutes": ticket_minutes(t)})
    return [{"n": k, "tickets": waves[k]} for k in sorted(waves)]


def run_checks(st):
    g, out = st.get("gates") or {}, []
    tests = st.get("tests")
    if tests:
        out.append({"t": "Автотесты", "v": "прошло %d, упало %d" % (tests["passed"], tests["failed"]),
                    "s": "Программа сама проверяет, что написанное работает.", "ok": not tests["failed"]})
    rows = (
        ("GS", "Поиск готового", lambda x: "частей %s, взято готовым %s" % (x.get("capabilities"), x.get("taken")),
         "Что брать готовым, решено по каждой части, лицензии проверены."),
        ("GA", "Архитектура", lambda x: "%s из 10" % x.get("score"),
         "Независимый критик оценил устройство продукта по длинному списку требований."),
        ("G1", "Ни одно требование не потеряно", lambda x: "разобрано %s" % x.get("total"),
         "Каждая твоя фраза стала строкой списка и дошла до конца."),
        ("G2", "Сверка описания с твоей задачей", lambda x: "найдено %s, исправлено %s" % (x.get("found"), x.get("fixed")),
         "Отдельный проверяющий читал только твою задачу и описание будущей работы."),
        ("G3", "Каждое требование попало в работу", lambda x: "проблем: %s" % (x.get("problems") or 0),
         "Ни одно требование не осталось без куска работы."),
        ("G4", "Слепая приёмка", lambda x: "совпало %s из %s" % (x.get("matched"), x.get("checked")),
         "Проверяющий не видел нашей документации и сверял готовое с твоей задачей."),
    )
    for key, title, value, meaning in rows:
        if key in g:
            out.append({"t": title, "v": value(g[key]), "s": meaning, "ok": bool(g[key].get("ok"))})
    return out


def run_report(r, st):
    stage_state = {"done": "done", "active": "active", "skipped": "skipped", "failed": "active"}
    stages = [{"name": RU_STAGE.get(s["id"], s["id"]), "state": stage_state.get(s.get("status"), "pending"),
               "note": s.get("note") if s.get("status") == "skipped" else None}
              for s in st.get("stages") or [] if s.get("id") in RU_STAGE]
    tickets = st.get("tickets") or []
    done = sum(1 for t in tickets if t.get("status") == "done")
    req = st.get("requirements") or {}
    in_work = sum(req.get(k, 0) for k in ("inTicket", "inSpec", "placeholder"))
    awaiting = sum(1 for t in tickets if t.get("status") == "awaiting_owner")
    not_done = ["%s — %s" % (x["text"], x["why"]) if x.get("why") else x["text"]
                for x in st.get("reqList") or [] if x.get("status") in ("deferred", "dropped")]
    start = date_of(st.get("startedAt"))
    end = date_of(st.get("finishedAt"))
    return {"id": r["id"], "name": r["plain"] or r["title"], "plain": r["gives"],
            "statusLabel": "Сдан" if st.get("finishedAt") else "Идёт",
            "dates": (span_text(start, end) if end else "начат %s" % day_text(start)) if start else "",
            "brief": brief_text(st), "stages": stages,
            "tasks": {"done": done, "total": len(tickets),
                      "note": ("%d ждут твоего взгляда" % awaiting) if awaiting else ""},
            "requirements": "Требований %d: готово %d, в работе %d, отложено %d"
                            % (req.get("total", 0), req.get("done", 0), in_work, req.get("deferred", 0)),
            "reqBar": {"done": req.get("done", 0), "prog": in_work, "later": req.get("deferred", 0)},
            "checks": run_checks(st), "assumptions": (st.get("debt") or {}).get("assumptions") or [],
            "notDone": not_done + (st.get("report") or []), "plan": run_plan(st), "nowDoing": ""}


def project_arch():
    a = arch_read()
    if not a or not a.get("rounds"):
        return None
    gated = [r for r in a["rounds"] if r.get("kind") != "as-built"]
    last = gated[-1] if gated else a["rounds"][-1]
    g = a.get("gate") or {}
    audit = json_read(os.path.join(ROOT, last["file"]), {})
    crit = audit.get("criteria") or {}
    names = [(n, crit[k]) for k, _, n, _ in ARCH_CRITERIA if k in crit and "na" not in crit[k]]
    built = [r for r in a["rounds"] if r.get("kind") == "as-built"][-1:]
    label = ("Принята с оговоркой владельца" if g.get("waived") else "Принята, подтвердил второй критик") if g.get("ok") \
        else "Идёт доработка"
    return {"score": last["overall"], "pass": ARCH_PASS, "ok": bool(g.get("ok")), "statusLabel": label,
            "summary": last.get("summary") or "",
            "rounds": [{"n": i + 1, "overall": r["overall"], "kind": r["kind"]} for i, r in enumerate(gated)],
            "criteria": [{"name": n, "score": round(c["score"], 1)} for n, c in names],
            "asBuilt": {"score": built[0]["overall"], "summary": built[0].get("summary") or ""} if built else None}


def project_reuse():
    data = scout_read()
    if not data or not data.get("capabilities"):
        return None
    taken, own = [], []
    for c in data["capabilities"]:
        (taken if c.get("decision") in ("adopt", "adapt", "fork") else own).append(
            {"name": c.get("name") or c.get("id"), "why": c.get("why") or "", "choice": c.get("choice") or ""})
    return {"taken": taken, "own": own}


def project_spend(saved, st):
    s = dict(saved.get("spend") or {})
    p = (st or {}).get("pacing") or {}
    if not s.get("windows"):
        pairs = (("Вся неделя", p.get("weekly_used_pct")), ("Окно пяти часов", p.get("window_used_pct")))
        s["windows"] = [{"label": n, "used": v} for n, v in pairs if v is not None]
    s.setdefault("ceiling", 80)
    return s


def project_timeline(rows, milestones, sched, today, tz):
    t0, t1 = "T00:00:00" + tz, "T23:59:00" + tz
    out = []
    for r in rows:
        a, b = sched[r["id"]]
        row = {"plain": r["plain"] or r["title"], "run": r["id"], "gives": r["gives"],
               "start": a.isoformat() + t0, "end": b.isoformat() + t1}
        if r["status"] == "landed":
            row.update(kind="done", group="done", dateText=span_text(a, b))
        elif r["status"] == "in-flight":
            row.update(kind="active", group="now", dateText="примерно до " + day_text(b))
        else:
            row.update(kind="estimate", group="ahead", dateText="примерно " + span_text(a, b))
            if r["status"] == "blocked":
                row["dateText"] = "ждёт решения: " + r["result"]
        out.append(row)
    by_id = {r["id"]: r for r in rows}
    for m in milestones:
        ends = [sched[x][1] for x in m["after"] if x in sched]
        at = max(ends) if ends else today
        ready = bool(m["after"]) and all(by_id.get(x, {}).get("status") == "landed" for x in m["after"])
        out.append({"plain": m["title"], "run": m["id"], "gives": m["gives"], "kind": "milestone", "group": "milestone",
                    "at": at.isoformat() + t1, "dateText": "уже можно" if ready else "примерно " + day_text(at)})
    return out


def project_title(lines, saved):
    if saved.get("title"):
        return saved["title"]
    m = next((re.match(r"^#\s*Программа\s*[—–-]\s*(.+)$", x) for x in lines if x.startswith("#")), None)
    return m.group(1).strip() if m else "Проект"


def project_progress(rows, sts, saved, spend):
    weights = {r["id"]: r["tickets"] or PROGRAM_DEFAULT_TICKETS for r in rows}
    done = 0
    for r in rows:
        if r["status"] == "landed":
            done += weights[r["id"]]
        elif r["status"] == "in-flight":
            done += min(weights[r["id"]], sum(1 for t in (sts.get(r["id"]) or {}).get("tickets") or [] if t.get("status") == "done"))
    total = sum(weights.values()) or 1
    landed = sum(1 for r in rows if r["status"] == "landed")
    tests = next(((sts.get(r["id"]) or {}).get("tests") for r in reversed(rows) if (sts.get(r["id"]) or {}).get("tests")), None)
    return weights, {
        "percent": int(round(done * 100 / total / 5.0) * 5), "done": done, "total": total,
        "percentLabel": "всей работы по проекту сделано",
        "method": "Считается по планам прогонов: %d из %d запланированных кусков работы (тасков) уже сделаны. Округлено до 5 %%." % (done, total),
        "howTo": saved.get("howTo") or "Каждая часть полосы — прогон, её ширина — сколько в нём работы.",
        "tiles": {"workLabel": "Сделано работы", "work": "кусков работы (тасков) готово. Всего столько запланировано.",
                  "runsValue": str(landed), "runsOf": "из %d" % len(rows), "runs": "прогонов сдано целиком",
                  "tests": str(tests["passed"]) if tests else "—",
                  "testsOk": ("все прошли" if not tests["failed"] else "упало %d" % tests["failed"]) if tests else "ещё нет",
                  "testsNote": "автоматических проверок последнего прогона",
                  "limit": spend.get("paceLabel") or ""}}


def project_now(saved, rows, sts, landed_n):
    n = saved.get("now") or {}
    flying = next((r for r in rows if r["status"] == "in-flight"), None)
    state = "Идёт сейчас: " + (flying["plain"] or flying["title"]) if flying else (
        "Проект сдан" if rows and landed_n == len(rows) else "Сейчас ни один прогон не идёт")
    head = "Сдано %d %s из %d." % (landed_n, plural_ru(landed_n, "прогон", "прогона", "прогонов"), len(rows))
    return {"state": n.get("state") or state, "headline": n.get("headline") or head,
            "sentence": n.get("sentence") or "", "aside": n.get("aside") or ""}


def project_data():
    lines = program_lines()
    if lines is None:
        return None
    rows, saved = program_rows(lines), json_read(PROJECT_STATE, {})
    stamp = now()
    today, tz = date_of(stamp), stamp[-6:]
    sts = run_states(rows)
    live = read_state()
    spend = project_spend(saved, live)
    weights, progress = project_progress(rows, sts, saved, spend)
    nxt = next_runnable(rows)
    sched = program_schedule(rows, today, program_parallel(lines))
    status = {"landed": "landed", "in-flight": "now", "blocked": "blocked"}
    runs = [{"id": r["id"], "name": r["title"], "plain": r["plain"] or r["title"], "gives": r["gives"], "weight": weights[r["id"]],
             "status": status.get(r["status"], "next" if nxt and nxt["id"] == r["id"] else "pending")} for r in rows]
    timeline = project_timeline(rows, program_milestones(lines), sched, today, tz)
    dates = [x[0] for x in sched.values()] + [x[1] for x in sched.values()] + [today]
    pad = dt.timedelta(days=max(3, (max(dates) - min(dates)).days // 6))
    landed = [r for r in rows if r["status"] == "landed" and r["id"] in sts]
    flying = next((r for r in rows if r["status"] == "in-flight" and r["id"] in sts), None)
    current = run_report(flying, sts[flying["id"]]) if flying else None
    if current:
        current["nowDoing"] = (saved.get("runNotes") or {}).get(flying["id"], "")
    landed_n = sum(1 for r in rows if r["status"] == "landed")
    return {"meta": {"title": project_title(lines, saved), "asOf": stamp, "tz": tz,
                     "asOfLabel": "%s, %s" % (day_text(today), stamp[11:16]),
                     "note": "Страница обновляется сама, когда меняется ход работ."},
            "now": project_now(saved, rows, sts, landed_n), "progress": progress, "runs": runs,
            "gantt": {"start": min(dates).isoformat(), "end": (max(dates) + pad).isoformat(), "rows": timeline,
                      "basisShort": "Даты впереди — оценка: сколько дней занимает прогон и что от чего зависит.",
                      "basisTitle": "Как посчитаны сроки",
                      "basis": ["Сданные прогоны показаны по настоящим датам.",
                                "Для остальных берётся оценка дней из плана и порядок зависимостей.",
                                "Одновременно идёт прогонов: %d." % program_parallel(lines)]},
            "changes": saved.get("changes") or {"sinceLabel": "", "items": []},
            "arch": project_arch(), "reuse": project_reuse(), "currentRun": current,
            "pastRuns": [run_report(r, sts[r["id"]]) for r in reversed(landed)],
            "spend": spend, "glossary": saved.get("glossary") or GLOSSARY}


# ── вопросы владельцу и его ручные дела ─────────────────────────────────────

def questions_read():
    return json_read(QUESTIONS, {"nextId": 1, "open": [], "manual": [], "resolved": []})


def questions_view(saved=None):
    q = dict(questions_read())
    saved = json_read(PROJECT_STATE, {}) if saved is None else saved
    stamp = date_of(now())
    q.update(key=re.sub(r"\W+", "-", str(saved.get("title") or "project")), listDateLabel=day_text(stamp),
             nextListLabel=saved.get("nextList") or "",
             heroNote=saved.get("heroNote") or "Работа из-за этих вопросов не стоит.",
             manualNote=saved.get("manualNote") or "Это может сделать только ты: пароли, твои аккаунты, твоё разрешение.")
    return q


QUESTION_FIELDS = (("title", "о чём вопрос"), ("about", "контекст: откуда вопрос и почему важен"),
                   ("agrees", "на что соглашается владелец"), ("recommend", "рекомендация"),
                   ("why", "почему так советуем"), ("silence", "что будет, если промолчит"))


def cmd_question(pos, opt, multi=None):
    act = pos[0] if pos else "list"
    q = questions_read()
    if act == "add":
        missing = [m for k, m in QUESTION_FIELDS if not text_of(opt.get(k))]
        if missing:
            die("вопрос владельцу должен читаться без других страниц, не хватает: " + "; ".join(missing))
        item = {k: opt[k] for k, _ in QUESTION_FIELDS}
        item.update(id=q["nextId"], urgency=opt.get("urgency") if isinstance(opt.get("urgency"), str) else "Работу не останавливает")
        if isinstance(opt.get("before"), str):
            item["before"] = opt["before"]
        q["nextId"] += 1
        q["open"].append(item)
        json_write(QUESTIONS, q)
        return ["вопрос %d добавлен" % item["id"]] + project_refresh()
    if act == "answer":
        if len(pos) < 2 or not isinstance(opt.get("by-user"), str):
            die("question answer N --by-user \"его слова\" [--decision \"что решено\"]")
        hit = next((x for x in q["open"] if str(x["id"]) == pos[1]), None)
        if hit is None:
            die("открытого вопроса %s нет" % pos[1])
        q["open"].remove(hit)
        q["resolved"].insert(0, {"date": day_text(date_of(now())), "title": hit["title"], "answer": opt["by-user"],
                                 "decision": opt.get("decision") if isinstance(opt.get("decision"), str) else hit["recommend"]})
        json_write(QUESTIONS, q)
        return ["вопрос %s закрыт" % pos[1]] + project_refresh()
    if act == "list":
        return question_digest(q)
    die("question add | answer | list")


def question_digest(q):
    """Текст для чата: на каждый вопрос можно ответить, не открывая ни одной страницы."""
    if not q["open"] and not q["manual"]:
        return ["от владельца сейчас ничего не нужно"]
    out = []
    for x in q["open"]:
        out += ["%d. %s" % (x["id"], x["title"]), "   О чём: " + x["about"], "   На что соглашаешься: " + x["agrees"],
                "   Совет: %s %s" % (x["recommend"], x["why"]), "   Если промолчишь: " + x["silence"],
                "   Ответ: «%d ок» или свой вариант" % x["id"]]
    for m in q["manual"]:
        out += ["Руками — %s" % m["title"], "   Почему только ты: " + m["onlyYou"], "   Зачем: " + m["why"]]
        out += ["   %d) %s" % (i + 1, s) for i, s in enumerate(m["steps"])]
    return out


def cmd_manual(pos, opt, multi=None):
    if len(pos) < 2 or pos[0] not in ("add", "done"):
        die("manual add KEY --title … --only-you … --why … --step … | manual done KEY --by-user \"…\"")
    act, key = pos[0], pos[1]
    q = questions_read()
    if act == "add":
        steps = (multi or {}).get("step") or []
        if not all(text_of(opt.get(k)) for k in ("title", "only-you", "why")) or not steps:
            die("ручное дело: --title, --only-you (почему не может агент), --why и хотя бы один --step")
        q["manual"].append({"id": key, "title": opt["title"], "onlyYou": opt["only-you"], "why": opt["why"], "steps": steps,
                            "short": opt.get("short") if isinstance(opt.get("short"), str) else opt["title"],
                            "urgency": opt.get("urgency") if isinstance(opt.get("urgency"), str) else ""})
    else:
        hit = next((x for x in q["manual"] if x["id"] == key), None)
        if hit is None or not isinstance(opt.get("by-user"), str):
            die("manual done KEY --by-user \"его слова\" — и такое дело должно быть в списке")
        q["manual"].remove(hit)
        q["resolved"].insert(0, {"date": day_text(date_of(now())), "title": hit["title"], "answer": opt["by-user"], "decision": "сделано"})
    json_write(QUESTIONS, q)
    return ["ручное дело %s: %s" % (key, "записано" if act == "add" else "закрыто")] + project_refresh()


# ── сборка страниц ──────────────────────────────────────────────────────────

def project_template(name):
    """Шаблон страницы: свежий из навыка, иначе сохранённая копия рядом со страницей."""
    keep = os.path.join(PROJECT_DIR, "templates", name)
    src = os.path.join((read_state() or {}).get("skillDir") or "", "report", name)
    if os.path.isfile(src):
        os.makedirs(os.path.dirname(keep), exist_ok=True)
        shutil.copyfile(src, keep)
    try:
        return open(keep, encoding="utf-8").read()
    except OSError:
        return None


def page_lint(node, where=""):
    """Страницу читает владелец: без кодов, жаргона, путей и секретов."""
    if isinstance(node, dict):
        return [x for k, v in node.items() if k not in LINT_KEYS_SKIP for x in page_lint(v, k)]
    if isinstance(node, list):
        return [x for v in node for x in page_lint(v, where)]
    if isinstance(node, str):
        return ["%s: %s — «%s»" % (why, where, m.group(0)) for rx, why in PAGE_LINT for m in [rx.search(node)] if m]
    return []


def page_json(data):
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def project_write():
    """Две страницы: ход проекта и вопросы. Данные внутри, поэтому открываются двойным кликом."""
    p = project_data()
    if p is None:
        return None
    index, questions = project_template("project-template.html"), project_template("questions-template.html")
    if index is None or questions is None:
        return ["! шаблонов страницы нет: нужен skillDir в state.js или .autopilot/project/templates/"]
    q = questions_view({"title": p["meta"]["title"], **json_read(PROJECT_STATE, {})})
    title = p["meta"]["title"]
    os.makedirs(PROJECT_DIR, exist_ok=True)
    for name, tpl, data, heading in (("index.html", index, {"p": p, "q": q}, "%s: ход проекта" % title),
                                     ("questions.html", questions, q, "%s: вопросы" % title)):
        html = tpl.replace("__TITLE__", heading.replace("&", "&amp;").replace("<", "&lt;")).replace("__DATA__", page_json(data))
        with open(os.path.join(PROJECT_DIR, name), "w", encoding="utf-8") as f:
            f.write(html)
    return ["! страница: " + x for x in page_lint(p) + page_lint({k: q[k] for k in ("open", "manual")})][:20]


def project_refresh():
    """Страница не отстаёт от работы: пересобирается сама, если у проекта есть программа."""
    if not os.path.isfile(PROGRAM):
        return []
    return project_write() or []


def project_save_text(saved, pos, opt, multi):
    act = pos[0]
    if act == "now":
        saved["now"] = {k: opt[k] for k in ("state", "headline", "sentence", "aside") if isinstance(opt.get(k), str)}
    elif act == "change":
        if len(pos) < 2:
            die("project change \"что изменилось\" [--since \"с 8 ноября\"]")
        ch = saved.setdefault("changes", {"sinceLabel": "", "items": []})
        if isinstance(opt.get("since"), str):
            ch.update(sinceLabel=opt["since"], items=[])
        ch["items"].append(pos[1])
    elif act == "spend":
        s = saved.setdefault("spend", {})
        pairs = [x.partition("=") for x in (multi or {}).get("window", [])]
        if pairs:
            s["windows"] = [{"label": a, "used": num(b)} for a, _, b in pairs]
        for key in ("verdict", "ceilingLabel", "resetLabel", "paceLabel", "moneyCap", "moneyVerdict", "moneyNote"):
            flag = re.sub(r"[A-Z]", lambda m: "-" + m.group(0).lower(), key)
            if isinstance(opt.get(flag), str):
                s[key] = opt[flag]
        if isinstance(opt.get("ceiling"), str):
            s["ceiling"] = num(opt["ceiling"])
    elif act in ("title", "url", "next-list"):
        if len(pos) < 2:
            die("project %s \"значение\"" % act)
        saved[{"title": "title", "url": "url", "next-list": "nextList"}[act]] = pos[1]
    elif act == "run":
        if len(pos) < 2 or not isinstance(opt.get("now"), str):
            die("project run P03 --now \"что делает прогон сейчас\"")
        saved.setdefault("runNotes", {})[pos[1]] = opt["now"]
    else:
        die("project | now | change | spend | title | url | next-list | run | lint")


def cmd_project(pos, opt, multi=None):
    if lint_only := pos[:1] == ["lint"]:
        pos = []
    if pos:
        saved = json_read(PROJECT_STATE, {})
        project_save_text(saved, pos, opt, multi)
        json_write(PROJECT_STATE, saved)
    notes = project_write()
    if notes is None:
        die("у проекта нет программы — .autopilot/program.md пишется по phases/0-program.md")
    url = json_read(PROJECT_STATE, {}).get("url")
    if lint_only:
        return notes or ["на странице чисто"]
    p = json.loads(re.search(r'id="data" type="application/json">(.*?)</script>',
                             open(os.path.join(PROJECT_DIR, "index.html"), encoding="utf-8").read(), re.S).group(1))
    return ["страница: .autopilot/project/index.html" + (" · адрес: " + url if url else ""),
            "сделано примерно %d %%: %s %s прогонов" % (p["p"]["progress"]["percent"], p["p"]["progress"]["tiles"]["runsValue"],
                                                       p["p"]["progress"]["tiles"]["runsOf"]),
            "ждёт владельца: вопросов %d, дел руками %d" % (len(p["q"]["open"]), len(p["q"]["manual"]))] + notes


# ── команды ─────────────────────────────────────────────────────────────────

def parse_args(argv):
    pos, opt, multi = [], {}, {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            key = a[2:]
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                opt[key] = argv[i + 1]
                multi.setdefault(key, []).append(argv[i + 1])
                i += 2
                continue
            opt[key] = True
        else:
            pos.append(a)
        i += 1
    return pos, opt, multi


def tests_pair(v):
    m = re.match(r"^\s*(\d+)\s*(?:/\s*(\d+))?\s*$", str(v))
    if not m:
        die("тесты пишутся как ПРОШЛО/УПАЛО, например 34/0")
    return {"passed": int(m.group(1)), "failed": int(m.group(2) or 0)}


def cmd_init(opt):
    if not opt.get("slug"):
        die("init требует --slug")
    old = read_state()
    notes = []
    if old and not old.get("finishedAt") and not opt.get("force"):
        die("идёт прогон %s — это продолжение, а не новый прогон (или --force)" % old.get("dir"))
    if old and old.get("dir") and os.path.isdir(os.path.join(A, old["dir"])):
        dst = os.path.join(old["dir"], "state.js")
        if subprocess.run(["git", "-C", A, "mv", "-f", "state.js", dst], capture_output=True).returncode:
            os.replace(STATE, os.path.join(A, dst))
        notes.append("прошлый прогон убран в архив: %s" % dst)
    state = fresh_state(opt)
    log(state, "init")
    os.makedirs(os.path.join(run_dir(state), "tickets"), exist_ok=True)
    if isinstance(opt.get("program"), str):
        state["program"] = opt["program"]
        notes.append(program_set(opt["program"], "in-flight", d=state["dir"], started=state["startedAt"][:10]))
    save(state)
    ensure_gitignore()
    register_row(state, "в работе", None)
    notes.append("папка прогона: .autopilot/%s" % state["dir"])
    return state, notes


def cmd_stage(state, pos, opt):
    if not pos:
        die("stage <id> [done|skip|fail] [--note …]")
    sid, action = pos[0], (pos[1] if len(pos) > 1 else "start")
    if sid not in ORDER:
        die("этапы: " + ", ".join(ORDER))
    s = stage(state, sid)
    t = now()
    if action == "start":
        s["status"] = "active"
        s.setdefault("startedAt", t)
        s.pop("finishedAt", None)
    elif action == "done":
        s["status"] = "done"
        s.setdefault("startedAt", t)
        s["finishedAt"] = t
    elif action in ("skip", "fail"):
        if not opt.get("note"):
            die("%s требует --note с причиной" % action)
        s["status"] = "skipped" if action == "skip" else "failed"
        s.setdefault("startedAt", t)
        s["finishedAt"] = t
    else:
        die("действие этапа: start | done | skip | fail")
    if isinstance(opt.get("note"), str):
        s["note"] = opt["note"]
    if sid == "spec" and action in ("start", "done"):
        ls_arch_guard(state)
        refresh_g1(state, create=True)
    if sid == "architecture" and action in ("start", "done"):
        ls_scout_guard(state)
    if sid == "scout" and action == "done" and not scout_passed():
        die("поиск готового не проверен: `scout verify`, потом `scout check`")
    if sid == "architecture" and action == "done" and not arch_accepted():
        die("архитектура не принята: `arch status`")
    log(state, "stage", id=sid, act=action,
        note=opt["note"] if action in ("skip", "fail") and isinstance(opt.get("note"), str) else None)


def close_requirements(state, tk, opt, t):
    """Требование закрыто, когда закрыты все таски, где оно названо. --placeholder R05
    помечает его заглушкой вместо done: там стоит видимая метка вместо данных пользователя."""
    ph = set(re.findall(r"[RGD]\d+[a-z]?", str(opt.get("placeholder") or "")))
    rows = dict(manifest_rows(state) or [])
    tickets = state.get("tickets") or []
    changes = {}
    for r in {x.split(".")[0] for x in tk.get("requirements", [])}:
        if rows.get(r) not in ("in-ticket", "in-spec", "open"):
            continue
        holders = [x for x in tickets if r in {y.split(".")[0] for y in x.get("requirements", [])}]
        if all(x is tk or x.get("status") == "done" for x in holders):
            changes[r] = ("placeholder" if r in ph else "done",
                          (opt.get("commit")[:7] if isinstance(opt.get("commit"), str) else None))
    manifest_update(state, changes)


CAP = 2      # дозапросов и свежих перезапусков на таск — phases/5-repair.md


def refuse_ticket(tk, act, by_user, commit):
    """Лимиты ремонта — не совет, а отказ: оркестратор долгого прогона забывает
    текст правила, а отказ команды забыть нельзя. Упавший таск снова пускает
    в работу только пользователь — его словами в --by-user."""
    i = tk["id"]
    if tk.get("status") == "failed":
        if act == "reset" and by_user:
            return
        die("таск %s упал — дальше решает пользователь. Скажи ему, что блокирует, и жди ответа; "
            "перезапуск только по его словам: ticket %s reset --by-user \"<цитата>\"" % (i, i))
    if act == "retry" and tk.get("retries", 0) >= CAP:
        die("таск %s: два свежих перезапуска уже были — третьего нет. "
            "ticket %s fail --note \"что блокирует\" и вопрос пользователю" % (i, i))
    if act == "repair" and tk.get("repairs", 0) >= CAP:
        die("таск %s: два дозапроса уже были — дальше свежий контекст (ticket %s retry) "
            "или fail с вопросом пользователю" % (i, i))
    if act == "done" and not commit and not tk.get("commit"):
        die("таск %s: нет --commit — сдан только закоммиченный таск. Git отказал — это сбой машины, "
            "не ремонт: ticket %s fail --note \"что ответил git\" и вопрос пользователю" % (i, i))


def cmd_ticket(state, pos, opt):
    acts = [p for p in pos if p in TICKET_STATUSES]
    ids = [p for p in pos if p not in TICKET_STATUSES]
    if len(acts) != 1 or not ids:
        die("ticket <id…> start|review|repair|done|fail|retry|reset|await")
    act = acts[0]
    known = {t["id"]: t for t in state.get("tickets") or []}
    by_user = opt.get("by-user") if isinstance(opt.get("by-user"), str) else None
    t = now()
    ls_night_guard(state, act, ids)
    ls_pacing_guard(state, act, ids)
    ls_owner_guard(state, act, ids, opt)
    for i in ids:                                    # сначала все отказы — потом запись
        tk = known.get(i)
        if tk is None:
            die("таска %s нет — сначала `ap.py tickets`" % i)
        refuse_ticket(tk, act, by_user, opt.get("commit") if isinstance(opt.get("commit"), str) else None)
    notes = []
    for i in ids:
        tk = known[i]
        notes.append(record_attempt(state, tk, act, opt))
        record_session(state, tk, act, opt)
        record_owner(state, tk, act, opt)
        tk["status"] = TICKET_STATUSES[act]
        if act == "start":
            tk.setdefault("startedAt", t)
            tk.pop("finishedAt", None)
        elif act == "retry":
            tk["retries"] = tk.get("retries", 0) + 1
            tk["startedAt"] = tk.get("startedAt") or t
        elif act == "repair":
            tk["repairs"] = tk.get("repairs", 0) + 1
            if isinstance(opt.get("note"), str):
                tk.setdefault("repairFindings", []).append(opt["note"])
        elif act in ("done", "fail"):
            tk.setdefault("startedAt", t)
            tk["finishedAt"] = t
            if act == "fail" and isinstance(opt.get("note"), str):
                tk.setdefault("concerns", []).append(opt["note"])
        elif act == "reset":
            for k in ("startedAt", "finishedAt"):
                tk.pop(k, None)
            if by_user:
                tk.setdefault("reopenedByUser", []).append(by_user)
                tk["repairs"] = tk["retries"] = 0
        if act == "done":
            close_requirements(state, tk, opt, t)
            record_landing(tk, opt)
        elif act == "review":
            record_landing(tk, opt)            # форк: prompt-таск влит, ревью — до await
        if opt.get("tests"):
            tk["tests"] = tests_pair(opt["tests"])
            state["tests"] = tk["tests"]
        if isinstance(opt.get("commit"), str):
            tk["commit"] = opt["commit"][:12]
    log(state, "ticket", ids=ids, act=act, tests=tests_pair(opt["tests"]) if opt.get("tests") else None,
        note=opt["note"] if act in ("repair", "fail") and isinstance(opt.get("note"), str)
        else by_user if act == "reset" else None)
    ls_night_record(state, act, ids)
    return [n for n in notes if n]


def cmd_set(state, pos):
    for p in pos:
        k, _, v = p.partition("=")
        if not _ or k in ("stages", "tickets", "requirements"):
            die("set key=value (скалярные поля верхнего уровня)")
        state[k] = None if v in ("", "null") else v


def cmd_add(state, pos):
    if len(pos) < 2 or pos[0] not in LISTS:
        die("add <%s> \"текст\"" % "|".join(sorted(LISTS)))
    key, vals = pos[0], pos[1:]
    if key.startswith("debt."):
        tgt = state.setdefault("debt", {}).setdefault(key[5:], [])
    else:
        tgt = state.setdefault(key, [])
    fresh = [v for v in vals if v not in tgt]
    tgt.extend(dict.fromkeys(fresh))
    if fresh:
        log(state, "add", key=key, n=len(fresh))


NUMBERS = {"coverage": ("found", "fixed", "deferred"), "blind": ("checked", "matched")}
BLIND_ROUNDS = 2    # слепая приёмка и одна перепроверка — phases/8-final.md


def cmd_numbers(state, name, pos, multi):
    """Гейт решают числа, поэтому без всех чисел команда ничего не пишет: пропавший
    счётчик — не ноль, а незаписанный результат."""
    keys = NUMBERS[name]
    usage = "%s %s" % (name, " ".join(k + "=N" for k in keys))
    d = {}
    for p in pos:
        k, eq, v = p.partition("=")
        if not eq or k not in keys or not v.isdigit():
            die("%s: не понял «%s» — пишется так: %s" % (name, p, usage))
        d[k] = int(v)
    missing = [k for k in keys if k not in d]
    if missing:
        die("%s: нет %s — пишется так: %s" % (name, ", ".join(missing), usage))
    if name == "blind":
        if d["matched"] > d["checked"]:
            die("blind: matched=%d больше checked=%d" % (d["matched"], d["checked"]))
        # Приёмка и одна перепроверка после таска F2 — третьего круга нет:
        # каждый прогон находит новое, и «ещё один круг» не кончается никогда.
        rounds = state.get("blindRounds", 0)
        if rounds >= BLIND_ROUNDS:
            die("blind: приёмка и её перепроверка уже были — третьего круга нет. "
                "Что ещё расходится — add report \"…\" и в отчёт как известный баг")
        state["blindRounds"] = rounds + 1
        d["mismatches"] = multi.get("mismatch", [])
        state[name] = d
        set_gate(state, "G4", not d["mismatches"], checked=d["checked"], matched=d["matched"])
    else:
        d["items"] = multi.get("item", [])
        state[name] = d
        set_gate(state, "G2", d["found"] <= d["fixed"] + d["deferred"],
                 found=d["found"], fixed=d["fixed"], deferred=d["deferred"])


def cmd_ask(state, pos, opt):
    """Сборка ждёт пользователя: раунд брифинга, ручной гейт, вопрос перед необратимым."""
    kind = pos[0] if pos else ""
    if kind not in WAIT_KINDS:
        die("ask <%s> --note \"что ждём, одной строкой\"" % "|".join(WAIT_KINDS))
    w = state.get("waiting")
    if w and w.get("kind") != kind:
        close_wait(state)
        w = None
    note = opt.get("note") if isinstance(opt.get("note"), str) else None
    state["waiting"] = {"kind": kind, "since": w["since"] if w else state["updatedAt"], "note": note}
    log(state, "ask", kind=kind, note=note)


def landing_problems(state):
    """Что мешает назвать сборку сданной: (отказ, оговорка). Отказ останавливает finish;
    оговорка — расхождение, оставшееся после обеих приёмок: чинить его больше нечем,
    сборка сдаётся, но не зелёной."""
    refuse, caveat = [], []
    gates = state.get("gates") or {}
    g = gates.get("G1")
    if g is None:
        refuse.append("G1: манифест не проверен")
    elif not g["ok"]:
        refuse.append("G1: открытых требований — %s" % g.get("open"))
    for gid, what in (("G2", "спецификация не сверена с брифом"), ("G3", "трасса манифест ↔ таски не сверена")):
        if gid not in gates:
            refuse.append("%s: %s" % (gid, what))
        elif not gates[gid]["ok"]:
            refuse.append("%s: не пройден" % gid)
    g = gates.get("G4")
    if g is None:
        refuse.append("G4: слепой приёмки не было")
    elif not g["ok"]:
        line = "G4: расхождений с брифом — %d" % len((state.get("blind") or {}).get("mismatches") or [])
        (caveat if state.get("blindRounds", 0) >= BLIND_ROUNDS else refuse).append(line)
    for tk in state.get("tickets") or []:
        if tk.get("status") != "done":
            refuse.append("таск %s: %s" % (tk["id"], tk.get("status")))
        elif not tk.get("commit"):
            refuse.append("таск %s: сдан без коммита" % tk["id"])
    refuse += ["таск %s: коммита %s нет в истории" % pair for pair in lost_commits(state)]
    refuse += ls_arch_landing(state)
    return refuse, caveat


def cmd_finish(state, opt):
    refresh_g1(state, create=True)
    refuse, caveat = landing_problems(state)
    by_user = opt.get("by-user") if isinstance(opt.get("by-user"), str) else None
    if refuse and not by_user:
        die("сборка не сдана:\n  ! %s\nПочини это. Починить нельзя — скажи пользователю, что не так; "
            "сдать как есть можно только по его словам: finish --result \"…\" --by-user \"<цитата>\""
            % "\n  ! ".join(refuse))
    t = now()
    notes = []
    for s in state.get("stages") or []:
        if s.get("status") in ("active", "pending") and s.get("id") == "final":
            s["status"], s["finishedAt"] = "done", t
            s.setdefault("startedAt", t)
        elif s.get("status") == "active":
            s["status"], s["finishedAt"] = "done", t
        elif s.get("status") == "pending":
            s["status"], s["note"], s["finishedAt"] = "skipped", s.get("note") or "не понадобился", t
    problems = refuse + caveat
    if problems:
        state["landedWith"] = dict({"problems": problems}, **({"byUser": by_user} if refuse else {}))
        notes += ["! сдано с оговоркой — " + p for p in problems]
    result = opt.get("result") if isinstance(opt.get("result"), str) else None
    return notes + land_run(state, result, problems, by_user, "сдан с оговорками" if problems else "сдан")


def land_run(state, result, problems, by_user, label):
    """Общая посадка: папка без --wip, конец прогона, строка в README и в программе."""
    t = state["updatedAt"]
    notes = []
    d = state.get("dir") or ""
    if d.endswith("--wip"):
        new = d[: -len("--wip")]
        if os.path.exists(os.path.join(A, new)):
            notes.append("! папка %s уже есть — оставляю %s" % (new, d))
        elif git_mv(d, new):
            state["dir"] = new
            notes.append("папка прогона: .autopilot/%s" % new)
        else:
            notes.append("! не смог переименовать %s — оставляю как есть" % d)
    state["finishedAt"] = t
    state["result"] = result
    register_row(state, label, state["result"])
    log(state, "finish", result=state["result"], problems=len(problems))
    if state.get("program"):
        notes.append(program_set(state["program"], "landed", d=state["dir"], result=state["result"],
                                 landed=t[:10], tickets=len(state.get("tickets") or []) or None))
    return notes


def cmd_reopen(state):
    """Второй бриф в сданном прогоне: фазы 1–8 идут заново, прежние таски остаются."""
    d = state.get("dir") or ""
    if not d.endswith("--wip") and git_mv(d, d + "--wip"):
        state["dir"] = d + "--wip"
    state["finishedAt"] = None
    state["blind"] = None
    state["blindRounds"] = 0
    for s in state.get("stages") or []:
        if s.get("id") != "preflight":
            for k in ("startedAt", "finishedAt", "note"):
                s.pop(k, None)
            s["status"] = "pending"
    stage(state, "manifest").update(status="active", startedAt=now())
    state["result"] = None
    state.pop("landedWith", None)
    state["gates"] = {}
    register_row(state, "в работе", None)
    log(state, "reopen")


def lost_commits(state):
    """[(таск, sha)] — сданные таски, чьего коммита нет в HEAD."""
    lost = []
    for tk in state.get("tickets") or []:
        c = tk.get("commit")
        if tk.get("status") != "done" or not c:
            continue
        r = subprocess.run(["git", "-C", ROOT, "merge-base", "--is-ancestor", c, "HEAD"],
                           capture_output=True)
        if r.returncode:
            lost.append((tk["id"], c))
    return lost


def cmd_commits(state):
    """Возобновление верит state.js, а история могла уйти из-под него: reset, rebase,
    другая ветка. Сданный таск, чьего коммита нет в HEAD, — строка «!»; сбрасывает
    его оркестратор, потому что код после rebase может лежать на месте под другим sha."""
    return (["! таск %s: коммита %s нет в истории — `ap.py ticket %s reset`" % (i, c, i)
             for i, c in lost_commits(state)] or ["коммиты сданных тасков на месте"])


PROJECT_COMMANDS = {"program": cmd_program, "arch": cmd_arch, "scout": cmd_scout, "project": cmd_project,
                    "question": cmd_question, "manual": cmd_manual}


def main():
    argv = sys.argv[1:]
    # Справка ничего не трогает: ни state.js, ни гейты, ни сервер.
    if "--help" in argv or "-h" in argv or argv[:1] == ["help"]:
        print(__doc__.strip())
        return
    if "--stop-now" in argv:
        stop_now()
        return
    pos, opt, multi = parse_args(argv)
    cmd = pos[0] if pos else ""
    notes = []
    if cmd in PROJECT_COMMANDS:          # проект живёт между прогонами: state.js этим командам не нужен
        for line in PROJECT_COMMANDS[cmd](pos[1:], opt, multi):
            print("  " + (line if line.startswith("!") else "· " + line))
        return
    if cmd == "init":
        state, notes = cmd_init(opt)
    else:
        state = read_state()
        if state is None:
            die("state.js ещё нет — начни с `ap.py init`")
        rest = pos[1:]
        if cmd not in ("", "sync", "commits", "ls-check"):
            # Время события ставится до команды: ей самой и ленте нужна одна метка.
            state["updatedAt"] = now()
            beat(state)
        if cmd in MOVES_ON:
            close_wait(state)
        if cmd == "stage":
            cmd_stage(state, rest, opt)
        elif cmd == "ticket":
            notes += cmd_ticket(state, rest, opt)
        elif cmd == "ls-check":
            notes += cmd_ls_check(state)
        elif cmd == "queue":
            notes += cmd_queue(state, rest, opt)
        elif cmd == "night":
            notes += cmd_night(state, rest, opt)
        elif cmd == "pacing":
            notes += cmd_pacing(state, rest, opt, multi)
        elif cmd == "e2e":
            notes += cmd_e2e(state, rest, multi)
        elif cmd == "tickets":
            notes.append(publish_tickets(state))
            log(state, "tickets", n=len(state.get("tickets") or []))
            if state.get("program") and state.get("tickets"):
                notes.append(program_set(state["program"], "in-flight", tickets=len(state["tickets"])))
        elif cmd == "check-plan":
            problems = check_plan(state)
            notes += ["! " + p for p in problems] or ["G3: трасса сходится"]
            set_gate(state, "G3", not problems, problems=len(problems))
        elif cmd == "set":
            cmd_set(state, rest)
            if any(p.startswith("tier=") for p in rest):
                log(state, "tier", v=state.get("tier"))
        elif cmd == "add":
            cmd_add(state, rest)
        elif cmd in ("coverage", "blind"):
            cmd_numbers(state, cmd, rest, multi)
        elif cmd == "tests":
            state["tests"] = tests_pair(rest[0] if rest else "")
            log(state, "tests", **state["tests"])
        elif cmd == "ask":
            cmd_ask(state, rest, opt)
        elif cmd == "answered":
            close_wait(state)
        elif cmd == "finish":
            notes = cmd_finish(state, opt)
        elif cmd == "reopen":
            cmd_reopen(state)
        elif cmd == "commits":
            notes = cmd_commits(state)
        elif cmd not in ("", "sync"):
            die("неизвестная команда %s — список в начале ap.py" % cmd)
    recount(state)
    notes = close_passed(state) + notes
    save(state)
    write_board(state)
    snap = write_snapshot(state)
    if state.get("program") and cmd in ("init", "tickets", "ticket", "stage", "tests", "finish", "reopen"):
        notes += project_refresh()
    if cmd == "finish" or opt.get("stop"):
        srv = stop_later()
    elif opt.get("no-serve"):
        srv = "сервер не проверялся"
    else:
        srv = serve(state)
    r = state.get("requirements") or {}
    print("%s · %s · требований %s, готово %s" % (snap, srv, r.get("total", 0), r.get("done", 0)))
    for line in notes:
        print("  " + (line if line.startswith("!") else "· " + line))
    for line in audit(state)[:5]:
        print("  ! " + line)
    if opt.get("check-update"):
        note = check_update(state)
        if note:
            print("  ↑ " + note)


if __name__ == "__main__":
    main()
