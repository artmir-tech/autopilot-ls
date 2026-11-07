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

`check-plan` refuses a ticket without one of the five header fields, with a value outside the lists, with `Ночью: да` beside `Внимание: owner`, a `migration` sharing its wave, a non-prompt ticket writing into `prompts/`, and a prompt ticket writing outside `prompts/` and `evals/` — each as a `!` line of gate G3.

## The fork's commands

| Event | Call |
|---|---|
| a retry, before the fresh executor goes out | `ticket 03 retry` — prints `ретрай N: <model> · <effort>`, the rung from the ladder in `phases/5-repair.md`; launch on exactly that. `--model`/`--effort` override it only on the user's word |
| a ticket lands | `ticket 03 done --tests 34/0 --gates "crap 7.4 · dry 0 · mutants 38/41" --base <sha> --commit <sha>` |
| Phase 0, and whenever a `!` about the fork appears | `ls-check` — `docs/standards/ub-mode.md` in the project, `.claude/worktrees/` in `.gitignore`, whether `make gates` exists yet. Not an event: it writes nothing to the log |

## Calibration

After a run, `attempts` and `repairs` by `model` answer the one question the heuristic in `phases/4-plan.md` cannot: which kind of ticket the cheaper model really carries. The final report of the run does not show them; the next plan reads them from the archived `state.js`.
