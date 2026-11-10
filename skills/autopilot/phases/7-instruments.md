# Instruments — the fork's data in `state.js`

Read when the run first writes one of the blocks below: in Phase 4 before `ap.py tickets`, and when `phases/5-night.md`, the pacing rules of `phases/5-subagents.md`, `phases/5-sessions.md` or `phases/0-program.md` say so. Everything here is written by `ap.py` — **never by hand**, like the rest of `state.js` (`phases/0-instruments.md`). The dashboard does not show these blocks yet; they are data for the morning report, for the next plan and for a later dashboard.

## Tickets — what `ap.py tickets` reads from the header

| `state.js` | Ticket header | Values | Written by |
|---|---|---|---|
| `tickets[].type` | `**Тип:**` | `code` · `prompt` · `migration` · `e2e` · `infra` | `tickets` |
| `tickets[].model` | `**Модель:**` | `opus` · `sonnet` · `haiku` — the plan, never rewritten | `tickets` |
| `tickets[].effort` | `**Усилие:**` | `low` · `medium` · `high` · `xhigh` | `tickets` |
| `tickets[].attention` | `**Внимание:**` | `none` · `review` · `owner` | `tickets` |
| `tickets[].night_ok` | `**Ночью:**` | `да` → `true` · `нет` → `false` | `tickets` |
| `tickets[].attempts` | — | `[{model, effort, at}]` — the rung each launch actually flew on | `ticket NN start`, `ticket NN retry` |
| `tickets[].base` | — | where the main branch stood before the ticket landed | `ticket NN done --base` |
| `tickets[].gates` | — | the gates' summary as step 6 printed it | `ticket NN done --gates` |
| `tickets[].status` = `awaiting_owner` | — | landed, reviewed, waiting for the owner's word on its review page | `ticket NN await --page …` |
| `tickets[].page` · `approvedByUser` | — | the review page's path; the owner's words that approved it | `ticket NN await`, `ticket NN done --by-user` |

`check-plan` refuses a ticket without one of the five header fields, with a value outside the lists, with `Ночью: да` beside `Внимание: owner`, a `migration` sharing its wave, a non-prompt ticket writing into `prompts/`, a prompt ticket writing outside `prompts/` and `evals/`, and a ticket whose text shrinks the task without the owner's words (`phases/4-plan.md`) — each as a `!` line of gate G3.

## The fork's commands

| Event | Call |
|---|---|
| a retry, before the fresh executor goes out | `ticket 03 retry` — prints `ретрай N: <model> · <effort>`, the rung from the ladder in `phases/5-repair.md`; launch on exactly that. `--model`/`--effort` override it only on the user's word |
| a ticket lands | `ticket 03 done --tests 34/0 --gates "crap 7.4 · dry 0 · mutants 38/41" --base <sha> --commit <sha>` |
| a prompt ticket reviewed clean, its page written | `ticket 03 await --page prompt-reviews/03-coach.html --gates "<EVAL>"` — `done` is then refused without `--by-user "«их слова»"`; their comments are `ticket 03 repair --note "…"` |
| Phase 0, and whenever a `!` about the fork appears | `ls-check` — the `ub-mode` skill is installed, `.claude/worktrees/` in `.gitignore`, whether `make gates` exists yet. Not an event: it writes nothing to the log |

## Commands of the whole project — no `state.js` needed

| Event | Call |
|---|---|
| prior art written | `scout verify`, then `scout check` — gate GS (`phases/2a-scout.md`) |
| an audit of the architecture written | `arch round --file <NN.json> [--kind confirm\|delta\|as-built]` — gate GA; `arch start`, `arch status`, `arch judge --file`, `arch continue --by-user`, `arch delta --note`, `arch waive --by-user` (`phases/2b-architecture.md`) |
| the master plan written or changed | `program check`; closing the planning run: `program plan --result` (`phases/0-program.md`) |
| the owner's page | `project` builds it; `project now · change · spend · next-list · url · run · lint` |
| a question or a manual action | `question add · answer · list`, `manual add · done` |

## The night queue — `queue` and `night`

| `state.js` | What | Written by |
|---|---|---|
| `queue.tickets` | ids in launch order: `night_ok`, pending, parents landed or ahead in the queue | `queue`, `night start` |
| `queue.skipped` | `[{id, why}]` — every other unfinished ticket and why it is not tonight: «Ночью: нет», «ждёт 03», «упал», the owner's note | `queue` |
| `queue.dropped` | `{id: why}` — taken out by hand for the night, kept across rebuilds | `queue drop` |
| `night.status` | `running` → `stopped` (first `failed`, or the pacing stop) → `finished` | `night start · stop · end`, `ticket … fail` |
| `night.done` · `night.failed` · `night.awaiting` | what landed, what failed, which prompt tickets wait for the owner's look | `ticket … done · fail · await` while the night runs |
| `night.stop` · `night.report` | why it stopped; the morning report's file name | `night stop`, `ticket … fail`, `night end` |
| `night.resume_at` | while `paused`: when the window resets + 5 minutes | `pacing`, at 85 % |
| `night.date` · `startedAt` · `endedAt` | the night's bounds | `night start`, `night end` |

| Event | Call |
|---|---|
| show what would fly tonight | `queue` |
| a ticket needs the owner at night | `queue drop 07 --note "что нужно от владельца"` — its dependents leave with it |
| the night begins | `night start` — rebuilds the queue; until `night end`, `ticket … start · retry` refuse anything outside it, and refuse everything once a ticket failed |
| the pacing stop at night | `night stop --note "окно 85 %"` |
| the morning report is written | `night end --report night-2026-11-08.md` |

**«Ночная очередь» on a dashboard** would show `queue.tickets` in order, `queue.skipped` with reasons, and `night` as «идёт · остановлена: <почему> · закончена» with done and failed — the morning report is the same data in words.

## The window — `pacing`

| `state.js` → `pacing` | What | Written by |
|---|---|---|
| `window_used_pct` · `window_reset_at` | the 5-hour window: percent used, when it resets | `pacing --window --reset` |
| `weekly_used_pct` · `weekly_reset_at` | the weekly limit, percent used, when it resets — the pacing basis when `get_usage` reports no 5-hour window | `pacing --weekly --weekly-reset` |
| `reserve_pct` | kept back for reviews and repairs of what flies — 15 unless the owner says otherwise | `pacing --reserve` |
| `night_weekly_max_pct` | the most of the weekly limit one night may spend — the owner's number, 15 unset | `pacing --night-weekly-max-pct` |
| `est_cost_by_ticket` | `{id: percent of the window}` — measured or corrected estimates; a ticket without one is estimated by its rung | `pacing --est 03=8` |
| `source` · `at` | `get_usage` or `measure-run`; when it was read | `pacing --source` |
| `night.weekly_at_start` | the weekly percent when the night began — what the night's share is counted from | `night start` |

`ap.py pacing` prints the verdict — in flight at most 3 / 2 / none, the room for one ticket, and at 85 % the time to continue; `pacing check 03 05` answers per ticket. At night it also pauses the night at 85 % of the window and stops it at the weekly share. **Once `pacing` has numbers, `ticket … start · retry` refuse** a launch at 85 % or more, and a `start` that would put more tickets in flight (`in-progress`, `repair`) than the window allows — stale numbers are fixed by a fresh `get_usage` and `pacing`, never by going around the refusal.

**«Окно лимитов» on a dashboard** would be two gauges — the window with its reset time, the week with the night's share marked — and the in-flight cap the verdict gives; the morning report's «Цифры» line is the same data in words.

## Worker sessions — `dispatch`, `tickets[].session`, `board.json`

| `state.js` | What | Written by |
|---|---|---|
| `dispatch` | `sessions` — executors start as worker sessions (`phases/5-sessions.md`); absent — subagents | `set dispatch=sessions`, on the owner's words |
| `tickets[].session` | `{id, name, lease_until}` — the worker flying the ticket | `ticket 03 start --session <id> --name t03-intake` |

While `dispatch` is `sessions`, every `ap.py` call also rewrites `.autopilot/<dir>/board.json` from `state.js` and the workers' `status/NN.json`. Nobody edits it by hand; workers never write it.

## The program — `program` and `.autopilot/program.md`

| Where | What | Written by |
|---|---|---|
| `state.js` → `program` | the row this run delivers, `P02` | `init --program P02` |
| `program.md`, the row's status | `in-flight` at `init`, `landed` at `finish`; `blocked` / `pending` by command | `init`, `finish`, `program P05 block --note "…"`, `program P05 pending` |
| `program.md`, «Папка» · «Итог» | the run's directory; its `--result` | `init`, `finish` |

`ap.py program` prints the next runnable row and what waits; it reads no `state.js` and writes nothing.

## The e2e result — `e2e`

`state.js` → `e2e`: `{dialogues, passed, usd, regressions, at}` of the last L2 run, from `ap.py e2e dialogues=12 passed=11 usd=3.4 --regression "…"` (`phases/8a-e2e.md`).

## The morning report — the same data in words

`night-<YYYY-MM-DD>.md` (`phases/5-night.md`) is written from `state.js`, re-read at the end of the night, never from memory of it:

| Раздел | From |
|---|---|
| Сделано | `night.done` → each ticket's title, `tests`, `gates` — what became possible, in the user's words |
| Упало | `night.failed` → the ticket's `concerns`; `night.stop`; the dependents left untouched (`queue.skipped` «ждёт …») |
| Нужно от тебя | `night.awaiting` → each ticket's `page`, first («открой страницу обзора и ответь»); `queue.dropped` and `queue.skipped` with the owner's reasons; tickets with `attention: owner` still pending; `attention: review` landed tonight («посмотри»); a `waiting` left open |
| Цифры | `pacing.window_used_pct` at start and end, `pacing.weekly_used_pct − night.weekly_at_start` against `night_weekly_max_pct`, counts of done / failed / waiting; `e2e` if L2 ran |

Words from the table in `SKILL.md`: «Окно», «Проверки качества», «Прогон диалогов» — never `pacing`, gates or L2.

## Calibration

After a run, `attempts` and `repairs` by `model` answer the one question the heuristic in `phases/4-plan.md` cannot: which kind of ticket the cheaper model really carries. The final report of the run does not show them; the next plan reads them from the archived `state.js`.
