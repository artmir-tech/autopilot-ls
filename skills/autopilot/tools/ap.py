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
import socket
import subprocess
import sys
import time
import urllib.error
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
ORDER = ["preflight", "manifest", "briefing", "spec", "plan", "build", "review", "final"]
# Этап, чей результат лежит на диске, пройден — даже если его забыли отметить.
ARTIFACT = {"manifest": "manifest.md", "spec": "spec.md", "plan": "tickets/*.md"}
TICKET_STATUSES = {"start": "in-progress", "review": "review", "repair": "repair",
                   "done": "done", "fail": "failed", "retry": "in-progress", "reset": "pending"}
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
            + ls_wave_problems(tickets) + ls_night_row_problems(state, tickets))


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
        if (by.get(b) or {}).get("status") != "done" and b not in queued:
            return "ждёт %s" % b
    return None


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
    return round(SHARE * (100 - (p.get("window_used_pct") or 0) - p.get("reserve_pct", 15)))


def resume_at(p):
    try:
        t = dt.datetime.fromisoformat(p.get("window_reset_at") or "")
    except ValueError:
        return None
    return (t + dt.timedelta(minutes=5)).isoformat(timespec="seconds")


def pacing_verdict(state, p):
    used = p.get("window_used_pct") or 0
    if used >= WINDOW_STOP:
        out = ["стоп: окно %s %% — новых запусков нет; летящие довести до посадки, синк, продолжить в %s"
               % (used, resume_at(p) or "сброс окна + 5 мин")]
    else:
        out = ["окно %s %% · в полёте не больше %d · место под таск %d %%"
               % (used, 2 if used > WINDOW_TWO else 3, pacing_room(p))]
    n = state.get("night") or {}
    if n.get("status") != "running":
        return out
    spent = (p.get("weekly_used_pct") or 0) - (n.get("weekly_at_start") or 0)
    cap = p.get("night_weekly_max_pct", 15)
    if n.get("weekly_at_start") is not None and spent >= cap:
        n.update(status="stopped", stop="неделя +%s %% из %s %%" % (spent, cap))
        out.append("стоп ночи: неделя +%s %% из %s %%" % (spent, cap))
    elif used >= WINDOW_STOP:
        n.update(status="paused", resume_at=resume_at(p))
    return out


def cmd_pacing(state, pos, opt, multi):
    """Окно лимитов из get_usage (или measure-run.py) — в state.js.pacing; вердикт — сколько
    в полёт и влезает ли таск. Решает арифметика, а не настроение длинного прогона."""
    p = state.setdefault("pacing", {})
    p.setdefault("reserve_pct", 15)
    for flag, key in PACING_KEYS.items():
        if opt.get(flag) not in (None, True):
            p[key] = num(opt[flag])
    for flag, key in (("reset", "window_reset_at"), ("source", "source")):
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
PROGRAM_ROW = re.compile(r"^\|\s*P\d+\s*\|")


def program_lines():
    try:
        return open(PROGRAM, encoding="utf-8").read().splitlines()
    except OSError:
        return None


def program_rows(lines):
    rows = []
    for i, line in enumerate(lines):
        if PROGRAM_ROW.match(line):
            c = [x.strip() for x in cells_of(line)] + [""] * 6
            rows.append({"i": i, "id": c[0], "title": c[1], "deps": re.findall(r"P\d+", c[2]),
                         "status": c[3], "dir": c[4].strip("`"), "result": c[5]})
    return rows


def program_set(pid, status, d=None, result=None):
    """Строка программы меняется только здесь: статус, папка прогона, итог."""
    lines = program_lines()
    if lines is None:
        return "! программы нет — .autopilot/program.md"
    hit = [r for r in program_rows(lines) if r["id"] == pid]
    if not hit:
        return "! в программе нет %s" % pid
    r = hit[0]
    lines[r["i"]] = "| %s | %s | %s | %s | %s | %s |" % (
        r["id"], r["title"], ", ".join(r["deps"]) or "—", status,
        "`%s`" % d if d else (("`%s`" % r["dir"]) if r["dir"] not in ("", "—") else "—"),
        result or r["result"] or "—")
    with open(PROGRAM, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return "программа: %s → %s" % (pid, status)


def cmd_program(pos, opt):
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


IN_FLIGHT = ("in-progress", "repair")


def ls_pacing_guard(state, act, ids):
    """Окно ≥85 % — запусков нет; иначе в полёте не больше, чем окно позволяет (3 или 2).
    Цифры устарели — сначала get_usage и `pacing`, а не обход отказа."""
    p = state.get("pacing") or {}
    used = p.get("window_used_pct")
    if used is None or act not in ("start", "retry"):
        return
    if used >= WINDOW_STOP:
        die("окно %s %% — новых запусков нет: летящие довести, продолжить после сброса. "
            "Окно уже сброшено — свежие цифры: get_usage → `pacing --window …`" % used)
    cap = 2 if used > WINDOW_TWO else 3
    flying = {t["id"] for t in state.get("tickets") or [] if t.get("status") in IN_FLIGHT}
    total = len(flying | set(ids))
    if act == "start" and total > cap:
        die("в полёте было бы %d, окно %s %% позволяет %d — запусти меньше" % (total, used, cap))


def ls_night_record(state, act, ids):
    n = state.get("night") or {}
    if n.get("status") != "running" or act not in ("done", "fail"):
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


def cmd_ls_check(state):
    """Что форку нужно в репозитории проекта: стандарт кода, игнор worktree, make gates."""
    out = []
    if not os.path.isfile(os.path.join(ROOT, "docs", "standards", "ub-mode.md")):
        out.append("! нет docs/standards/ub-mode.md — скопируй из %s/standards/ub-mode.md"
                   % (state.get("skillDir") or "<skillDir>"))
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
        notes.append(program_set(opt["program"], "in-flight", d=state["dir"]))
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
        refresh_g1(state, create=True)
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
        die("ticket <id…> start|review|repair|done|fail|retry|reset")
    act = acts[0]
    known = {t["id"]: t for t in state.get("tickets") or []}
    by_user = opt.get("by-user") if isinstance(opt.get("by-user"), str) else None
    t = now()
    ls_night_guard(state, act, ids)
    ls_pacing_guard(state, act, ids)
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
    state["result"] = opt.get("result") if isinstance(opt.get("result"), str) else None
    register_row(state, "сдан с оговорками" if problems else "сдан", state["result"])
    log(state, "finish", result=state["result"], problems=len(problems))
    if state.get("program"):
        notes.append(program_set(state["program"], "landed", d=state["dir"], result=state["result"]))
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
    if cmd == "program":                 # программа живёт между прогонами: state.js ей не нужен
        for line in cmd_program(pos[1:], opt):
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
