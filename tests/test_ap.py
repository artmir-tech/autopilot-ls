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


class Run(unittest.TestCase):
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
    def test_init_creates_run(self):
        self.init()
        s = self.state()
        self.assertTrue(re.match(r"\d{4}-\d{2}-\d{2}-repair-bot--wip$", s["dir"]))
        self.assertTrue(os.path.isdir(os.path.join(self.dir, "tickets")))
        self.assertEqual([x["status"] for x in s["stages"]], ["active"] + ["pending"] * 7)
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
        self.ap("stage", "spec")
        g = self.state()["gates"]["G1"]
        self.assertEqual((g["ok"], g["open"], g["total"]), (False, 1, 4))
        self.write("manifest.md", MANIFEST)
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
        code, out = self.ap("ls-check")
        self.assertEqual(code, 0, out)
        self.assertIn("! нет docs/standards/ub-mode.md", out)
        self.assertIn("! .gitignore без .claude/worktrees/", out)
        os.makedirs(os.path.join(self.root, "docs", "standards"))
        with open(os.path.join(self.root, "docs", "standards", "ub-mode.md"), "w") as f:
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


if __name__ == "__main__":
    unittest.main()
