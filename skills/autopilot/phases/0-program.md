# Phase 0 — A program of several runs

Read when `.autopilot/program.md` exists at preflight or resume, or when Phase 4 finds the work over the T3 ceiling («more — not allowed, split into runs», `phases/4-plan.md`). One run is at most ~36K lines and twelve tickets; a product like «Легко Сказать» — core, LLM layer, stages, Telegram, interview, focus group, operations — is several. **A program is the list of runs with their dependencies, and the rule that a run starts only when the runs it needs have landed.**

## The file

`.autopilot/program.md`, committed with `.autopilot/`, read by people as well as by `ap.py`:

```markdown
# Программа — <проект>

Бриф программы: `.autopilot/program-brief.md`. Каждый прогон — своя папка, свой бриф, свой манифест.

| ID | Прогон | Зависит от | Статус | Папка | Итог |
|----|--------|------------|--------|-------|------|
| P01 | Ядро: автомат, схема БД, миграции, CliChannel | — | landed | `2026-11-10-core` | ядро и CLI-канал есть |
| P02 | LLM-слой: реестр промптов, роутер, кассеты | P01 | in-flight | `2026-11-12-llm` | — |
| P03 | Стадии: обработчики и prompt-таски | P02 | pending | — | — |
| P05 | Блок интервью | P01 | blocked | — | ждёт методику от владельца |
```

- **Statuses** — `pending` · `in-flight` · `landed` · `blocked`. `ap.py` writes `in-flight` (`init --program P02`) and `landed` (`finish`) itself; `blocked` and back to `pending` — `ap.py program P05 block --note "…"` / `program P05 pending`; never by hand in a row `ap.py` owns.
- **One run, one brief.** `program-brief.md` is the owner's whole text, verbatim, like any brief (`phases/1-manifest.md`). Each run's brief is the **verbatim slice** of it that the run delivers, written into the run's own `<дата>-brief.md` with a first line naming the row: «Прогон P02 программы — фрагмент брифа программы, дословно». The run's manifest atomises only its slice; G4 checks only its slice.
- **Dependencies are runs, not tickets**: P03 needs what P02 *landed*, read from P02's `interfaces.md` and `PROGRESS.md` — never from a run still in flight.
- **Cutting the program is your process decision** — the size rules of `phases/4-plan.md` applied one level up: each run a coherent product slice that lands green on its own, the groundwork first. **What goes in a run is not**: whether a capability is wanted at all stays the owner's, as in every brief.

## The top orchestrator

`python3 .autopilot/ap.py program` — works without a `state.js` — prints the next runnable row («следующий: P03 — …»), what waits on what, what is blocked. It is the whole of the top level:

1. **A run lands** → its row is `landed`; the report's last line names the next one: «Следующий прогон программы — P03 «Стадии». Скажи `/autopilot-ls` в новой сессии — продолжу с него».
2. **A new session, not this one.** A run leaves the orchestrator's context at its heaviest; the next run starts fresh. With the owner's standing permission — asked once, like the night task (`phases/5-night.md`) — a one-off scheduled task a few minutes ahead says `/autopilot-ls` in a fresh session; without it, the owner says it.
3. **`/autopilot-ls` with no unfinished run and a program on disk** → the next row: its brief slice into a new dated brief, `init --program P03`, and Phase 1 as usual. No row runnable → say why in one line («P03 ждёт P02, P05 ждёт методику») and stop.
4. **After the last row lands** — one blind check of the whole program against `program-brief.md`, exactly as G4 (`phases/8-final.md`), and one line per drift into the last run's report.

Night runs never start a new run of the program: the night flies the queue of the run in flight (`phases/5-night.md`).
