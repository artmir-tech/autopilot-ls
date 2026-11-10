"""Тесты skills/autopilot/tools/ap.py — учёта прогона Autopilot.

Запуск из корня репозитория:  python3 -m unittest discover -s tests
Каждый тест поднимает временный git-репозиторий с .autopilot/ и зовёт ap.py
как оркестратор — отдельным процессом, без сервера (--no-serve).
"""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(os.path.dirname(HERE), "skills", "autopilot")
AP = os.path.join(SKILL, "tools", "ap.py")
TEMPLATE = os.path.join(SKILL, "phases", "dashboard-template.html")

MANIFEST = """# Манифест требований

| ID | Из брифа (дословно) | Статус | Основание | Где |
|----|---------------------|--------|-----------|-----|
| R01 | «принимает заявки» | in-spec | — | spec §2 |
| R02 | «складывает в таблицу» | in-spec | — | spec §4 |
| R03 | «SMS» | dropped | «не надо» | — |
| R05 | «цвета студии» | in-spec | — | spec §6 |
"""


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def ticket(tid, title, reqs, deps, zone, wave, review="нет", model="sonnet",
           kind="code", effort="medium", attention="none", night="нет"):
    """Шаблон таска форка autopilot-ls: поля Тип, Модель, Усилие, Внимание, Ночью обязательны.
    Поле со значением None в файл не пишется — так проверяется отказ check-plan."""
    extra = "".join("**%s:** %s\n" % (k, v) for k, v in (
        ("Тип", kind), ("Модель", model), ("Усилие", effort), ("Внимание", attention), ("Ночью", night))
        if v is not None)
    return ("# %s — %s\n\n**Требования:** %s\n**Зависит от:** %s\n**Зона:** %s\n"
            "**Волна:** %s\n**Ревью:** %s\n%s\n## Критерии приёмки\n\n- [ ] что-то\n"
            % (tid, title, reqs, deps, " · ".join("`%s`" % z for z in zone), wave, review, extra))


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="ap-test-")
        self.git("init", "-q")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init")
        self.a = os.path.join(self.root, ".autopilot")
        os.makedirs(self.a)
        shutil.copy(TEMPLATE, os.path.join(self.a, "dashboard.html"))
        shutil.copy(AP, os.path.join(self.a, "ap.py"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def git(self, *args):
        return subprocess.run(["git", "-C", self.root] + list(args), capture_output=True, text=True)

    def ap(self, *args):
        env = dict(os.environ, AUTOPILOT_NO_UPDATE_CHECK="1")
        r = subprocess.run([sys.executable, os.path.join(self.a, "ap.py")] + list(args) + ["--no-serve"],
                           capture_output=True, text=True, env=env, cwd=self.root)
        return r.returncode, r.stdout

    def state(self):
        raw = read(os.path.join(self.a, "state.js"))
        return json.loads(raw.split("=", 1)[1])

    def stage(self, sid):
        return next(s for s in self.state()["stages"] if s["id"] == sid)

    def init(self):
        code, out = self.ap("init", "--slug", "repair-bot", "--title", "Бот", "--skill-dir", SKILL)
        self.assertEqual(code, 0, out)
        self.dir = os.path.join(self.a, self.state()["dir"])
        return out

    def write(self, rel, text):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def manifest(self):
        return read(os.path.join(self.dir, "manifest.md"))

    # ── init ───────────────────────────────────────────────────────────────

class Run(Base):
    def test_init_creates_run(self):
        self.init()
        s = self.state()
        self.assertTrue(re.match(r"\d{4}-\d{2}-\d{2}-repair-bot--wip$", s["dir"]))
        self.assertTrue(os.path.isdir(os.path.join(self.dir, "tickets")))
        self.assertEqual([x["status"] for x in s["stages"]], ["active"] + ["pending"] * 9)
        self.assertRegex(s["startedAt"], r"T\d\d:\d\d:\d\d[+-]\d\d:\d\d$")
        self.assertIn("в работе", read(os.path.join(self.a, "README.md")))
        self.assertIn(".autopilot/serve.*", read(os.path.join(self.root, ".gitignore")))
        self.assertIn("window.STATE={", read(os.path.join(self.a, "dashboard.html")))

    def test_init_refuses_on_live_run(self):
        self.init()
        code, out = self.ap("init", "--slug", "other")
        self.assertNotEqual(code, 0)
        self.assertIn("продолжение", out)

    def test_init_archives_finished_run(self):
        self.init()
        first = self.state()["dir"]
        self.ap("finish", "--result", "готово", "--by-user", "«сдавай»")
        code, out = self.ap("init", "--slug", "second")
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.exists(os.path.join(self.a, first.replace("--wip", ""), "state.js")))
        self.assertTrue(self.state()["dir"].endswith("second--wip"))

    # ── stages ─────────────────────────────────────────────────────────────
    def test_opening_a_stage_closes_the_previous(self):
        self.init()
        self.ap("stage", "manifest")
        self.assertEqual(self.stage("preflight")["status"], "done")
        self.assertEqual(self.stage("manifest")["status"], "active")

    def test_review_closes_build(self):
        self.init()
        self.ap("stage", "build")
        self.ap("stage", "review")
        self.assertEqual(self.stage("build")["status"], "done")

    def test_passed_stage_with_artifact_is_marked_done(self):
        self.init()
        self.write("manifest.md", MANIFEST)
        self.ap("stage", "architecture", "skip", "--note", "маленькая сборка")
        code, out = self.ap("stage", "spec")
        self.assertEqual(self.stage("manifest")["status"], "done")
        self.assertIn("briefing", out)                     # ни файла, ни отметки — подсказка
        self.assertEqual(self.stage("briefing")["status"], "pending")

    def test_skip_needs_a_reason(self):
        self.init()
        code, _ = self.ap("stage", "briefing", "skip")
        self.assertNotEqual(code, 0)
        self.ap("stage", "briefing", "skip", "--note", "полный автомат — самобрифинг")
        self.assertEqual(self.stage("briefing")["status"], "skipped")

    # ── tickets and the manifest ───────────────────────────────────────────
    def plan(self):
        self.init()
        self.write("manifest.md", MANIFEST)
        self.write("tickets/01-karkas.md", ticket("01", "Каркас", "R01, R05", "—", ["src/core/"], 1, "да — фундамент", "opus",
                                                         effort="high"))
        self.write("tickets/02-priem.md", ticket("02", "Приём", "R01.1, R02, A01", "01", ["src/bot/"], 2))

    def test_tickets_publish_and_move_rows_in_ticket(self):
        self.plan()
        code, out = self.ap("tickets")
        t = {x["id"]: x for x in self.state()["tickets"]}
        self.assertEqual(t["02"]["requirements"], ["R01.1", "R02", "A01"])
        self.assertEqual(t["02"]["blockedBy"], ["01"])
        self.assertEqual(t["01"]["zone"], ["src/core/"])
        self.assertEqual(t["01"]["review"], "да — фундамент")
        self.assertEqual(t["02"]["status"], "pending")
        m = self.manifest()
        self.assertRegex(m, r"\| R01 \|[^\n]*\| in-ticket \|[^\n]*T01, T02")
        self.assertRegex(m, r"\| R03 \|[^\n]*\| dropped \|")
        self.assertEqual(self.state()["requirements"]["inTicket"], 3)

    def test_check_plan_passes_a_sound_plan(self):
        self.plan()
        code, out = self.ap("check-plan")
        self.assertIn("G3: трасса сходится", out)

    def test_check_plan_catches_defects(self):
        self.plan()
        self.write("tickets/03-tablica.md", ticket("03", "Таблица", "R02", "02", ["src/bot/sheets/"], 2))
        self.write("tickets/04-nichei.md", ticket("04", "Ничей", "", "—", [], 1))
        code, out = self.ap("check-plan")
        self.assertIn("в волне 2, но его зависимости позволяют не раньше 3", out)
        self.assertIn("таски 02 и 03 в одной волне пишут в src/bot/sheets/", out)
        self.assertIn("таск 04 ни к чему не привязан", out)
        self.assertIn("у таска 04 нет зоны", out)

    def test_check_plan_catches_a_requirement_in_no_ticket(self):
        self.plan()
        self.write("manifest.md", MANIFEST + "| G01 | «отмена» | in-spec | — | spec §5 |\n")
        code, out = self.ap("check-plan")
        self.assertIn("требование G01", out)

    def test_done_closes_rows_only_when_all_their_tickets_are_done(self):
        self.plan()
        self.ap("tickets")
        self.ap("ticket", "01", "start")
        self.ap("ticket", "01", "done", "--tests", "3/0", "--commit", "1111111aaaa", "--placeholder", "R05")
        m = self.manifest()
        self.assertRegex(m, r"\| R01 \|[^\n]*\| in-ticket \|")     # ещё и в таске 02
        self.assertRegex(m, r"\| R05 \|[^\n]*\| placeholder \|[^\n]*1111111")
        self.ap("ticket", "02", "start")
        self.ap("ticket", "02", "done", "--tests", "5/0", "--commit", "2222222bbbb")
        m = self.manifest()
        self.assertRegex(m, r"\| R01 \|[^\n]*\| done \|")
        self.assertRegex(m, r"\| R02 \|[^\n]*\| done \|")
        s = self.state()
        self.assertEqual(s["requirements"]["done"], 2)
        self.assertEqual(s["requirements"]["placeholder"], 1)
        self.assertEqual(s["tests"], {"passed": 5, "failed": 0})

    def test_ticket_lifecycle_counters(self):
        self.plan()
        self.ap("tickets")
        self.ap("ticket", "01", "02", "start")
        self.ap("ticket", "01", "review")
        self.ap("ticket", "01", "repair", "--note", "ключ схемы — R01")
        self.ap("ticket", "02", "retry")
        t = {x["id"]: x for x in self.state()["tickets"]}
        self.assertEqual(t["01"]["status"], "repair")
        self.assertEqual(t["01"]["repairs"], 1)
        self.assertEqual(t["01"]["repairFindings"], ["ключ схемы — R01"])
        self.assertEqual(t["02"]["retries"], 1)
        self.assertTrue(t["02"]["startedAt"])
        self.ap("ticket", "02", "reset")
        t = {x["id"]: x for x in self.state()["tickets"]}
        self.assertEqual(t["02"]["status"], "pending")
        self.assertNotIn("startedAt", t["02"])

    def test_repairs_and_retries_stop_at_two(self):
        self.plan()
        self.ap("tickets")
        self.ap("ticket", "01", "02", "start")
        for _ in range(2):
            self.assertEqual(self.ap("ticket", "01", "repair", "--note", "тест красный")[0], 0)
            self.assertEqual(self.ap("ticket", "02", "retry")[0], 0)
        before = self.state()["rev"]
        code, out = self.ap("ticket", "01", "repair", "--note", "ещё раз")
        self.assertNotEqual(code, 0)
        self.assertIn("два дозапроса", out)
        code, out = self.ap("ticket", "02", "retry")
        self.assertNotEqual(code, 0)
        self.assertIn("третьего нет", out)
        t = {x["id"]: x for x in self.state()["tickets"]}
        self.assertEqual((t["01"]["repairs"], t["02"]["retries"]), (2, 2))
        self.assertEqual(self.state()["rev"], before)          # отказ ничего не пишет

    def test_a_failed_ticket_restarts_only_by_the_users_words(self):
        self.plan()
        self.ap("tickets")
        self.ap("ticket", "01", "02", "start")
        self.ap("ticket", "02", "retry")
        self.ap("ticket", "02", "fail", "--note", "native-модуль не грузится")
        for act in ("start", "retry", "repair", "review", "done", "reset"):
            code, out = self.ap("ticket", "02", act)
            self.assertNotEqual(code, 0, act)
            self.assertIn("решает пользователь", out)
        code, _ = self.ap("ticket", "01", "02", "start")       # волна с упавшим — целиком отказ
        self.assertNotEqual(code, 0)
        self.assertEqual({x["id"]: x["status"] for x in self.state()["tickets"]}["02"], "failed")
        code, out = self.ap("ticket", "02", "reset", "--by-user", "«ключ добавил, давай ещё раз»")
        self.assertEqual(code, 0, out)
        t = {x["id"]: x for x in self.state()["tickets"]}["02"]
        self.assertEqual((t["status"], t["retries"]), ("pending", 0))
        self.assertEqual(t["reopenedByUser"], ["«ключ добавил, давай ещё раз»"])

    def test_blind_acceptance_runs_at_most_twice(self):
        self.init()
        self.assertEqual(self.ap("blind", "checked=4", "matched=3", "--mismatch", "R02 — не видно")[0], 0)
        self.assertEqual(self.ap("blind", "checked=4", "matched=3", "--mismatch", "R02 — всё ещё")[0], 0)
        code, out = self.ap("blind", "checked=4", "matched=4")
        self.assertNotEqual(code, 0)
        self.assertIn("третьего круга нет", out)
        self.assertEqual(self.state()["blind"]["mismatches"], ["R02 — всё ещё"])
        self.ap("finish", "--result", "готово", "--by-user", "«сдавай»")
        self.ap("reopen")                                       # новый бриф — новая приёмка
        self.assertEqual(self.ap("blind", "checked=4", "matched=4")[0], 0)

    def test_unknown_ticket_is_an_error(self):
        self.plan()
        self.ap("tickets")
        code, out = self.ap("ticket", "09", "start")
        self.assertNotEqual(code, 0)

    def test_escaped_pipe_in_a_quote(self):
        self.init()
        self.write("manifest.md", MANIFEST.replace("«складывает в таблицу»", "«таблица \\| или база»"))
        self.write("tickets/01-a.md", ticket("01", "A", "R01, R02, R05", "—", ["a/"], 1))
        self.ap("tickets")
        self.assertRegex(self.manifest(), r"\| R02 \| «таблица \\\| или база» \| in-ticket \|")

    def test_d_rows_are_constraints_not_requirements(self):
        self.plan()
        self.write("manifest.md", MANIFEST + "| D01 | схема не держит два адреса | in-spec | таск 02 | spec §3 |\n")
        code, out = self.ap("check-plan")
        self.assertNotIn("D01", out)
        self.assertEqual(self.state()["requirements"]["total"], 4)

    def test_dependencies_accept_a_t_prefix(self):
        self.plan()
        self.write("tickets/03-c.md", ticket("03", "C", "R02", "T1, T02", ["c/"], 3))
        self.ap("tickets")
        t = {x["id"]: x for x in self.state()["tickets"]}
        self.assertEqual(t["03"]["blockedBy"], ["01", "02"])

    def test_a_lettered_dependency_is_not_turned_into_a_number(self):
        # E35 зависит от E34 из той же волны; таск 34 из первой волны тут ни при чём.
        self.plan()
        self.write("tickets/34-a.md", ticket("34", "A", "R02", "—", ["a/"], 1))
        self.write("tickets/E34-b.md", ticket("E34", "B", "R02", "—", ["b/"], 2))
        self.write("tickets/E35-c.md", ticket("E35", "C", "R02", "E34", ["c/"], 2))
        self.write("tickets/E36-d.md", ticket("E36", "D", "R02", "X7", ["d/"], 3))
        code, out = self.ap("check-plan")
        t = {x["id"]: x for x in self.state()["tickets"]}
        self.assertEqual(t["E35"]["blockedBy"], ["E34"])
        self.assertIn("таск E35 в волне 2, но его зависимости позволяют не раньше 3", out)
        self.assertIn("таск E36 зависит от несуществующего X7", out)
        self.assertFalse(self.state()["gates"]["G3"]["ok"])

    def test_empty_tickets_dir_does_not_pass_the_plan(self):
        self.init()
        self.write("manifest.md", MANIFEST)
        self.ap("stage", "build")
        self.assertEqual(self.stage("plan")["status"], "pending")
        self.write("tickets/01-a.md", ticket("01", "A", "R01", "—", ["a/"], 1))
        self.ap()
        self.assertEqual(self.stage("plan")["status"], "done")

    # ── lists and numbers ──────────────────────────────────────────────────
    def test_add_set_and_numbers(self):
        self.init()
        self.ap("add", "concerns", "src/x.ts:4 — два формата даты")
        self.ap("add", "debt.emptyEnv", "TELEGRAM_BOT_TOKEN")
        self.ap("add", "debt.emptyEnv", "TELEGRAM_BOT_TOKEN")      # без дублей
        self.ap("set", "tier=T2", "baseCommit=abc1234")
        self.ap("coverage", "found=2", "fixed=1", "deferred=1", "--item", "R07 — отложено")
        self.ap("add", "report", "два формата даты", "лишний отступ")
        self.ap("blind", "checked=4", "matched=3", "--mismatch", "R02 — не видно")
        s = self.state()
        self.assertEqual(s["concerns"], ["src/x.ts:4 — два формата даты"])
        self.assertEqual(s["debt"]["emptyEnv"], ["TELEGRAM_BOT_TOKEN"])
        self.assertEqual((s["tier"], s["baseCommit"]), ("T2", "abc1234"))
        self.assertEqual(s["coverage"], {"found": 2, "fixed": 1, "deferred": 1, "items": ["R07 — отложено"]})
        self.assertEqual(s["report"], ["два формата даты", "лишний отступ"])
        self.assertEqual(s["blind"], {"checked": 4, "matched": 3, "mismatches": ["R02 — не видно"]})

    def test_every_event_leaves_a_beat(self):
        # updatedAt перезаписывается; журнал хранит каждое событие, чтобы рабочее
        # время считалось и тогда, когда дашборд их не видел (сон, мёртвый сервер)
        self.init()
        first = self.state()["beats"]
        self.assertEqual(first, [self.state()["startedAt"]])
        self.ap("add", "report", "раз")
        self.ap()                                   # синхронизация — не событие
        s = self.state()
        self.assertEqual(s["beats"][-1], s["updatedAt"])
        self.assertLessEqual(len(s["beats"]), 2)
        self.assertEqual(s["beats"], sorted(set(s["beats"])))

    # ── what the dashboard reads ───────────────────────────────────────────
    def test_waiting_for_the_user_is_kept_apart_from_work(self):
        # Ожидание ответа — не работа сборки: дашборд вычитает waits из часов
        self.init()
        self.ap("stage", "briefing")
        self.ap("ask", "briefing", "--note", "три вопроса")
        s = self.state()
        self.assertEqual((s["waiting"]["kind"], s["waiting"]["note"]), ("briefing", "три вопроса"))
        self.assertEqual(s["waiting"]["since"], s["updatedAt"])
        self.ap("answered")
        s = self.state()
        self.assertIsNone(s["waiting"])
        self.assertEqual(len(s["waits"]), 1)
        self.assertEqual(s["waits"][0]["kind"], "briefing")
        self.assertLessEqual(s["waits"][0]["from"], s["waits"][0]["to"])

    def test_moving_on_closes_a_forgotten_wait(self):
        self.init()
        self.ap("ask", "spec")
        self.ap("add", "report", "раз")                    # учёт — не ответ пользователя
        self.assertIsNotNone(self.state()["waiting"])
        self.ap("stage", "plan")
        s = self.state()
        self.assertIsNone(s["waiting"])
        self.assertEqual([w["kind"] for w in s["waits"]], ["spec"])

    def test_ask_needs_a_known_kind(self):
        self.init()
        code, _ = self.ap("ask", "whatever")
        self.assertNotEqual(code, 0)

    def test_log_records_events_not_syncs(self):
        self.plan()
        self.ap("tickets")
        self.ap("ticket", "01", "start")
        self.ap("ticket", "01", "repair", "--note", "пустой адрес")
        self.ap("ticket", "01", "done", "--tests", "7/0", "--commit", "abc")
        self.ap()
        kinds = [(e["k"], e.get("act")) for e in self.state()["log"]]
        self.assertEqual(kinds, [("init", None), ("tickets", None), ("ticket", "start"),
                                 ("ticket", "repair"), ("ticket", "done")])
        last = self.state()["log"][-1]
        self.assertEqual((last["ids"], last["tests"]), (["01"], {"passed": 7, "failed": 0}))
        self.assertEqual(self.state()["log"][3]["note"], "пустой адрес")

    def test_gates_follow_the_events_that_decide_them(self):
        self.plan()
        self.write("manifest.md", MANIFEST.replace("| R02 | «складывает в таблицу» | in-spec",
                                                   "| R02 | «складывает в таблицу» | open"))
        self.ap("stage", "architecture", "skip", "--note", "маленькая сборка")
        self.ap("stage", "spec")
        g = self.state()["gates"]["G1"]
        self.assertEqual((g["ok"], g["open"], g["total"]), (False, 1, 4))
        self.write("manifest.md", MANIFEST)
        self.ap("stage", "architecture", "skip", "--note", "маленькая сборка")
        self.ap("stage", "spec", "done")
        self.assertTrue(self.state()["gates"]["G1"]["ok"])
        self.write("manifest.md", MANIFEST.replace("| R02 | «складывает в таблицу» | in-spec",
                                                   "| R02 | «складывает в таблицу» | open"))
        self.ap("sync")                                     # манифест правят и после спецификации
        g = self.state()["gates"]["G1"]
        self.assertEqual((g["ok"], g["open"]), (False, 1))
        self.write("manifest.md", MANIFEST)
        self.ap("sync")
        self.assertTrue(self.state()["gates"]["G1"]["ok"])
        self.ap("coverage", "found=2", "fixed=1", "deferred=1")
        self.ap("check-plan")
        self.ap("blind", "checked=4", "matched=3", "--mismatch", "R02 — не видно")
        g = self.state()["gates"]
        self.assertTrue(g["G2"]["ok"])
        self.assertTrue(g["G3"]["ok"])
        self.assertEqual((g["G4"]["ok"], g["G4"]["matched"], g["G4"]["checked"]), (False, 3, 4))

    def test_gate_numbers_are_required(self):
        self.init()
        self.ap("coverage", "found=2", "fixed=1", "deferred=0")
        self.ap("blind", "checked=4", "matched=3", "--mismatch", "R02 — не видно")
        before = read(os.path.join(self.a, "state.js"))
        for args in (["coverage"], ["coverage", "fixed=1"], ["coverage", "found=1", "fixed=1"],
                     ["coverage", "found=two", "fixed=1", "deferred=1"], ["coverage", "found=1", "fixed=1", "deferred=0", "extra=1"],
                     ["blind"], ["blind", "checked=4"], ["blind", "checked=3", "matched=4"]):
            code, out = self.ap(*args)
            self.assertNotEqual(code, 0, args)
            self.assertIn("ошибка", out, args)
        self.assertEqual(read(os.path.join(self.a, "state.js")), before)
        g = self.state()["gates"]
        self.assertFalse(g["G2"]["ok"])
        self.assertFalse(g["G4"]["ok"])
        self.assertEqual(self.state()["blind"]["mismatches"], ["R02 — не видно"])

    def test_help_touches_nothing(self):
        code, out = self.ap("--help")
        self.assertEqual(code, 0)
        self.assertIn("Учёт прогона Autopilot", out)
        self.assertFalse(os.path.exists(os.path.join(self.a, "state.js")))
        self.init()
        self.ap("coverage", "found=2", "fixed=1", "deferred=0")
        before = read(os.path.join(self.a, "state.js"))
        for args in (["--help"], ["-h"], ["help"], ["coverage", "--help"], ["blind", "-h"], ["stage", "final", "--help"]):
            code, out = self.ap(*args)
            self.assertEqual(code, 0, args)
            self.assertIn("ap.py coverage found=", out, args)
        self.assertEqual(read(os.path.join(self.a, "state.js")), before)
        self.assertFalse(self.state()["gates"]["G2"]["ok"])

    def test_requirements_carry_the_users_words(self):
        self.init()
        self.write("manifest.md", MANIFEST.replace("«цвета студии»", "*(подразумевается)* «таблица \\| база»")
                   + "| D01 | схема | in-spec | — | — |\n")
        self.ap()
        req = {r["id"]: r for r in self.state()["reqList"]}
        self.assertEqual(sorted(req), ["R01", "R02", "R03", "R05"])     # D## — не требование
        self.assertEqual(req["R01"], {"id": "R01", "text": "«принимает заявки»", "status": "in-spec"})
        self.assertEqual(req["R03"]["why"], "«не надо»")
        self.assertEqual(req["R05"]["text"], "(подразумевается) «таблица | база»")

    def test_every_write_bumps_rev(self):
        # Дашборд перерисовывается по rev: синхронизация тоже меняет то, что он показывает
        self.init()
        r = self.state()["rev"]
        self.ap()
        self.assertEqual(self.state()["rev"], r + 1)

    # ── finish ─────────────────────────────────────────────────────────────
    def ready(self):
        """Прогон, которому нечего скрывать: гейты зелёные, таски сданы настоящими коммитами."""
        self.plan()
        self.ap("tickets")
        self.ap("stage", "architecture", "skip", "--note", "маленькая сборка")
        self.ap("stage", "spec", "done")
        self.ap("check-plan")
        self.ap("coverage", "found=0", "fixed=0", "deferred=0")
        self.git("add", "-A")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "run")
        sha = self.git("rev-parse", "--short", "HEAD").stdout.strip()
        self.ap("ticket", "01", "02", "start")
        self.ap("ticket", "01", "02", "done", "--commit", sha)
        self.git("add", "-A")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "books")

    def test_finish_lands_the_run(self):
        self.ready()
        self.ap("blind", "checked=4", "matched=4")
        code, out = self.ap("finish", "--result", "Бот принимает заявки")
        self.assertEqual(code, 0, out)
        s = self.state()
        self.assertTrue(s["finishedAt"])
        self.assertFalse(s["dir"].endswith("--wip"))
        self.assertTrue(os.path.isdir(os.path.join(self.a, s["dir"])))
        self.assertTrue(all(x["status"] in ("done", "skipped") for x in s["stages"]))
        self.assertIn("| сдан | Бот принимает заявки |", read(os.path.join(self.a, "README.md")))
        self.assertEqual(s["result"], "Бот принимает заявки")
        self.assertNotIn("landedWith", s)
        self.assertIn("R", self.git("status", "--short").stdout)    # переименование через git mv

    def assertRefused(self, *needles):
        code, out = self.ap("finish", "--result", "готово")
        self.assertNotEqual(code, 0, out)
        for n in needles:
            self.assertIn(n, out)
        s = self.state()
        self.assertIsNone(s["finishedAt"])
        self.assertTrue(s["dir"].endswith("--wip"))

    def test_finish_refuses_an_open_requirement(self):
        self.ready()
        self.ap("blind", "checked=4", "matched=4")
        self.write("manifest.md", self.manifest().replace("| R05 | «цвета студии» | done", "| R05 | «цвета студии» | open"))
        self.assertRefused("G1")

    def test_finish_refuses_a_check_that_never_ran(self):
        self.ready()
        self.assertRefused("G4")

    def test_finish_refuses_an_unfinished_ticket(self):
        self.ready()
        self.ap("blind", "checked=4", "matched=4")
        self.ap("ticket", "02", "reset")
        self.assertRefused("таск 02")

    def test_finish_refuses_a_commit_that_is_not_in_history(self):
        self.ready()
        self.ap("blind", "checked=4", "matched=4")
        self.ap("ticket", "02", "done", "--commit", "abc1234")
        self.assertRefused("таск 02", "abc1234")

    def test_finish_refuses_a_drift_while_a_second_look_is_left(self):
        self.ready()
        self.ap("blind", "checked=4", "matched=3", "--mismatch", "R02 — нет таблицы")
        self.assertRefused("G4")

    def test_a_drift_after_both_looks_lands_with_a_caveat(self):
        self.ready()
        self.ap("blind", "checked=4", "matched=3", "--mismatch", "R02 — нет таблицы")
        self.ap("blind", "checked=1", "matched=0", "--mismatch", "R02 — нет таблицы")
        code, out = self.ap("finish", "--result", "готово")
        self.assertEqual(code, 0, out)
        s = self.state()
        self.assertTrue(s["finishedAt"])
        self.assertIn("G4", s["landedWith"]["problems"][0])
        self.assertNotIn("byUser", s["landedWith"])
        self.assertIn("| сдан с оговорками | готово |", read(os.path.join(self.a, "README.md")))

    def test_finish_by_user_lands_and_keeps_what_was_wrong(self):
        self.ready()
        code, out = self.ap("finish", "--result", "готово", "--by-user", "«сдавай как есть»")
        self.assertEqual(code, 0, out)
        s = self.state()
        self.assertTrue(s["finishedAt"])
        self.assertEqual(s["landedWith"]["byUser"], "«сдавай как есть»")
        self.assertIn("G4", s["landedWith"]["problems"][0])
        self.ap("reopen")
        self.assertNotIn("landedWith", self.state())

    def test_reopen_puts_wip_back(self):
        self.init()
        self.ap("finish", "--result", "готово", "--by-user", "«сдавай»")
        self.ap("reopen")
        s = self.state()
        self.assertTrue(s["dir"].endswith("--wip"))
        self.assertIsNone(s["finishedAt"])
        self.assertEqual(self.stage("manifest")["status"], "active")
        self.assertEqual(self.stage("final")["status"], "pending")
        self.assertNotIn("finishedAt", self.stage("final"))

    def test_done_needs_a_commit(self):
        self.plan()
        self.ap("tickets")
        self.ap("ticket", "01", "start")
        code, out = self.ap("ticket", "01", "done", "--tests", "3/0")
        self.assertNotEqual(code, 0)
        self.assertIn("нет --commit", out)
        self.assertEqual(self.state()["tickets"][0]["status"], "in-progress")
        self.ap("ticket", "01", "done", "--commit", "abc1234")
        self.ap("ticket", "01", "review")
        self.assertEqual(self.ap("ticket", "01", "done")[0], 0)   # после ревью коммит уже есть

    def test_commits_flags_a_done_ticket_whose_commit_left_history(self):
        self.plan()
        self.ap("tickets")
        commit = lambda m: self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", m)
        commit("T01")
        kept = self.git("rev-parse", "--short", "HEAD").stdout.strip()
        commit("T02")
        lost = self.git("rev-parse", "--short", "HEAD").stdout.strip()
        self.ap("ticket", "01", "done", "--commit", kept)
        self.ap("ticket", "02", "done", "--commit", lost)
        events = len(self.state()["log"])
        code, out = self.ap("commits")
        self.assertIn("коммиты сданных тасков на месте", out)
        self.git("reset", "-q", "--hard", kept)
        code, out = self.ap("commits")
        self.assertEqual(code, 0, out)
        self.assertIn("! таск 02: коммита %s нет в истории" % lost, out)
        self.assertNotIn("таск 01", out)
        self.assertEqual(self.state()["tickets"][1]["status"], "done")   # сбрасывает оркестратор
        self.assertEqual(len(self.state()["log"]), events)               # проверка — не событие

    # ── форк autopilot-ls: поля таска ──────────────────────────────────────
    def test_ls_ticket_fields_reach_the_state(self):
        self.plan()
        self.write("tickets/03-prompt.md", ticket("03", "Промпт коуча", "R02", "01", ["prompts/coach/"], 2,
                                                  model="opus", kind="prompt", effort="high",
                                                  attention="review", night="да"))
        self.ap("tickets")
        t = {x["id"]: x for x in self.state()["tickets"]}
        self.assertEqual((t["01"]["type"], t["01"]["model"], t["01"]["effort"]), ("code", "opus", "high"))
        self.assertEqual((t["03"]["type"], t["03"]["attention"], t["03"]["night_ok"]), ("prompt", "review", True))
        self.assertIs(t["02"]["night_ok"], False)

    def test_check_plan_refuses_missing_and_unknown_ls_fields(self):
        self.plan()
        self.write("tickets/03-x.md", ticket("03", "Икс", "R02", "02", ["src/x/"], 3, model="сильная", effort=None))
        code, out = self.ap("check-plan")
        self.assertIn("таск 03: Модель «сильная» — не из opus | sonnet | haiku", out)
        self.assertIn("у таска 03 нет поля Усилие", out)
        self.assertNotIn("G3: трасса сходится", out)

    def test_check_plan_refuses_night_for_an_owner_ticket(self):
        self.plan()
        self.write("tickets/03-m.md", ticket("03", "Методика", "R02", "02", ["src/m/"], 3,
                                             attention="owner", night="да"))
        code, out = self.ap("check-plan")
        self.assertIn("таск 03: «Ночью: да» при «Внимание: owner»", out)

    def test_check_plan_keeps_a_migration_alone_in_its_wave(self):
        self.plan()
        self.write("tickets/03-mig.md", ticket("03", "Миграция", "R02", "01", ["migrations/"], 2, kind="migration"))
        code, out = self.ap("check-plan")
        self.assertIn("таск 03 (migration) делит волну 2 с 02 — миграция летит одна", out)

    def shrunk(self, tid, line):
        self.write("tickets/%s-s.md" % tid, ticket(tid, "Поиск", "R02", "02", ["src/s/"], 3) + line + "\n")
        return self.ap("check-plan")[1]

    def test_a_ticket_is_not_reset_forever_without_the_owner(self):
        self.plan()
        self.ap("tickets")
        for _ in range(2):
            self.ap("ticket", "02", "start")
            code, out = self.ap("ticket", "02", "reset")
            self.assertEqual(code, 0, out)
        self.ap("ticket", "02", "start")
        code, out = self.ap("ticket", "02", "reset")
        self.assertNotEqual(code, 0)
        self.assertIn("два перезапуска без слов владельца", out)
        code, out = self.ap("ticket", "02", "reset", "--by-user", "«давай ещё раз»")
        self.assertEqual(code, 0, out)
        self.assertEqual(next(t for t in self.state()["tickets"] if t["id"] == "02")["resets"], 0)

    def test_check_plan_refuses_a_ticket_that_shrinks_the_task(self):
        self.plan()
        out = self.shrunk("03", "- [ ] В первой версии поиска нет")
        self.assertIn("таск 03: «в первой версии»", out)
        self.assertNotIn("G3: трасса сходится", out)

    def test_only_the_owners_words_let_a_ticket_shrink_the_task(self):
        self.plan()
        self.assertIn("таск 03: «упрощённ»", self.shrunk("03", "Упрощённо.\n**Урезание:** без цитаты"))
        out = self.shrunk("03", "Упрощённо.\n**Урезание:** «поиск сделаем потом»")
        self.assertIn("G3: трасса сходится", out)

    def test_a_repair_ticket_answers_to_the_same_rule(self):
        self.plan()
        out = self.shrunk("F1", "- [ ] Потом допилим отступы")
        self.assertIn("таск F1: «потом допилим»", out)

    def test_quotes_code_and_test_stubs_do_not_count_as_shrinking(self):
        self.plan()
        out = self.shrunk("03", "> «пока упрощённо»\n- [ ] Адрес `/api/v1/users` отвечает\n- [ ] Заглушка в тестах вместо сервиса")
        self.assertIn("G3: трасса сходится", out)

    def test_a_placeholder_row_may_have_its_stub(self):
        self.plan()
        self.write("manifest.md", self.manifest().replace("| R02 | «складывает в таблицу» | in-spec", "| R02 | «складывает в таблицу» | placeholder"))
        self.assertIn("placeholder", self.manifest())
        out = self.shrunk("03", "- [ ] Видимая заглушка вместо таблицы")
        self.assertNotIn("таск 03: «заглушк»", out)

    def test_check_plan_keeps_the_prompt_zone_for_prompt_tickets(self):
        self.plan()
        self.write("tickets/03-p.md", ticket("03", "Промпт", "R02", "01", ["prompts/coach/", "evals/coach/"], 2,
                                             model="opus", kind="prompt", effort="high"))
        self.write("tickets/04-c.md", ticket("04", "Код", "R02", "01", ["src/coach/", "prompts/shared/"], 2))
        self.write("tickets/05-p.md", ticket("05", "Промпт и код", "R02", "01", ["prompts/w/", "src/w/"], 2,
                                             model="opus", kind="prompt", effort="high"))
        code, out = self.ap("check-plan")
        self.assertIn("таск 04 (code) пишет в prompts/shared/ — зона промптов только у prompt-тасков", out)
        self.assertIn("таск 05 (prompt) пишет в src/w/ — prompt-таск правит только prompts/ и evals/", out)
        self.assertNotIn("таск 03 (", out)

    def test_attempts_record_the_rung_and_retries_climb_the_ladder(self):
        self.plan()
        self.write("tickets/02-priem.md", ticket("02", "Приём", "R01.1, R02, A01", "01", ["src/bot/"], 2,
                                                 model="haiku", effort="low"))
        self.ap("tickets")
        self.ap("ticket", "02", "start")
        code, out = self.ap("ticket", "02", "retry")
        self.assertIn("ретрай 1: sonnet · medium", out)
        code, out = self.ap("ticket", "02", "retry")
        self.assertIn("ретрай 2: opus · high", out)
        t = {x["id"]: x for x in self.state()["tickets"]}["02"]
        self.assertEqual([(a["model"], a["effort"]) for a in t["attempts"]],
                         [("haiku", "low"), ("sonnet", "medium"), ("opus", "high")])
        self.assertEqual((t["model"], t["effort"]), ("haiku", "low"))      # план не переписывается

    def test_the_ladder_stops_at_opus_xhigh(self):
        self.plan()
        self.ap("tickets")
        self.ap("ticket", "01", "start")
        self.assertIn("ретрай 1: opus · high", self.ap("ticket", "01", "retry")[1])
        self.assertIn("ретрай 2: opus · xhigh", self.ap("ticket", "01", "retry")[1])

    def test_done_records_gates_and_base_and_publish_keeps_them(self):
        self.plan()
        self.ap("tickets")
        self.ap("ticket", "01", "start")
        self.ap("ticket", "01", "done", "--tests", "3/0", "--gates", "crap 7.4 · dry 0 · mutants 9/9",
                "--base", "0000000aaaa", "--commit", "1111111bbbb")
        self.ap("tickets")
        t = {x["id"]: x for x in self.state()["tickets"]}["01"]
        self.assertEqual((t["gates"], t["base"], t["commit"]),
                         ("crap 7.4 · dry 0 · mutants 9/9", "0000000aaaa", "1111111bbbb"))
        self.assertEqual(len(t["attempts"]), 1)

    def test_ls_check_names_what_the_fork_needs(self):
        self.init()
        with mock.patch.dict(os.environ, {"HOME": self.root}):
            code, out = self.ap("ls-check")
            self.assertEqual(code, 0, out)
            self.assertIn("! не установлен скилл ub-mode", out)
            self.assertIn("! .gitignore без .claude/worktrees/", out)
            os.makedirs(os.path.join(self.root, ".claude", "skills", "ub-mode"))
            with open(os.path.join(self.root, ".claude", "skills", "ub-mode", "SKILL.md"), "w") as f:
                f.write("# ub-mode\n")
            with open(os.path.join(self.root, ".gitignore"), "a") as f:
                f.write(".claude/worktrees/\n")
            with open(os.path.join(self.root, "Makefile"), "w") as f:
                f.write("check:\n\ttrue\ngates:\n\ttrue\n")
            code, out = self.ap("ls-check")
        self.assertNotIn("! ", out)
        self.assertIn("make gates есть", out)

    # ── форк autopilot-ls: ночная очередь ──────────────────────────────────
    def night_plan(self):
        self.init()
        self.write("manifest.md", MANIFEST)
        self.write("tickets/01-karkas.md", ticket("01", "Каркас", "R01", "—", ["src/core/"], 1, model="opus",
                                                  effort="high", night="нет"))
        self.write("tickets/02-a.md", ticket("02", "А", "R02", "01", ["src/a/"], 2, night="да"))
        self.write("tickets/03-b.md", ticket("03", "Б", "R05", "01", ["src/b/"], 2, night="да"))
        self.write("tickets/04-c.md", ticket("04", "В", "R02", "02", ["src/c/"], 3, night="да"))
        self.write("tickets/05-d.md", ticket("05", "Г", "R05", "03", ["src/d/"], 3, night="нет"))
        self.ap("tickets")

    def test_check_plan_refuses_night_for_a_ticket_with_an_open_row(self):
        self.night_plan()
        self.write("manifest.md", MANIFEST.replace("| R02 | «складывает в таблицу» | in-spec |",
                                                   "| R02 | «складывает в таблицу» | open |"))
        code, out = self.ap("check-plan")
        self.assertIn("таск 02: «Ночью: да», а R02 ещё open — вопрос владельцу не закрыт", out)

    def test_queue_takes_night_tickets_whose_parents_are_done_or_queued(self):
        self.night_plan()
        code, out = self.ap("queue")
        self.assertIn("в очереди 0", out)                               # 01 не сдан, не ночной
        self.ap("ticket", "01", "start")
        self.ap("ticket", "01", "done", "--tests", "3/0", "--commit", "1111111aaaa")
        code, out = self.ap("queue")
        q = self.state()["queue"]
        self.assertEqual(q["tickets"], ["02", "03", "04"])
        self.assertIn({"id": "05", "why": "Ночью: нет"}, q["skipped"])

    def test_night_flies_only_the_queue_and_stops_after_the_first_failure(self):
        self.night_plan()
        self.ap("ticket", "01", "start")
        self.ap("ticket", "01", "done", "--tests", "3/0", "--commit", "1111111aaaa")
        self.ap("queue")
        self.assertEqual(self.ap("night", "start")[0], 0)
        code, out = self.ap("ticket", "05", "start")
        self.assertNotEqual(code, 0)
        self.assertIn("ночью летит только очередь", out)
        self.ap("ticket", "02", "03", "start")
        self.ap("ticket", "02", "done", "--tests", "4/0", "--commit", "2222222bbbb")
        self.ap("ticket", "03", "fail", "--note", "порт занят")
        code, out = self.ap("ticket", "04", "start")
        self.assertNotEqual(code, 0)
        self.assertIn("ночь остановлена", out)
        n = self.state()["night"]
        self.assertEqual((n["status"], n["done"], n["failed"]), ("stopped", ["02"], ["03"]))
        self.ap("night", "end", "--report", "night-2026-11-08.md")
        self.assertEqual(self.state()["night"]["status"], "finished")
        self.assertEqual(self.ap("ticket", "05", "start")[0], 0)           # днём — как обычно

    def test_queue_drop_takes_a_ticket_and_its_dependents_out(self):
        self.night_plan()
        self.ap("ticket", "01", "start")
        self.ap("ticket", "01", "done", "--tests", "3/0", "--commit", "1111111aaaa")
        self.ap("queue")
        self.ap("queue", "drop", "02", "--note", "нужна методика")
        q = self.state()["queue"]
        self.assertEqual(q["tickets"], ["03"])
        self.assertIn({"id": "02", "why": "нужна методика"}, q["skipped"])
        self.assertIn({"id": "04", "why": "ждёт 02"}, q["skipped"])

    # ── форк autopilot-ls: пейсинг лимитов ─────────────────────────────────
    def test_pacing_stores_the_window_and_caps_the_flight(self):
        self.plan()
        self.ap("tickets")
        code, out = self.ap("pacing", "--window", "41", "--reset", "2026-11-08T03:10:00+04:00",
                            "--weekly", "22", "--source", "get_usage")
        self.assertEqual(code, 0, out)
        p = self.state()["pacing"]
        self.assertEqual((p["window_used_pct"], p["weekly_used_pct"], p["reserve_pct"]), (41, 22, 15))
        self.assertEqual(p["window_reset_at"], "2026-11-08T03:10:00+04:00")
        self.assertIn("в полёте не больше 3", out)
        self.assertIn("в полёте не больше 2", self.ap("pacing", "--window", "61")[1])
        code, out = self.ap("pacing", "--window", "85")
        self.assertIn("стоп: окно 85 %", out)
        self.assertIn("продолжить в 2026-11-08T03:15:00+04:00", out)

    def test_pacing_check_compares_the_estimate_with_the_room_left(self):
        self.plan()
        self.ap("tickets")
        self.ap("pacing", "--window", "41", "--reset", "2026-11-08T03:10:00+04:00")
        code, out = self.ap("pacing", "check", "01", "02")
        self.assertIn("01 opus·high ≈10 % — можно (место 35 %)", out)
        self.assertIn("02 sonnet·medium ≈5 % — можно", out)
        self.ap("pacing", "--window", "75", "--est", "02=7")
        code, out = self.ap("pacing", "check", "01", "02")
        self.assertIn("01 opus·high ≈10 % — нельзя (место 8 %)", out)
        self.assertIn("02 sonnet·medium ≈7 % — можно", out)

    def test_pacing_stops_the_night_at_the_weekly_cap(self):
        self.night_plan()
        self.ap("pacing", "--window", "10", "--weekly", "30", "--night-weekly-max-pct", "15")
        self.ap("night", "start")
        self.assertEqual(self.state()["night"]["weekly_at_start"], 30)
        code, out = self.ap("pacing", "--window", "20", "--weekly", "46")
        self.assertIn("стоп ночи: неделя +16 % из 15 %", out)
        self.assertEqual(self.state()["night"]["status"], "stopped")

    def test_the_window_pauses_the_night_and_night_start_resumes_it(self):
        self.night_plan()
        self.ap("ticket", "01", "start")
        self.ap("ticket", "01", "done", "--tests", "3/0", "--commit", "1111111aaaa")
        self.ap("pacing", "--window", "10", "--reset", "2026-11-08T03:10:00+04:00")
        self.ap("night", "start")
        self.ap("ticket", "02", "start")
        self.ap("ticket", "02", "done", "--tests", "4/0", "--commit", "2222222bbbb")
        self.ap("pacing", "--window", "86")
        self.assertEqual(self.state()["night"]["status"], "paused")
        code, out = self.ap("ticket", "03", "start")
        self.assertIn("ночь на паузе до 2026-11-08T03:15:00+04:00", out)
        self.ap("pacing", "--window", "3", "--reset", "2026-11-08T08:15:00+04:00")
        self.ap("night", "start")
        n = self.state()["night"]
        self.assertEqual((n["status"], n["done"]), ("running", ["02"]))
        self.assertEqual(self.ap("ticket", "03", "start")[0], 0)

    def test_a_night_stopped_by_a_failure_does_not_restart_before_its_report(self):
        self.night_plan()
        self.ap("ticket", "01", "start")
        self.ap("ticket", "01", "done", "--tests", "3/0", "--commit", "1111111aaaa")
        self.ap("night", "start")
        self.ap("ticket", "02", "start")
        self.ap("ticket", "02", "fail", "--note", "сеть")
        code, out = self.ap("night", "start")
        self.assertNotEqual(code, 0)
        self.assertIn("сначала отчёт", out)

    # ── форк autopilot-ls: воркеры-сессии ─────────────────────────────────
    def test_sessions_dispatch_keeps_a_board_from_state_and_status_files(self):
        self.plan()
        self.ap("tickets")
        self.ap("set", "dispatch=sessions")
        self.ap("ticket", "02", "start", "--session", "local_abc", "--name", "t02-priem")
        self.write("status/02.json", json.dumps({"ticket": "02", "status": "DONE", "branch": "ls/ticket-02-x1",
                                                 "worktree": "/tmp/wt-02", "tests": "5 passed"}))
        self.ap()
        board = json.loads(read(os.path.join(self.dir, "board.json")))
        row = {r["id"]: r for r in board["tickets"]}["02"]
        self.assertEqual((row["session_id"], row["name"], row["status"]), ("local_abc", "t02-priem", "in-progress"))
        self.assertEqual((row["worker_status"], row["branch"], row["worktree"]), ("DONE", "ls/ticket-02-x1", "/tmp/wt-02"))
        self.assertTrue(row["lease_until"] > row["attempts"][0]["at"])
        self.assertEqual(row["model"], "sonnet")

    def test_no_board_without_sessions_dispatch(self):
        self.plan()
        self.ap("tickets")
        self.ap("ticket", "02", "start")
        self.assertFalse(os.path.exists(os.path.join(self.dir, "board.json")))

    # ── форк autopilot-ls: e2e L2 ──────────────────────────────────────────
    def test_e2e_records_an_l2_run_and_its_regressions(self):
        self.init()
        code, out = self.ap("e2e", "dialogues=12", "passed=11", "usd=3.4",
                            "--regression", "d07 — коуч задал 14 вопросов при 5–10")
        self.assertEqual(code, 0, out)
        e = self.state()["e2e"]
        self.assertEqual((e["dialogues"], e["passed"], e["usd"]), (12, 11, 3.4))
        self.assertEqual(e["regressions"], ["d07 — коуч задал 14 вопросов при 5–10"])
        self.assertIn("L2: 11 из 12", out)
        code, out = self.ap("e2e", "dialogues=12")
        self.assertNotEqual(code, 0)

    # ── форк autopilot-ls: программа прогонов ──────────────────────────────
    PROGRAM = """# Программа

| ID | Прогон | Зависит от | Статус | Папка | Итог |
|----|--------|------------|--------|-------|------|
| P01 | Ядро и БД | — | landed | `2026-11-01-core` | ядро есть |
| P02 | Промпты стадий 1–3 | P01 | pending | — | — |
| P03 | Telegram-канал | P02 | pending | — | — |
| P04 | Фокус-группа | P01 | blocked | — | ждёт методику |
"""

    def write_program(self):
        with open(os.path.join(self.a, "program.md"), "w", encoding="utf-8") as f:
            f.write(self.PROGRAM)

    def test_program_names_the_next_run_whose_parents_landed(self):
        self.write_program()                         # до первого прогона state.js ещё нет
        code, out = self.ap("program")
        self.assertEqual(code, 0, out)
        self.assertIn("следующий: P02 — Промпты стадий 1–3", out)
        self.assertIn("P03 ждёт P02", out)
        self.assertIn("P04 blocked — ждёт методику", out)

    def test_a_run_of_the_program_marks_its_row_from_init_to_finish(self):
        self.write_program()
        code, out = self.ap("init", "--slug", "prompts", "--title", "Промпты", "--skill-dir", SKILL,
                            "--program", "P02")
        self.assertEqual(code, 0, out)
        s = self.state()
        self.assertEqual(s["program"], "P02")
        prog = read(os.path.join(self.a, "program.md"))
        self.assertRegex(prog, r"\| P02 \|[^\n]*\| in-flight \| `%s` \|" % re.escape(s["dir"]))
        self.ap("finish", "--result", "промпты 1–3 на месте", "--by-user", "«сдавай»")
        prog = read(os.path.join(self.a, "program.md"))
        self.assertRegex(prog, r"\| P02 \|[^\n]*\| landed \| `[^`]*prompts` \| промпты 1–3 на месте \|")
        self.assertIn("следующий: P03", self.ap("program")[1])

    def test_pacing_refuses_launches_over_the_window_and_the_flight_cap(self):
        self.night_plan()
        self.ap("ticket", "01", "start")
        self.ap("ticket", "01", "done", "--tests", "3/0", "--commit", "1111111aaaa")
        self.ap("pacing", "--window", "70")
        code, out = self.ap("ticket", "02", "03", "04", "start")
        self.assertNotEqual(code, 0)
        self.assertIn("в полёте было бы 3, окно 70 % позволяет 2", out)
        self.assertEqual(self.ap("ticket", "02", "03", "start")[0], 0)
        self.ap("pacing", "--window", "90")
        code, out = self.ap("ticket", "04", "start")
        self.assertIn("окно 90 % — новых запусков нет", out)

    # ── форк autopilot-ls: обзор промпта владельцем ────────────────────────
    def prompt_plan(self):
        self.plan()
        self.write("tickets/03-coach.md", ticket("03", "Промпт коуча", "R02", "01", ["prompts/coach/", "evals/coach/"],
                                                 2, "да — промпт", "opus", kind="prompt", effort="high",
                                                 attention="review", night="да"))
        self.write("tickets/04-next.md", ticket("04", "После коуча", "R05", "03", ["src/next/"], 3, night="да"))
        self.ap("tickets")
        self.ap("ticket", "01", "start")
        self.ap("ticket", "01", "done", "--tests", "3/0", "--commit", "1111111aaaa")

    def test_a_prompt_ticket_waits_for_the_owner_and_lands_only_on_their_words(self):
        self.prompt_plan()
        self.ap("ticket", "03", "start")
        code, out = self.ap("ticket", "03", "await", "--page", "prompt-reviews/03-coach.html")
        self.assertNotEqual(code, 0)
        self.assertIn("нет --commit", out)
        code, out = self.ap("ticket", "03", "await", "--page", "prompt-reviews/03-coach.html",
                            "--commit", "3333333cccc", "--gates", "eval 18/20")
        self.assertEqual(code, 0, out)
        t = {x["id"]: x for x in self.state()["tickets"]}["03"]
        self.assertEqual((t["status"], t["page"], t["commit"]), ("awaiting_owner", "prompt-reviews/03-coach.html",
                                                                "3333333cccc"))
        self.assertRegex(self.manifest(), r"\| R02 \|[^\n]*\| in-ticket \|")
        code, out = self.ap("ticket", "03", "done")
        self.assertNotEqual(code, 0)
        self.assertIn("ждёт владельца", out)
        self.assertEqual(self.ap("ticket", "03", "repair", "--note", "владелец: вопросов не больше пяти")[0], 0)
        self.ap("ticket", "03", "await", "--page", "prompt-reviews/03-coach.html", "--commit", "4444444dddd")
        code, out = self.ap("ticket", "03", "done", "--by-user", "«ок, утверждаю»")
        self.assertEqual(code, 0, out)
        t = {x["id"]: x for x in self.state()["tickets"]}["03"]
        self.assertEqual((t["status"], t["approvedByUser"], t["repairs"]), ("done", ["«ок, утверждаю»"], 1))

    def test_the_night_lists_awaiting_tickets_and_their_dependents_wait(self):
        self.prompt_plan()
        self.ap("night", "start")
        self.ap("ticket", "03", "start")
        self.ap("ticket", "03", "await", "--page", "prompt-reviews/03-coach.html", "--commit", "3333333cccc")
        self.assertEqual(self.state()["night"]["awaiting"], ["03"])
        self.ap("queue")
        self.assertIn({"id": "04", "why": "ждёт 03"}, self.state()["queue"]["skipped"])

    def test_pacing_without_a_5_hour_window_paces_by_the_week(self):
        """get_usage на части тарифов отдаёт только недельные окна — темп тогда по неделе."""
        self.night_plan()
        code, out = self.ap("pacing", "--weekly", "48", "--source", "get_usage")
        self.assertIn("окна 5 ч нет — темп по неделе: неделя 48 % · в полёте не больше 3", out)
        self.assertIsNone(self.state()["pacing"].get("window_used_pct"))
        self.assertIn("в полёте не больше 2", self.ap("pacing", "--weekly", "81")[1])
        code, out = self.ap("pacing", "--weekly", "95", "--weekly-reset", "2026-11-08T13:00:00+00:00")
        self.assertIn("стоп: неделя 95 %", out)
        self.assertIn("продолжить в 2026-11-08T13:05:00+00:00", out)
        self.ap("ticket", "01", "start")
        code, out = self.ap("ticket", "01", "start")
        self.assertNotEqual(code, 0)
        self.assertIn("неделя 95 % — новых запусков нет", out)

    def test_queue_builds_on_a_parent_under_point_review(self):
        """Таск на точечном ревью уже влит — следующие строятся на нём (phases/6-review.md)."""
        self.night_plan()
        self.ap("ticket", "01", "start")
        self.ap("ticket", "01", "done", "--tests", "3/0", "--commit", "1111111aaaa")
        self.ap("ticket", "01", "review")
        self.ap("queue")
        self.assertEqual(self.state()["queue"]["tickets"], ["02", "03", "04"])
        self.ap("ticket", "01", "repair", "--note", "ключ схемы")
        self.ap("queue")
        self.assertIn({"id": "02", "why": "ждёт 01"}, self.state()["queue"]["skipped"])

    def test_the_night_counts_only_its_own_queue(self):
        """Ревью дневного таска, закрытое ночью, — не ночная работа."""
        self.night_plan()
        self.ap("ticket", "01", "start")
        self.ap("ticket", "01", "done", "--tests", "3/0", "--commit", "1111111aaaa")
        self.ap("ticket", "01", "review")
        self.ap("night", "start")
        self.ap("ticket", "02", "start")
        self.ap("ticket", "02", "done", "--tests", "4/0", "--commit", "2222222bbbb")
        self.ap("ticket", "01", "done")
        self.assertEqual(self.state()["night"]["done"], ["02"])


class Pure(unittest.TestCase):
    """Функции без процесса: опознание своего сервера и версия навыка."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("ap", AP)
        cls.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.m)

    def test_is_ours(self):
        a = self.m.A
        self.assertTrue(self.m.is_ours("/usr/bin/python3 -m http.server 8000 --bind 127.0.0.1 --directory %s" % a))
        self.assertFalse(self.m.is_ours("python3 -m http.server 8000 --directory %s2" % a))
        self.assertFalse(self.m.is_ours("node http-server --directory %s" % a))

    def test_version(self):
        self.assertEqual(self.m._version('---\nname: x\nmetadata:\n  version: "2.0.1"\n---\nversion: 9'), (2, 0, 1))
        self.assertIsNone(self.m._version("---\nname: x\n---\nversion: 3\n"))

    def test_skill_declares_a_version(self):
        text = read(os.path.join(SKILL, "SKILL.md"))
        self.assertIsNotNone(self.m._version(text))


class Architecture(Base):
    """Гейт GA: балл считает ap.py, порог 9, минимум 8, подтверждение вторым критиком, потолок кругов."""

    KEYS = ("product_fit qualities boundaries domain data flows failure security ops testability "
            "performance evolution simplicity delivery decisions reuse llm legacy").split()

    def audit(self, n, score=9.2, kind="audit", **over):
        crit = {k: {"score": score, "evidence": "§3: цитата", "gap": "мелочь"} for k in self.KEYS}
        crit["llm"] = {"na": "в продукте нет моделей"}
        crit["legacy"] = {"na": "новый проект"}
        crit["reuse"] = {"na": "маленькая сборка, готовое не искали"}
        crit.update(over.pop("criteria", {}))
        body = {"criteria": crit, "findings": [], "prior": [], "summary": "Итог простыми словами",
                "scenarios": [{"name": "сценарий %d" % i, "verdict": "проходит"} for i in range(5)]}
        body.update(over)
        os.makedirs(os.path.join(self.a, "architecture-audit"), exist_ok=True)
        rel = ".autopilot/architecture-audit/%02d.json" % n
        with open(os.path.join(self.root, rel), "w", encoding="utf-8") as f:
            json.dump(body, f, ensure_ascii=False)
        return self.ap("arch", "round", "--file", rel, "--kind", kind)

    def status(self):
        return json.loads(read(os.path.join(self.a, "architecture-audit", "state.json")))

    def start(self):
        self.ap("arch", "start", "--scope", "project")

    @staticmethod
    def finding(fid, severity="major", criterion="data", **over):
        return dict({"id": fid, "severity": severity, "criterion": criterion, "what": "нет миграций", "fix": "описать"}, **over)

    def judge(self, n, **verdicts):
        body = {"verdicts": [{"id": i, "verdict": v, "why": "§4 это решает"} for i, v in verdicts.items()]}
        rel = ".autopilot/architecture-audit/%02d-judge.json" % n
        with open(os.path.join(self.root, rel), "w", encoding="utf-8") as f:
            json.dump(body, f, ensure_ascii=False)
        return self.ap("arch", "judge", "--file", rel)

    def rounds_with(self, *counts):
        """Круги audit с заданным числом серьёзных находок, каждый разобран судьёй: всё настоящее."""
        for n, count in enumerate(counts, 1):
            ids = ["A%d" % i for i in range(1, count + 1)]
            before = ["A%d" % i for i in range(1, counts[n - 2] + 1)] if n > 1 else []
            code, out = self.audit(n, 8, findings=[self.finding(i) for i in ids],
                                   prior=[{"id": i, "closed": True} for i in before])
            self.assertEqual(code, 0, out)
            code, out = self.judge(n, **{i: "real" for i in ids})
            self.assertEqual(code, 0, out)
        return out

    def test_no_fewer_serious_findings_stops_and_asks_the_owner(self):
        self.start()
        out = self.rounds_with(2, 2)
        self.assertIn("не стало меньше (было 2, стало 2)", out)
        self.assertTrue(self.status()["rounds"][1]["stalled"])
        code, out = self.audit(3, 9.2, prior=[{"id": "A1", "closed": True}, {"id": "A2", "closed": True}])
        self.assertNotEqual(code, 0)
        self.assertIn("стоп", out)

    def test_fewer_serious_findings_go_on(self):
        self.start()
        out = self.rounds_with(13, 9)
        self.assertIn("ещё круг", out)
        self.assertFalse(self.status()["rounds"][1].get("stalled"))

    def test_more_rounds_only_on_the_owners_words(self):
        self.start()
        self.rounds_with(1, 1)
        code, out = self.ap("arch", "continue")
        self.assertNotEqual(code, 0)
        self.assertIn("слова владельца", out)
        code, out = self.ap("arch", "continue", "--by-user", "«давай ещё один»")
        self.assertEqual(code, 0, out)
        code, out = self.audit(3, 8.5, prior=[{"id": "A1", "closed": True}])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.status()["rounds"][1]["continued"], "«давай ещё один»")

    def test_the_stop_is_counted_after_the_judge(self):
        self.start()
        self.audit(1, 8, findings=[self.finding("A1"), self.finding("A2"), self.finding("A3")])
        self.judge(1, A1="real", A2="real", A3="real")
        closed = [{"id": i, "closed": True} for i in ("A1", "A2", "A3")]
        self.audit(2, 8, findings=[self.finding("A1"), self.finding("A2"), self.finding("A3"), self.finding("A4")], prior=closed)
        code, out = self.judge(2, A1="real", A2="refuted", A3="preference", A4="risk")
        self.assertIn("ещё круг", out)
        self.assertFalse(self.status()["rounds"][1].get("stalled"))

    def test_a_confirmation_is_not_compared_with_an_audit(self):
        self.start()
        self.audit(1, 9.2)
        self.audit(2, 8.5, kind="confirm", findings=[self.finding("A1"), self.finding("A2")])
        code, out = self.judge(2, A1="real", A2="real")
        self.assertIn("ещё круг", out)
        self.assertFalse(self.status()["rounds"][1].get("stalled"))

    def test_the_next_round_waits_for_the_judge(self):
        self.start()
        self.audit(1, 8, findings=[self.finding("A1")])
        code, out = self.audit(2, 9.2, prior=[{"id": "A1", "closed": True}])
        self.assertNotEqual(code, 0)
        self.assertIn("судья", out)

    def test_the_judge_answers_every_serious_finding_and_adds_none(self):
        self.start()
        self.audit(1, 8, findings=[self.finding("A1"), self.finding("A2"), self.finding("A3", "minor")])
        code, out = self.judge(1, A1="real")
        self.assertNotEqual(code, 0)
        self.assertIn("A2", out)
        code, out = self.judge(1, A1="real", A2="real", A3="real")
        self.assertNotEqual(code, 0)
        self.assertIn("A3", out)
        self.assertFalse(self.status()["rounds"][0].get("judged"))

    def test_a_dismissed_finding_goes_to_no_repair_and_no_next_round(self):
        self.start()
        self.audit(1, 8, findings=[self.finding("A1"), self.finding("A2")])
        code, out = self.judge(1, A1="real", A2="preference")
        self.assertIn("в ремонт: A1\n", out)
        code, out = self.audit(2, 8.5, prior=[{"id": "A1", "closed": True}])
        self.assertEqual(code, 0, out)

    def test_the_judge_clearing_the_blocking_finding_can_reach_the_threshold(self):
        self.start()
        low = {"data": {"score": 7, "evidence": "§4", "gap": "нет миграций"}}
        self.audit(1, 9.6, criteria=low, findings=[self.finding("A1", "blocking")])
        self.assertFalse(self.status()["rounds"][0]["passed"])
        code, out = self.judge(1, A1="refuted")
        self.assertEqual(code, 0, out)
        self.assertIn("порог взят", out)
        self.assertTrue(self.status()["rounds"][0]["passed"])

    def test_a_blocking_finding_left_standing_holds_the_floor(self):
        self.start()
        low = {"data": {"score": 7, "evidence": "§4", "gap": "нет миграций"}}
        self.audit(1, 9.6, criteria=low, findings=[self.finding("A1", "blocking")])
        code, out = self.judge(1, A1="risk")
        self.assertFalse(self.status()["rounds"][0]["passed"])
        self.assertEqual(self.status()["rounds"][0]["floor"], 7)

    def test_the_judge_does_not_remove_the_owners_question(self):
        self.start()
        self.audit(1, 8, findings=[self.finding("A1", owner=True)])
        code, out = self.judge(1, A1="preference")
        self.assertNotEqual(code, 0)
        self.assertIn("вопрос владельца", out)

    def test_a_low_score_asks_for_another_round(self):
        self.start()
        code, out = self.audit(1, 7.5)
        self.assertEqual(code, 0, out)
        self.assertIn("7.5 из 10", out)
        self.assertIn("ещё круг", out)
        self.assertFalse(self.status()["gate"]["ok"])

    def test_the_score_is_weighted_by_the_tool(self):
        self.start()
        self.audit(1, 9, criteria={"product_fit": {"score": 6, "evidence": "§1", "gap": "не тот продукт"}})
        # веса применимых критериев: всего 27, product_fit — 3: (24·9 + 3·6) / 27
        self.assertEqual(self.status()["rounds"][0]["overall"], 8.67)

    def test_a_high_average_does_not_hide_a_hole(self):
        self.start()
        code, out = self.audit(1, 9.5, criteria={"security": {"score": 7, "evidence": "§8", "gap": "нет модели угроз"}})
        self.assertEqual(code, 0, out)
        self.assertIn("security 7", out)
        self.assertFalse(self.status()["rounds"][0]["passed"])

    def test_a_pass_needs_a_second_independent_critic(self):
        self.start()
        code, out = self.audit(1, 9.2)
        self.assertIn("подтверждение", out)
        self.assertFalse(self.status()["gate"]["ok"])
        code, out = self.audit(2, 9.1, kind="confirm")
        self.assertEqual(code, 0, out)
        self.assertIn("GA пройден", out)
        self.assertTrue(self.status()["gate"]["ok"])

    def test_nothing_to_confirm_before_a_passing_round(self):
        self.start()
        self.audit(1, 8)
        code, out = self.audit(2, 9.5, kind="confirm")
        self.assertNotEqual(code, 0)
        self.assertIn("подтверждать нечего", out)

    def test_a_failed_confirmation_sends_it_back(self):
        self.start()
        self.audit(1, 9.2)
        code, out = self.audit(2, 8.6, kind="confirm")
        self.assertIn("ещё круг", out)
        self.assertFalse(self.status()["gate"]["ok"])

    def test_an_incomplete_audit_is_refused_whole(self):
        self.start()
        crit = {"data": {"score": 7, "evidence": "§4"}, "failure": {"score": 9.5, "evidence": ""}}
        code, out = self.audit(1, 9.2, criteria=crit)
        self.assertNotEqual(code, 0)
        self.assertIn("data: 7", out)
        self.assertIn("failure: оценка без доказательства", out)
        self.assertEqual(self.status()["rounds"], [])

    def test_the_product_cannot_be_marked_not_applicable(self):
        self.start()
        code, out = self.audit(1, 9.2, criteria={"product_fit": {"na": "не нужно"}})
        self.assertNotEqual(code, 0)
        self.assertIn("product_fit", out)

    def test_a_blocking_finding_cannot_sit_on_a_high_score(self):
        self.start()
        finding = {"id": "A1", "severity": "blocking", "criterion": "data", "what": "нет миграций", "fix": "описать"}
        code, out = self.audit(1, 9.2, findings=[finding])
        self.assertNotEqual(code, 0)
        self.assertIn("A1 блокирует", out)

    def test_old_findings_must_be_answered(self):
        self.start()
        finding = {"id": "A1", "severity": "major", "criterion": "data", "what": "нет миграций", "fix": "описать"}
        self.audit(1, 8, findings=[finding])
        self.judge(1, A1="real")
        code, out = self.audit(2, 9.2)
        self.assertNotEqual(code, 0)
        self.assertIn("A1", out)
        code, out = self.audit(2, 9.2, prior=[{"id": "A1", "closed": True}])
        self.assertEqual(code, 0, out)

    def test_an_open_blocking_finding_stops_the_pass(self):
        self.start()
        finding = {"id": "A1", "severity": "blocking", "criterion": "data", "what": "нет миграций", "fix": "описать"}
        low = {"data": {"score": 6, "evidence": "§4", "gap": "нет"}}
        self.audit(1, 9, criteria=low, findings=[finding])
        self.judge(1, A1="real")
        self.audit(2, 9.4, prior=[{"id": "A1", "closed": False}])
        self.assertFalse(self.status()["rounds"][1]["passed"])

    def test_a_broken_scenario_stops_the_pass(self):
        self.start()
        scenarios = [{"name": "отказ базы", "verdict": "ломается"}] + [{"name": "s%d" % i, "verdict": "проходит"} for i in range(4)]
        code, out = self.audit(1, 9.6, scenarios=scenarios)
        self.assertIn("отказ базы", out)
        self.assertFalse(self.status()["rounds"][0]["passed"])

    def test_rounds_are_capped_and_then_it_is_the_owners_call(self):
        self.start()
        for n in range(1, 7):
            code, out = self.audit(n, 8)
            self.assertEqual(code, 0, out)
        self.assertIn("потолок", out)
        code, out = self.audit(7, 9.5)
        self.assertNotEqual(code, 0)
        self.assertIn("потолок", out)
        code, out = self.ap("arch", "waive")
        self.assertNotEqual(code, 0)
        code, out = self.ap("arch", "waive", "--by-user", "«идём так»")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.status()["gate"]["waived"], "«идём так»")
        self.assertTrue(self.status()["gate"]["ok"])

    def test_the_spec_waits_for_the_architecture_or_a_reason(self):
        self.init()
        code, out = self.ap("stage", "spec")
        self.assertNotEqual(code, 0)
        self.assertIn("архитектура не принята", out)
        self.ap("stage", "architecture", "skip", "--note", "сборка на 2 тысячи строк")
        code, out = self.ap("stage", "spec")
        self.assertEqual(code, 0, out)

    def test_the_stage_closes_only_on_an_accepted_architecture(self):
        self.init()
        self.ap("stage", "scout", "skip", "--note", "правки в готовом коде")
        self.ap("stage", "architecture")
        code, out = self.ap("stage", "architecture", "done")
        self.assertNotEqual(code, 0)
        self.start()
        self.audit(1, 9.2)
        self.audit(2, 9.2, kind="confirm")
        code, out = self.ap("stage", "architecture", "done")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.stage("architecture")["status"], "done")

    def test_the_gate_shows_on_the_run(self):
        self.init()
        self.start()
        self.audit(1, 8)
        g = self.state()["gates"]["GA"]
        self.assertEqual((g["ok"], g["score"], g["rounds"]), (False, 8.0, 1))

    def test_it_works_before_any_run_exists(self):
        self.start()
        code, out = self.audit(1, 9.2)
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(os.path.join(self.a, "state.js")))

    def test_a_change_reopens_the_gate_and_has_its_own_cap(self):
        self.start()
        self.audit(1, 9.2)
        self.audit(2, 9.2, kind="confirm")
        code, out = self.audit(3, 9.5)
        self.assertNotEqual(code, 0)                      # принятая меняется только через delta
        self.ap("arch", "delta", "--note", "добавили очередь")
        self.assertFalse(self.status()["gate"]["ok"])
        code, out = self.audit(3, 9.3, kind="delta")
        self.assertIn("изменение принято", out)
        self.assertTrue(self.status()["gate"]["ok"])

    def test_a_ticket_names_its_sections_once_the_architecture_is_accepted(self):
        self.start()
        self.audit(1, 9.2)
        self.audit(2, 9.2, kind="confirm")
        self.init()
        self.write("manifest.md", MANIFEST)
        self.write("tickets/01-a.md", ticket("01", "Ядро", "R01, R02, R05", "—", "`src/`", 1))
        out = self.ap("check-plan")[1]
        self.assertIn("нет поля Архитектура", out)

    def test_a_check_against_the_code_does_not_move_the_gate(self):
        self.start()
        self.audit(1, 9.2)
        self.audit(2, 9.2, kind="confirm")
        code, out = self.audit(3, 6.5, kind="as-built")
        self.assertEqual(code, 0, out)
        self.assertTrue(self.status()["gate"]["ok"])


class Scout(Base):
    """Поиск готового: решения по частям, лицензии, владелец решает про чужой проект за основу."""

    FACTS = {"license": "MIT", "stars": 5000, "pushedAt": "2026-10-01", "archived": False, "checkedAt": "2026-11-10"}

    def capability(self, cid="C1", decision="adopt", license="MIT", **over):
        cap = {"id": cid, "name": "Приём сообщений", "requirements": ["R01"], "core": False, "decision": decision,
               "choice": "aiogram/aiogram", "why": "зрелая библиотека",
               "candidates": [{"repo": "aiogram/aiogram", "facts": dict(self.FACTS, license=license)}]}
        cap.update(over)
        return cap

    def write_art(self, *caps):
        with open(os.path.join(self.a, "prior-art.json"), "w", encoding="utf-8") as f:
            json.dump({"products": [], "capabilities": list(caps)}, f, ensure_ascii=False)

    def check(self, *caps):
        self.write_art(*caps)
        return self.ap("scout", "check")

    def test_needing_no_code_is_a_decision_with_a_reason(self):
        fine = self.capability("C1", "configure", candidates=[], choice=None, why="хватит настройки вебхука")
        code, out = self.check(fine)
        self.assertEqual(code, 0, out)
        self.assertIn("берём готовым 1, пишем сами 0", out)
        self.assertIn("решение без причины", self.check(dict(fine, why=""))[1])
        self.assertIn("не названы требования", self.check(dict(fine, requirements=[]))[1])

    def test_a_clean_plan_passes_and_counts_what_we_take(self):
        code, out = self.check(self.capability(), self.capability("C2", "build", candidates=[], searched="искал очереди"))
        self.assertEqual(code, 0, out)
        self.assertIn("берём готовым 1, пишем сами 1", out)

    def test_an_unverified_candidate_is_refused(self):
        cap = self.capability()
        del cap["candidates"][0]["facts"]
        code, out = self.check(cap)
        self.assertIn("не проверен", out)

    def test_copyleft_can_only_be_studied(self):
        self.assertIn("лицензия GPL-3.0", self.check(self.capability(license="GPL-3.0"))[1])
        self.assertIn("лицензия none", self.check(self.capability("C1", "adapt", license="none", spike={"result": "да"}))[1])
        code, out = self.check(self.capability("C1", "learn", license="GPL-3.0"))
        self.assertNotIn("лицензия", out)

    def test_a_library_may_be_lgpl_but_copied_code_may_not(self):
        self.assertNotIn("лицензия", self.check(self.capability(license="LGPL-3.0"))[1])
        self.assertIn("лицензия", self.check(self.capability("C1", "adapt", license="LGPL-3.0", spike={"result": "да"}))[1])

    def test_an_archived_project_is_not_taken(self):
        cap = self.capability()
        cap["candidates"][0]["facts"]["archived"] = True
        self.assertIn("в архиве", self.check(cap)[1])

    def test_what_makes_the_product_needs_the_owners_word(self):
        self.assertIn("отличает продукт", self.check(self.capability(core=True))[1])
        self.assertNotIn("отличает продукт", self.check(self.capability(core=True, byUser="«берём»"))[1])

    def test_a_foreign_project_as_a_base_is_the_owners_call_and_needs_a_spike(self):
        out = self.check(self.capability("C1", "fork"))[1]
        self.assertIn("решение владельца", out)
        self.assertIn("проба", out)
        out = self.check(self.capability("C1", "fork", byUser="«да»", spike={"result": "собирается"}))[1]
        self.assertIn("GS пройден", out)

    def test_building_ourselves_must_say_what_was_searched(self):
        self.assertIn("что искали", self.check(self.capability("C1", "build", candidates=[]))[1])

    def test_the_choice_must_be_among_the_candidates(self):
        self.assertIn("нет среди кандидатов", self.check(self.capability(choice="other/repo"))[1])

    def test_architecture_waits_for_the_search_or_a_reason(self):
        self.init()
        code, out = self.ap("stage", "architecture")
        self.assertNotEqual(code, 0)
        self.assertIn("поиск готового", out)
        self.ap("stage", "scout", "skip", "--note", "правки в готовом коде")
        code, out = self.ap("stage", "architecture")
        self.assertEqual(code, 0, out)

    def test_the_gate_shows_on_the_run(self):
        self.init()
        self.check(self.capability())
        g = self.state()["gates"]["GS"]
        self.assertEqual((g["ok"], g["taken"], g["capabilities"]), (True, 1, 1))

    def test_verify_takes_facts_from_github_and_drops_inventions(self):
        spec = importlib.util.spec_from_file_location("ap_scout", os.path.join(self.a, "ap.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        m.PRIOR_ART = os.path.join(self.a, "prior-art.json")
        known = {"aiogram/aiogram": {"full_name": "aiogram/aiogram", "license": {"spdx_id": "MIT"},
                                     "stargazers_count": 5000, "pushed_at": "2026-10-01T10:00:00Z", "archived": False}}
        m.repo_json = known.get
        m.package_exists = lambda ref: False if ref == "pypi:nope" else True
        data = {"products": [{"repo": "made/up"}], "capabilities": [
            {"id": "C1", "candidates": [{"repo": "aiogram/aiogram", "package": "pypi:nope"}]}]}
        out = m.cmd_scout_verify(data)
        self.assertTrue(any("made/up" in x and x.startswith("!") for x in out))
        self.assertTrue(any("pypi:nope" in x for x in out))
        facts = data["capabilities"][0]["candidates"][0]["facts"]
        self.assertEqual((facts["license"], facts["stars"], facts["pushedAt"]), ("MIT", 5000, "2026-10-01"))
        self.assertNotIn("facts", data["products"][0])

    def test_a_closed_service_can_be_chosen_and_paying_for_it_is_the_owners(self):
        cap = self.capability(choice="ЮKassa", paid=True, candidates=[{"name": "ЮKassa", "closed": True}])
        self.assertIn("платное решает владелец", self.check(cap)[1])
        cap["asked"] = 3
        self.assertIn("GS пройден", self.check(cap)[1])

    def test_an_archived_repo_with_a_living_package_needs_a_reason(self):
        cap = self.capability()
        cap["candidates"][0]["facts"]["archived"] = True
        cap["candidates"][0]["archivedWhy"] = "пакет обновляется, код переехал"
        self.assertIn("GS пройден", self.check(cap)[1])

    def test_a_choice_is_required_and_risky_means_a_spike(self):
        self.assertIn("не назван выбор", self.check(self.capability(choice=None))[1])
        self.assertIn("нужна проба", self.check(self.capability(risky=True))[1])
        self.assertIn("GS пройден", self.check(self.capability(risky=True, spike={"result": "работает"}))[1])

    def test_copied_code_is_no_way_around_what_makes_the_product(self):
        self.assertIn("отличает продукт", self.check(self.capability("C1", "adapt", core=True, spike={"result": "да"}))[1])

    def test_a_long_silence_is_said_but_does_not_refuse(self):
        cap = self.capability()
        cap["candidates"][0]["facts"]["pushedAt"] = "2020-01-01"
        code, out = self.check(cap)
        self.assertIn("GS пройден", out)
        self.assertIn("не обновлялся", out)


PROGRAM_V2 = """# Программа — Запись к мастеру

Параллельно: 1

| ID | Прогон | Зависит от | Статус | Папка | Итог | Тасков | Дней | Простыми словами | Что это даёт | Начат | Сдан |
|----|--------|------------|--------|-------|------|--------|------|------------------|--------------|-------|------|
| P01 | Ядро | — | landed | `2026-11-02-core` | есть | 8 | 3 | Ядро расписания | Записи хранятся | 2026-11-02 | 2026-11-05 |
| P02 | Канал | P01 | pending | — | — | 6 | 2 | Бот | Клиент пишет боту | — | — |
| P03 | Оплата | P02 | pending | — | — | 6 | 4 | Оплата | Клиент платит | — | — |

| ID | Момент | После | Что станет можно |
|----|--------|-------|------------------|
| M1 | Первая запись | P02 | Записать клиента |
"""


class Project(Base):
    """Мастер-план, страница проекта, вопросы владельцу."""

    QUESTION = ("question", "add", "--title", "Сколько хранить", "--about", "Контекст", "--agrees", "Два года",
                "--recommend", "Два года.", "--why", "Хватит", "--silence", "Без срока")

    def program(self, text=PROGRAM_V2, briefs=("P01", "P02", "P03")):
        with open(os.path.join(self.a, "program.md"), "w", encoding="utf-8") as f:
            f.write(text)
        os.makedirs(os.path.join(self.a, "briefs"), exist_ok=True)
        for p in briefs:
            with open(os.path.join(self.a, "briefs", p + ".md"), "w", encoding="utf-8") as f:
                f.write("бриф\n")

    def page(self, name="index.html"):
        return read(os.path.join(self.a, "project", name))

    def page_data(self, name="index.html"):
        m = re.search(r'<script id="data" type="application/json">(.*?)</script>', self.page(name), re.S)
        return json.loads(m.group(1))

    def accept_architecture(self):
        audit = {k: {"score": 9.5, "evidence": "§", "gap": ""} for k, _, _, _ in self.module().ARCH_CRITERIA}
        body = {"criteria": audit, "findings": [], "summary": "Итог",
                "scenarios": [{"name": "s%d" % i, "verdict": "проходит"} for i in range(5)]}
        os.makedirs(os.path.join(self.a, "architecture-audit"), exist_ok=True)
        self.ap("arch", "start", "--scope", "project")
        for n, kind in ((1, "audit"), (2, "confirm")):
            with open(os.path.join(self.a, "architecture-audit", "%02d.json" % n), "w", encoding="utf-8") as f:
                json.dump(body, f, ensure_ascii=False)
            code, out = self.ap("arch", "round", "--file", ".autopilot/architecture-audit/%02d.json" % n, "--kind", kind)
            self.assertEqual(code, 0, out)

    def module(self):
        spec = importlib.util.spec_from_file_location("ap_project", os.path.join(self.a, "ap.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_a_clean_master_plan_passes(self):
        self.program()
        code, out = self.ap("program", "check")
        self.assertIn("мастер-план сходится: прогонов 3", out)

    def test_the_plan_needs_sizes_words_and_a_brief_for_every_run(self):
        self.program(PROGRAM_V2.replace("| 6 | 2 | Бот | Клиент пишет боту |", "| — | — | — | — |"), briefs=("P01", "P03"))
        out = self.ap("program", "check")[1]
        self.assertIn("P02: не заполнено — Тасков, Дней, Простыми словами, Что даёт", out)
        self.assertIn("P02: нет брифа", out)

    def test_a_run_depends_only_on_rows_above_it(self):
        self.program(PROGRAM_V2.replace("| P02 | Канал | P01 |", "| P02 | Канал | P03 |"))
        self.assertIn("P02 зависит от P03", self.ap("program", "check")[1])

    def test_every_live_requirement_goes_to_a_run(self):
        self.program()
        self.init()
        self.write("manifest.md", MANIFEST.replace("| spec §2 |", "| P02 |").replace("| spec §4 |", "| P03 |"))
        out = self.ap("program", "check")[1]
        self.assertIn("R05", out)
        self.assertNotIn("R01", out)
        self.assertNotIn("R03", out)                       # снято владельцем — прогон не нужен

    def test_schedule_uses_facts_dependencies_and_lanes(self):
        m = self.module()
        d = m.dt.date
        rows = m.program_rows(PROGRAM_V2.splitlines())
        s = m.program_schedule(rows, d(2026, 11, 10), 1)
        self.assertEqual(s["P01"], (d(2026, 11, 2), d(2026, 11, 5)))
        self.assertEqual(s["P02"], (d(2026, 11, 10), d(2026, 11, 11)))
        self.assertEqual(s["P03"], (d(2026, 11, 12), d(2026, 11, 15)))

    def test_two_lanes_run_independent_work_side_by_side(self):
        m = self.module()
        d = m.dt.date
        rows = m.program_rows(PROGRAM_V2.replace("| P03 | Оплата | P02 |", "| P03 | Оплата | P01 |").splitlines())
        s = m.program_schedule(rows, d(2026, 11, 10), 2)
        self.assertEqual(s["P03"][0], d(2026, 11, 10))

    def test_a_run_writes_its_dates_and_real_size(self):
        self.program()
        self.ap("init", "--slug", "chan", "--title", "Бот", "--skill-dir", SKILL, "--program", "P02")
        self.dir = os.path.join(self.a, self.state()["dir"])
        self.write("manifest.md", MANIFEST)
        self.write("tickets/01-a.md", ticket("01", "Первый", "R01, R02, R05", "—", ["src/a/"], 1))
        self.ap("tickets")
        row = next(x for x in read(os.path.join(self.a, "program.md")).splitlines() if x.startswith("| P02"))
        cells = [c.strip() for c in row.strip("|").split("|")]
        self.assertEqual((cells[3], cells[6]), ("in-flight", "1"))
        self.assertRegex(cells[10], r"\d{4}-\d\d-\d\d")

    def test_the_old_six_column_program_still_works(self):
        with open(os.path.join(self.a, "program.md"), "w", encoding="utf-8") as f:
            f.write("| ID | Прогон | Зависит от | Статус | Папка | Итог |\n|--|--|--|--|--|--|\n| P01 | Ядро | — | pending | — | — |\n")
        self.ap("init", "--slug", "c", "--title", "Б", "--skill-dir", SKILL, "--program", "P01")
        row = next(x for x in read(os.path.join(self.a, "program.md")).splitlines() if x.startswith("| P01"))
        self.assertEqual(row.count("|"), 7)

    def test_the_plan_lands_without_code(self):
        self.program()
        self.init()
        self.write("manifest.md", MANIFEST.replace("| spec §2 |", "| P02 |").replace("| spec §4 |", "| P03 |").replace("| spec §6 |", "| P03 |"))
        self.accept_architecture()
        code, out = self.ap("program", "plan", "--result", "3 прогона, запись к мастеру")
        self.assertEqual(code, 0, out)
        s = self.state()
        self.assertTrue(s["finishedAt"])
        self.assertEqual(self.stage("build")["status"], "skipped")
        self.assertFalse(s["dir"].endswith("--wip"))
        self.assertIn("план программы", read(os.path.join(self.a, "README.md")))
        self.assertIn("следующий: P02", self.ap("program")[1])

    def test_the_plan_waits_for_the_architecture(self):
        self.program()
        self.init()
        self.write("manifest.md", MANIFEST.replace("| spec §2 |", "| P02 |").replace("| spec §4 |", "| P03 |").replace("| spec §6 |", "| P03 |"))
        code, out = self.ap("program", "plan", "--result", "x")
        self.assertNotEqual(code, 0)
        self.assertIn("архитектура проекта не принята", out)

    def test_the_page_counts_the_whole_project(self):
        self.program()
        self.init()
        code, out = self.ap("project")
        self.assertEqual(code, 0, out)
        d = self.page_data()
        self.assertEqual((d["p"]["progress"]["done"], d["p"]["progress"]["total"]), (8, 20))
        self.assertEqual(d["p"]["progress"]["percent"], 40)
        self.assertEqual([r["status"] for r in d["p"]["runs"]], ["landed", "next", "pending"])
        kinds = [(r["group"], r["kind"]) for r in d["p"]["gantt"]["rows"]]
        self.assertEqual(kinds[0], ("done", "done"))
        self.assertIn(("milestone", "milestone"), kinds)

    def test_a_page_carries_its_data_and_opens_from_disk(self):
        self.program()
        self.init()
        self.ap("project")
        for name in ("index.html", "questions.html"):
            page = self.page(name)
            self.assertNotIn("__DATA__", page)
            self.assertNotIn("__TITLE__", page)
            self.assertNotIn("fetch(", page)
            self.assertIn('charset="utf-8"', page)

    def test_the_page_follows_the_work(self):
        self.program()
        self.ap("init", "--slug", "chan", "--title", "Бот", "--skill-dir", SKILL, "--program", "P02")
        self.dir = os.path.join(self.a, self.state()["dir"])
        self.write("manifest.md", MANIFEST)
        self.write("tickets/01-a.md", ticket("01", "Первый", "R01, R02, R05", "—", ["src/a/"], 1))
        self.ap("tickets")
        self.ap("ticket", "01", "start")
        self.assertEqual(self.page_data()["p"]["currentRun"]["plan"][0]["tickets"][0]["k"], "now")

    def test_a_question_must_stand_on_its_own(self):
        code, out = self.ap("question", "add", "--title", "Только заголовок")
        self.assertNotEqual(code, 0)
        self.assertIn("рекомендация", out)
        self.assertIn("если промолчит", out)

    def test_an_answer_moves_the_question_and_numbers_are_never_reused(self):
        self.program()
        self.init()
        self.ap(*self.QUESTION)
        self.ap("question", "answer", "1", "--by-user", "«ок»")
        code, out = self.ap(*self.QUESTION)
        q = self.page_data("questions.html")
        self.assertEqual([x["id"] for x in q["open"]], [2])
        self.assertEqual(q["resolved"][0]["answer"], "«ок»")

    def test_only_the_owners_words_close_a_question(self):
        self.program()
        self.init()
        self.ap(*self.QUESTION)
        self.assertNotEqual(self.ap("question", "answer", "1")[0], 0)

    def test_the_digest_can_be_answered_without_opening_anything(self):
        self.ap(*self.QUESTION)
        out = self.ap("question", "list")[1]
        for piece in ("Сколько хранить", "О чём: Контекст", "На что соглашаешься: Два года", "Совет: Два года.", "Если промолчишь: Без срока", "«1 ок»"):
            self.assertIn(piece, out)

    def test_a_manual_action_says_why_only_the_owner_can(self):
        self.assertNotEqual(self.ap("manual", "add", "k", "--title", "Договор")[0], 0)
        code, out = self.ap("manual", "add", "k", "--title", "Договор", "--only-you", "подпись", "--why", "нужно", "--step", "подпиши")
        self.assertEqual(code, 0, out)

    def test_lint_catches_what_the_owner_should_not_read(self):
        self.program()
        self.init()
        self.ap("question", "add", "--title", "Закрыть R07 в ветке main", "--about", "см. /Users/me/x", "--agrees", "a",
                "--recommend", "b", "--why", "c", "--silence", "d")
        out = self.ap("project", "lint")[1]
        self.assertIn("код требования", out)
        self.assertIn("слово разработчика", out)
        self.assertIn("путь на диске", out)

    def test_lint_is_quiet_on_plain_words(self):
        self.program()
        self.init()
        self.assertIn("на странице чисто", self.ap("project", "lint")[1])

    def test_an_open_change_holds_the_landing_even_when_the_stage_was_skipped(self):
        self.program()
        self.init()
        self.accept_architecture()
        self.ap("stage", "architecture", "skip", "--note", "архитектура проекта принята")
        self.ap("arch", "delta", "--note", "добавили очередь")
        m = self.module()
        s = self.state()
        self.assertEqual(m.ls_arch_landing(s)[0][:2], "GA")

    def test_repair_tickets_do_not_need_sections(self):
        self.accept_architecture()
        self.init()
        self.write("manifest.md", MANIFEST)
        self.write("tickets/01-a.md", ticket("01", "Первый", "R01, R02, R05", "—", ["src/a/"], 1).replace("**Волна:**", "**Архитектура:** §4\n**Волна:**"))
        self.write("tickets/F1-remont.md", ticket("F1", "Ремонт", "R01", "—", ["src/b/"], 2))
        self.assertNotIn("нет поля Архитектура", self.ap("check-plan")[1])

    def test_a_planning_session_is_marked_from_the_start(self):
        self.init()
        self.ap("arch", "start", "--scope", "project")
        self.assertTrue(self.state()["programPlan"])

    def test_the_program_remembers_mode_and_depth(self):
        self.program(PROGRAM_V2.replace("Параллельно: 1", "Режим: full\nГлубина: deep\nПараллельно: 1"))
        out = self.ap("program")[1]
        self.assertIn("Режим: full", out)
        self.assertIn("Глубина: deep", out)

    def test_more_than_one_lane_is_said_out_loud(self):
        self.program(PROGRAM_V2.replace("Параллельно: 1", "Параллельно: 2"))
        self.assertIn("один прогон на папку", self.ap("program", "check")[1])

    def test_the_questions_page_exists_without_a_program(self):
        self.init()
        code, out = self.ap(*self.QUESTION)
        self.assertEqual(code, 0, out)
        d = self.page_data("questions.html")
        self.assertFalse(d["hasProject"])
        self.assertEqual(len(d["open"]), 1)
        self.assertIn("только страница вопросов", self.ap("project")[1])

    def test_the_headline_of_a_landed_run_does_not_outlive_it(self):
        self.program()
        self.ap("project", "now", "--state", "Сдан первый")
        self.ap("init", "--slug", "chan", "--title", "Бот", "--skill-dir", SKILL, "--program", "P02")
        self.assertIn("Идёт сейчас: Бот", self.page_data()["p"]["now"]["state"])

    def test_the_questions_hero_tells_the_truth_about_urgency(self):
        self.program()
        self.init()
        self.ap(*self.QUESTION, "--urgency", "Закрывает запуск")
        self.assertIn("нельзя выходить к людям", self.page_data("questions.html")["heroNote"])
        self.ap(*self.QUESTION, "--urgency", "Останавливает работу")
        self.assertIn("Работа стоит", self.page_data("questions.html")["heroNote"])

    def test_the_architecture_and_the_ready_made_parts_reach_the_page(self):
        self.program()
        self.init()
        self.accept_architecture()
        with open(os.path.join(self.a, "prior-art.json"), "w", encoding="utf-8") as f:
            json.dump({"capabilities": [{"id": "C1", "name": "Канал", "decision": "adopt", "why": "зрелая", "choice": "a/b"},
                                        {"id": "C2", "name": "Правила", "decision": "build", "why": "наш продукт"}]}, f, ensure_ascii=False)
        self.ap("project")
        d = self.page_data()["p"]
        self.assertTrue(d["arch"]["ok"])
        self.assertEqual(d["arch"]["score"], 9.5)
        self.assertEqual(([x["name"] for x in d["reuse"]["taken"]], [x["name"] for x in d["reuse"]["own"]]), (["Канал"], ["Правила"]))


if __name__ == "__main__":
    unittest.main()
