# Phase 5 — Build

`ap.py stage build`. Where the code gets written. **Identical in all four modes, and hands-free**: manual buys control over *what* gets built, not over each edit.

## One ticket, one subagent, one fresh context

Never two tickets in one context — accumulated context is what makes long sessions start breaking what used to work. At T0 the one ticket goes to one executor like any other.

**You dispatch; you do not build.** Your keyboard reaches `.autopilot/**`, the memory files, `.gitignore`, `.env.example`, and git (`add`, `commit`, `status`, `--stat`, `rebase` and `merge --ff-only` of an executor's branch, `worktree remove` — never the diff). Every other file is written by someone whose context dies with the ticket. This is rule 5, and it loses to the two arguments that always arrive — «тут две строки» and «исполнитель не смог, доделаю сам»: a diff you read at ticket 02 is still in your context at ticket 08, and your context is the one that is never refreshed.

## What an executor gets — paths, not contents

| | |
|---|---|
| `prompts/executor.md` | by path (`skillDir` in `state.js`), **required reading before the first edit** — the testing contract, the code standards, what is never allowed, the return format |
| the `ub-mode` skill | for `Тип: code`, `migration`, `e2e`, `infra`: the executor loads it itself with the Skill tool, first thing — the clean-code standard `prompts/executor.md` makes binding, with its two exceptions. The launch prompt says so in one line. A contract without `STANDARD: ub-mode` is a дозапрос (`phases/5-repair.md`): code written from memory of the standard is not code written to it. A prompt ticket does not load it |
| the main checkout | its absolute path: the executor works in its own worktree, but reads `.autopilot/<dir>/` **from the main checkout** — `interfaces.md` grows during the build and is not committed until the end, so the worktree's copy is stale |
| its ticket | by path; it already carries the verbatim brief quotes |
| the spec sections the ticket names | `spec.md` by path **and section headings** — not the whole spec, not pasted |
| `interfaces.md` | by path, read first |
| the architecture sections the ticket names | `.autopilot/architecture.md` by path and the section numbers from `**Архитектура:**` — not the whole document |
| `notes.md` | by path, in an existing codebase |
| `reference.md` | by path, when the ticket builds something the user will look at |
| the check command, how to run one test file, the gates command | from `interfaces.md` — so it does not derive them |
| its log file | `.autopilot/<dir>/logs/NN.md` **inside its worktree** — the harness lets an executor write nowhere else; ub-mode's log goes there uncommitted, the contract carries only the path, and you move it at landing |
| its zone, and what it must not touch | zones of tickets flying beside it included |
| credentials | variable **names**, never a value |

A subagent has a filesystem; pasting what it can read writes the same words twice into the bill, and the second copy stays in your context for the rest of the run. Every rule the executor must follow travels in its prompt or in `prompts/executor.md` — a rule that lives only in a phase file does not exist for the one writing the code.

**The model, the effort and the worktree go into the call.** The ticket's `Модель` and `Усилие` are passed as they are — the skill requires it, which is what the Agent tool's `effort` asks for — and every executor gets its own git worktree:

```
Agent({ description: "T03 приём заявки", subagent_type: "general-purpose",
        model: "sonnet", effort: "medium", isolation: "worktree",
        prompt: "<пути, зона, команды, контракт — таблица выше>" })
```

A relaunch after a failure takes the rung `phases/5-repair.md` names, not the ticket's. `ap.py ticket NN start` records the model and effort the ticket flies on; a harness without a model, effort or worktree choice ignores the field silently — and without worktrees the run falls back to the shared tree, below.

**A worktree per executor.** Parallel executors in one checkout break each other's checks and leak into each other's commits; with `isolation: "worktree"` each writes only its own copy, and the main checkout holds nothing but landed tickets. The worktree is a fresh checkout: no `.venv`, no `node_modules`, no `.env` — the executor installs dependencies there first (the command is in `interfaces.md`), and tests never need `.env` (cassettes, `phases/8a-e2e.md`). Worktrees live under `.claude/worktrees/`, which `.gitignore` carries from Phase 0. **The harness cuts them from the repository the session runs in** — so the orchestrator's session must sit at the project's root: a session opened elsewhere moves there first (in the Claude desktop app, by changing the session's folder) and never `cd`s out of it; edits to anything outside the project go by absolute path. The executor names its worktree and branch in the contract (`WORKTREE:`), so landing never depends on what the harness prints.

**Dependencies.** Ticket 01 installs everything the spec's «Решения по реализации» names. A later ticket that needs something else returns `BLOCKED` with its name; if it fits a decision already made, add it to «Решения», relaunch that ticket with permission to install exactly that — the manifest and lock files join its commit — and fly nothing else that installs at the same time.

## Waves

Phase 4 gave every ticket a wave and a zone. **Launch a whole wave in one message, one subagent call per ticket, in the background** — two calls in two messages run one after the other, and the parallelism computed in the plan is thrown away in the delivery.

- **At most three in flight.** A wave of five goes out as three, then two. A point reviewer reads a commit and writes nothing — it does not count against the three.
- **Zones disjoint** — checked again at launch; same files → serialise. When in doubt, serialise.
- **A wave is not a barrier.** When a ticket returns, first launch the next ticket whose dependencies are all committed, then process the one that landed.
- **A dependent never launches on an uncommitted parent.**
- `ap.py ticket 02 03 start` goes **before** the launch — one call for the whole wave, **in the same message as the Agent calls**: Bash first, the launches after it.
- **One event, one message.** Every call of yours re-reads your whole context — at 200K, one call costs about as much as a small subagent's first steps. What one event needs goes out together: the `ap.py` mark, the commit, the next launch, the line to the user. Never a call that only marks, then a call that only launches.
- **Waiting for the wave is ending your turn** — a background subagent wakes you when it returns. Never spawn an agent, or run a loop, just to wait.
- **The pacing rules below cap all of this** — «at most three» is the ceiling of a fresh window, not a right.

## Pacing — the 5-hour window

The subscription's limits are the run's real budget: a run that hits the 5-hour wall mid-wave leaves tickets half-built until the window resets. **Before every launch and after every landing**, read the limits and let `ap.py` decide — arithmetic, not mood:

1. **`mcp__ccd_session_mgmt__get_usage`** — the 5-hour window (percent used, reset time) and the weekly limit. Load it with ToolSearch once if it is only listed as deferred.
2. **`ap.py pacing --window 41 --reset <ISO> --weekly 22 --source get_usage`** — writes `state.js` → `pacing` and prints the verdict; `ap.py pacing check 03 05` says, per ticket, whether its estimate fits.
3. **Launch only what the verdict allows** — `ap.py ticket … start` refuses the rest:
   - a ticket starts only if its estimate is **≤ 0.8 of the room left** — `100 − window − reserve`, the reserve **15 %** for reviews and repairs of what is already flying;
   - the window **over 60 % — at most two in flight**, not three;
   - **at 85 % — no new launches**: let the flying tickets land (or reset them at the frontier, `phases/0-resume.md`), `ap.py` once more so the dashboard holds, and **a one-off scheduled task «продолжить» at the reset time + 5 minutes** — `create_scheduled_task({fireAt: <то, что напечатал ap.py>, prompt: "/autopilot-ls\nПроект: <абсолютный путь>. Окно лимитов сброшено — продолжи прогон с фронтира. Если команда не сработала — прочитай ~/.claude/skills/autopilot-ls/SKILL.md и следуй ему."})`, only with the owner's standing permission (`phases/5-night.md`, «Starting it»); without it, one line to the user with the time to say `/autopilot-ls`.
   - **Big tickets go first in a fresh window** — an `opus · high` core of a T3 run at 10 % used, not at 70 %.

**Estimates** are percent of the 5-hour window per ticket, by rung until measured: `haiku·low` 2 · `sonnet·medium` 5 · `opus·high` 10 · `opus·xhigh` 14. They are guesses: after a landing, the window's rise across the ticket goes into `ap.py pacing --est NN=<факт>` for the tickets still to come like it, and after two or three runs the defaults in `ap.py` are rewritten from `state.js`.

**`get_usage` reports no 5-hour window** — some plans show only the weekly limits (all models, and per model). Then pass only `--weekly` (and `--weekly-reset`): `ap.py` paces by the week instead — over 80 % two in flight, at 95 % no new launches and «продолжить» at the weekly reset + 5 minutes; at night the weekly stop ends the night rather than pausing it. Estimates stay in percent of a 5-hour window, which makes them conservative against the week.

**`get_usage` says `not_applicable`** (an API key, not a subscription) — there is no window: the window rules are off, only the money caps (`EVAL_MAX_USD`, `E2E_MAX_USD`) and the night's share hold, and `python3 <skillDir>/tools/measure-run.py <проект>` after each ticket gives the spend in normalised units for the report. **`unavailable`** — ask once more; still nothing → act as at 61 %: two in flight, and a line in the log.

**Without worktrees — the fallback, not the plan.** A harness that cannot isolate puts parallel executors in one checkout. Then executors do not commit at all — ub-mode's «Commit often» waits for a worktree, and the prompt says so; each touches only its zone (and `.env.example`), you commit exactly the contract's `FILES` in the main checkout (step 3 without the rebase, step 8 without the merge, `--base` still recorded), and a check that fails **only in files of zones still being written** is a neighbour's unfinished work, not this ticket's defect: the ticket may land on its own tests green, and the full check runs again when the neighbour lands. `ap.py check` refuses a checkout holding someone else's uncommitted work, so such a run starts with `init --evidence off`, and the count stays yours to write with `--tests`.

## The return contract

Required in the prompt, not suggested — without it you cannot update anything:

```
STATUS: DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
WORKTREE: <абсолютный путь> · <ветка>
FILES: созданные и изменённые — только пути
TESTS: команда проверки → результат и сколько было до тебя (`npm run check` → 34 passed, было 21)
STANDARD: ub-mode загружен скиллом
GATES: crap max 7.4 · dry 0 пар ≥0.8 · mutants 38/41 убито, выжившие: <имена>
REDPROOF: новый тест → чем он падал до кода (одна строка на тест, до пяти)
INTERFACES: публичные сигнатуры, схемы, форматы событий, которые ты выставил
REQUIREMENTS: R01 done | R01.1 placeholder — <чего не хватило>
CONCERNS: что сделано с оговоркой и почему
BLOCKERS: чего не хватило (зависимость, решение, доступ)
LOG: .autopilot/<папка>/logs/NN.md
```

**No more than 25 lines, no code, no diffs, no account of the work.** A block longer than that is not read: ask for it again in one line — an essay skimmed once is re-read on every remaining turn of your context.

## After each ticket

In this order:

1. **Read the contract and its status.** No block → the ticket is not finished; ask for it. `BLOCKED` or `NEEDS_CONTEXT` → `phases/5-repair.md` now. A `CONCERNS` line saying the plan does not hold — a data model, an interface, two requirements colliding — is the build contradicting the plan: `phases/5-repair.md` too. Two `NEEDS_CONTEXT` in one run mean the tickets are too thin across the board.

   **`DONE_WITH_CONCERNS` is a `DONE` with entries in the ledger, not a repair.** The ticket goes through every step below like a `DONE`; each `CONCERNS` line becomes `ap.py add concerns "T03 · <файл:строка> — …"` in step 10, and the whole-branch review confirms or drops it. A concern never blocks the commit by itself. Two exceptions, both already routed: a concern that one of the ticket's own requirements is not fully done → point review (step 9); a concern that the plan does not hold → `phases/5-repair.md`.
2. **Nothing outside the zone, nothing left behind.** Everything the branch changed — `git -C "$WT" diff --name-only "$MAIN"...HEAD` and `git -C "$WT" status --porcelain` — lies inside this ticket's zone or is `.env.example`; the one untracked path allowed outside it is the executor's log, `.autopilot/<dir>/logs/NN.md`, which you move into the main checkout now — `mkdir -p .autopilot/<dir>/logs && mv "$WT/.autopilot/<dir>/logs/NN.md" .autopilot/<dir>/logs/`; a path outside it is a дозапрос: put it back or say why it had to change. A changed path inside the zone that `FILES` does not name is a дозапрос too — the contract is how the next tickets learn what exists. **A changed dependency manifest** (`pyproject.toml`, `package.json`, a lock file) gets one more look: a dependency or build tool that «Решения по реализации» does not name is the executor's `BLOCKED` it did not return — if it fits a decision already made, amend «Решения» and add a `D##` row saying what the build proved; if it is a new decision, a дозапрос to take it out.
3. **Close the branch — exactly `FILES`, never `-A`.** The executor commits as it goes, in small commits on its own branch (ub-mode, «Commit and Push»); whatever it left uncommitted you commit by name, then bring the branch up to the main one:

   ```bash
   WT=<путь из WORKTREE>; BR=<ветка из WORKTREE>; MAIN=$(git branch --show-current); BASE=$(git rev-parse --short HEAD)
   { git -C "$WT" diff --quiet HEAD && [ -z "$(git -C "$WT" ls-files -o --exclude-standard)" ] \
     || { git -C "$WT" add -- <незакоммиченные из FILES> && git -C "$WT" commit -qm "T03: остаток" \
          --trailer "Autopilot-Run: 2026-10-10-repair-bot" --trailer "Requirements: R01, R02" -- <те же пути>; }; } \
     && git -C "$WT" rebase -q "$MAIN"
   ```

   Every commit of the branch carries the two trailers — the executor got them in its prompt. A rebase conflict means two tickets wrote one file — a plan defect: `git -C "$WT" rebase --abort`, then `phases/5-repair.md`.
4. **Append its `INTERFACES` to `interfaces.md`** — you, never the executors; parallel writers collide. Two returns claiming one interface is a plan defect: keep the one that fits and re-cut the other.
5. **Run the check — the script runs it, not you**: `python3 .autopilot/ap.py check 03 --cwd "$WT"`. It refuses uncommitted code, runs `checkCmd` in the worktree, prints the last 30 lines, and writes the result with a fingerprint of the code to `.autopilot/<dir>/checks/03.json`; red exits non-zero. It touches nothing else, so tickets may be checked side by side, and a suite that may outrun the shell's timeout goes in the background. **Read what it prints before anything else happens** — green or red, the names of what failed, and the count. Compare the count with the contract: a `DONE` that added criteria and no tests is a дозапрос, and a suite reporting zero tests is red however it exits.
6. **Then the gates**, on the same tree: `(cd "$WT" && make gates CHANGED=1 BASE="$BASE" 2>&1 | tail -15)`. **One at a time and only on changed files**: two tickets landing together run their gates one after the other, never side by side; the mutator gets at most `MUTATE_WORKERS` workers (default: the number of cores; `LS_GATES_JOBS` is the same knob) and waits while the machine has more than 8 pytest processes or another mutator is running — the `gates-wait` target of `standards/gates.md` does it, counting with `while [ "$(pgrep -f pytest | wc -l | tr -d ' ')" -gt 8 ]; do sleep 20; done`, since macOS `pgrep` has no `-c`. A hot machine makes gates slow, never optional. A red gate — CRAP ≥ 10, a duplicate pair ≥ 0.8, a surviving mutant — **is `BLOCKING`**: it goes back as a дозапрос with the gate's lines verbatim, like a red test (a red build, typecheck or lint already is — they are in the check). Gates that disagree with the contract's `GATES` line are a дозапрос too: the executor reported a run it did not do. Until a ticket has built `make gates` (ticket 01 or the first `infra` ticket, to `standards/gates.md` in the skill), this step is skipped with one line in the log; after it, never.
7. **Red check or red gate → `phases/5-repair.md`.** Nothing lands on red, and nothing is repaired by you. The executor repairs in its own worktree and commits the fix on its branch; then steps 2–6 again.
8. **Land and record — one call:**

   ```bash
   git merge -q --ff-only "$BR" \
     && python3 .autopilot/ap.py ticket 03 done --gates "crap 7.4 · dry 0 · mutants 38/41" \
        --base "$BASE" --commit "$(git rev-parse --short HEAD)"
   ```

   **`done` without `--commit` is refused, and git refusing to merge is never worked around** — `index.lock`, `Permission denied`, a sandbox error: that is the machine, so `phases/5-repair.md`, «Fail early». The `&&` stays: a ticket is done when its commits are in the main branch. `--ff-only` refused means the main branch moved since step 3: rebase again, steps 5–6 again, then land. Never a merge commit, never a squash.

   **A ticket lands as one contiguous series**: `--base` is where the main branch stood before it, `--commit` its last commit, and `git diff <base>..<commit>` is the whole ticket — what the point reviewer reads and what a rollback undoes. `--gates` is what step 6 actually printed. The test count comes from the record of step 5, and **`done` is refused without a green record of exactly this code**: a rebase after the check means checking again, and typing the count by hand is refused too. Only a machine fault may skip it, in the owner's words: `--no-check --by-user "«…»"`. `--placeholder R05` for each row the contract reports as a stub. **The trailers make the history searchable after the run is gone**: `Autopilot-Run` is `dir` without `--wip` (ticket numbers restart every run, so `T03` alone names several tickets), `Requirements` the ticket's rows. `git log --grep="R02"` then finds every change a requirement ever caused.

   The worktree stays while a point review or its repair may still need the executor; when the ticket is finished — `git worktree remove "$WT" && git branch -q -d "$BR"`.
9. **Point review, if the ticket says `Ревью: да`**, or the contract reports one of its requirements as not done: `ap.py ticket NN review`, the reviewer in the background, and straight on to the next step and the next wave (`phases/6-review.md`). Its `BLOCKING` lines, when they come, go to `phases/5-repair.md`.
10. **The ledger.** Each stub the contract names → `ap.py add debt.placeholders`; each new variable → `add debt.emptyEnv NAME`; each `A##` that reached the code → `add additions`; each `CONCERNS` line → `add concerns`. Project memory only if something was discovered (`phases/9-memory.md`, Moment 2) — most tickets add nothing.
11. **One plain line to the user**: «Бот принимает заявки — 3 из 8 готово».

**Two tickets returning together are processed one at a time**, each through the whole list: one commit each, a check after each — otherwise a red has two possible authors.

## When the build is over

Every ticket is `done`, `awaiting_owner` (landed, its review page sent — `phases/5-prompts.md`), or `failed` with its dependents named to the user as waiting — point reviews included: none still running, every repair they asked for landed. An awaiting ticket does not hold the branch review; `finish` waits for it. Then `ap.py stage review` and `phases/6-review.md` — the whole-branch review.
