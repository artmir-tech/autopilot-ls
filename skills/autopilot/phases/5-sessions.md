# Phase 5 — Worker sessions *(экспериментально)*

Read only when `state.js` says `dispatch: sessions` — set with `ap.py set dispatch=sessions` **on the owner's own words** («запускай таски отдельными сессиями»), quoted into the brief's `## Дополнения`. Otherwise tickets fly as subagents (`phases/5-subagents.md`), which is the tested path. Everything in that file still holds — the contract, the zone, steps 2–11 of landing, pacing; this file replaces only *how an executor is started, reached and watched*.

**Why at all:** a worker session has its own context window and its own worktree, the owner can open it, read it and stop it, and the orchestrator's context does not carry the executors' traffic. **What it costs:** every session pays its own start (memory file, skills — tens of K), asks for permissions in its own mode (never above the orchestrator's), and fills the sidebar. Try it on a T2–T3 run by day; never at night.

## Starting a worker

```
start_session({ initiation: "user_asked", context: "fresh", use_worktree: true,
  name: "t03-intake", title: "T03 — приём заявки", model: "<Модель>", effort: "<Усилие>",
  wake_when_done: true, branch_name: "ticket-03",
  background: "<проект, прогон, что уже построено — из interfaces.md, ≥ 80 знаков>",
  prompt: "role: worker · ticket 03\n<то же, что исполнителю-субагенту: пути, зона, команды, трейлеры>\nКонтракт возврата — в <основная копия>/.autopilot/<папка>/status/03.json; последним сообщением — одна строка STATUS." })
```

then `ap.py ticket 03 start --session <id из ответа> --name t03-intake`.

- **`model` and `effort` cannot exceed the orchestrator's** — the app ignores a higher one. An `opus` ticket needs an `opus` orchestrator; if it is not, the ticket flies as a subagent and you say so in one line.
- **Cloud never** (`target: "cloud"`): a cloud worker cannot wake the orchestrator and has no local `.env`, gates or corpus.
- **A start the app refuses** — a turn begun by a scheduled task or another session's message may not start sessions — falls back to a subagent for that ticket, with one line in the log. That is also why the night run never uses this mode.
- At most as many in flight as pacing allows — workers draw on the same 5-hour window.

## Talking to a worker

- **Its report reaches you cut to 400 characters** — so the contract lives in a file: `status/NN.json` in the main checkout, written **only by the worker of that ticket**, never by you and never by another worker: `{ticket, status, worktree, branch, files, tests, gates, redproof, interfaces, requirements, concerns, blockers, log, at}`. No file → the ticket is not finished; ask for it.
- **A дозапрос goes by `SendMessage`** to the worker's session id, its context intact, exactly as in `phases/5-repair.md`. A retry is a new worker; the old one is stopped, not reused.
- **Status of the family** — `list_sessions({linked: true})`; a worker's context — `get_usage({session_id})`. Never poll: a worker that ends its turn wakes you (`wake_when_done`).

## The board and who writes what

| File | Writer | What |
|---|---|---|
| `state.js` | **the orchestrator only**, through `ap.py` | the run, as everywhere |
| `.autopilot/<dir>/board.json` | `ap.py`, on every call while `dispatch: sessions` | per ticket: status, the worker's own status, session id and name, branch, worktree, lease, attempts, model — outside every worker's worktree |
| `.autopilot/<dir>/status/NN.json` | the worker of ticket NN | its contract |
| its worktree and branch | the worker | the code, in small commits |

A lease that ran out (`lease_until`, two hours from the start) with no status file is a stuck worker: look at it once (`list_sessions`), then stop it and treat the ticket as a failure for `phases/5-repair.md`.

## Landing a worker's branch

The same as a subagent's, steps 2–8 of `phases/5-subagents.md`, with the worker's branch: rebase `ticket-NN` onto the main branch, the full check and `make gates` on it, the point review if the ticket has one, `git merge --ff-only`. **A worker never merges, rebases the main branch or pushes**, and never starts a run: `role: worker` in its prompt makes `/autopilot-ls` a no-op for it (`phases/0-preflight.md`). When the ticket is finished, archive the worker's session only if the owner agreed to that once; otherwise leave it for them.
