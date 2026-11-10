# Phase 4 — Plan

`ap.py stage plan`. Cut the spec into tickets, each built by its own subagent in a fresh context.

**Every ticket boundary is a cold start** — read the interfaces, explore the code, find the commands: 60–80K tokens of context in a new repo, well over 100K in a large existing one, and a dozen steps before a line is written, plus the orchestrator's own turns to launch and land it. **Fewer, denser tickets beat more, thinner ones** — but only down to what one context can hold.

## Size — read from the volume of code, never from the length of the spec

**One executor builds about 3,000 lines** — changed lines, tests included. That is where its context gets heavy: every step re-reads all of it from the cache, so each step costs more than the last. Measured: an 11-ticket run of ~29K lines ended its executors at 300–420K; a single dialogue of ~1,300 lines in a large existing codebase used two thirds of its window.

**Estimate the volume first**, from the spec and, in existing code, from `notes.md`: how many screens, endpoints, tables, flows, and how much of the existing code each one changes. One line to yourself — «~8K строк: чат ~3K, приглашения ~2K, лимиты ~1,5K, остальное ~1,5K» — then:

| Volume | Tickets | Tier |
|---|---|---|
| **up to ~3K lines** | **one** — one executor gets the whole spec and builds it in one fresh context, start to finish. No waves, no point review | **T0** |
| ~3–6K | 2 | **T1** |
| ~6–18K | 3–6, one per ~3K | **T2** |
| ~18–36K | 7–12, one per ~3K | **T3** |
| more | **not allowed** — split into runs: `phases/0-program.md` | |

**T0 is the default for a list of edits in existing code** — eighteen fixes across a codebase are usually under 3K lines, however many files they touch. The executor works through them in one context, like a single dialogue, and the whole-branch review checks the result.

A `deep` spec for a landing page is a long document about one page: still T0. State the volume, tier and count in one line to the user; `ap.py set tier=T2`.

## How to cut

- **Each ticket is a narrow but complete path through every layer it touches** — data, logic, interface, tests. When it lands, something works end to end that did not before.
- **No ticket only checks.** «Подтвердить готовность», «прогнать полную проверку», «доказать, что сборка работает перед установкой» build nothing, and «всё проходит» has no finish line: every run finds the next timeout, and the executor repairs it as a defect, round after round. Checking is already three steps of the flight — the point review, the whole-branch review, the blind acceptance — and the check before an irreversible step is a question: `ap.py ask action` with what was verified, not a ticket. A ticket's tests prove *its own* criteria, never «everything».
- **The shell, the schema, the shared primitives are ticket 01, alone.** Nothing parallelises with it.
- Groundwork that makes later tickets easy goes early. Tickets closing `R` go before tickets closing only `A`.
- Number from `01` in dependency order; each ticket names what it depends on.
- **The size test.** Merge neighbours that together stay under ~3K lines, even ones that would fly side by side — that trades a little clock time for a whole cold start. Split only a ticket that would run past ~3K lines, or one with a long debugging loop ahead of it — an unfamiliar integration.
- **The payback test:** would its executor spend more flying in than building? Merge it into its neighbour. **The neighbour test:** under three acceptance criteria and the same files as an adjacent ticket? It is a checklist item there.
- **Prompt tickets are cut by stage, not by slice.** For `Тип: prompt` the vertical slice does not apply — a prompt ticket changes one stage's prompt (or two tightly coupled ones) and its eval cases, nothing else; the code that calls the stage is a code ticket. Size is counted in stages and cases, not lines: one ticket per stage; merge two stages when each has under about five cases to write. Seam tests become **eval cases on the stage's contract**, and the ticket's check is `make cases STAGE=<stage>` (`phases/5-prompts.md`). Its criteria are behaviours on cases — «на кейсе coach-007 коуч задаёт ровно один вопрос», never «промпт стал лучше».
- **The merge pass**, mandatory, before any file is written: merge adjacent tickets on the same files, thin tickets with a natural parent, and chains where A alone demos nothing. A draft of 12 tickets for ~18K lines was T2 cut too thin. A wide change below is the one chain the merge pass leaves alone.

## A wide change — new beside old

In existing code a requirement can change **one shared thing that many zones use**: rename a field, change the type of money, split a name, swap a library. A vertical slice never turns green on it — the first ticket changes the shared thing, every zone it did not touch breaks, and the check stays red. One ticket for all of it overflows its executor. Cut it in three steps, each green on its own:

1. **Expand** — the new thing appears **next to** the old one, and the old one keeps working: both fields, with the data copied and kept in sync; the new function, with the old one delegating to it. `Ревью: да — фундамент`, `Модель: opus`, `Усилие: high`.
2. **Migrate** — one ticket per zone moves its callers to the new thing. The old one is still there, so the zones not yet moved stay green; tickets on different zones fly in one wave. Criterion: «в `<зона>` не осталось обращений к `<старое>`».
3. **Contract** — once nothing calls the old thing, it is removed. Dropping a column with user data in it is `Ревью: да — удаление данных`.

Every ticket of the chain carries the same requirement. It applies when the change crosses more zones than one ticket owns; a shared thing used in one zone is an ordinary ticket. In a project built from scratch there is nothing to migrate — this never comes up.

## Waves and zones

**`wave = 1 + max(wave of what it depends on)`**, no dependencies → wave 1. Then **split each wave by zones**: two tickets writing the same files cannot fly together — the later one moves to the next wave. Every ticket names its **zone** — the directories and modules it owns, tests included. With an accepted architecture zones follow its components, and every ticket except a prompt ticket names its sections in `**Архитектура:**`: `check-plan` refuses one that does not. Waves are *discovered* in the dependency graph, never manufactured by splitting a ticket; a wave of one is a normal answer. A wave number, once written, is not renumbered — a real re-cut is said to the user in a line.

## Type, review, model, effort, attention — decided per ticket, here

**Type** — what kind of work the ticket is. It decides which rules apply to it, so it is never left out:

| `Тип:` | What it builds | What changes for it |
|---|---|---|
| `code` | the product's code and its tests | everything in this file, as written |
| `prompt` | prompt files under `prompts/**`, their eval cases, the registry | `phases/5-prompts.md` at launch; no vertical slice; evals instead of seam tests (below) |
| `migration` | a schema change under `migrations/` and the code that reads the new shape | **a wave of one ticket**, always (below) |
| `e2e` | the e2e harness: the CLI channel, the replay corpus, rubrics, cassettes | live models only behind the `E2E_MAX_USD` cap (`phases/8a-e2e.md`) |
| `infra` | `Makefile`, the check command, `make gates`, CI, scripts | never a deploy — that is an action, not a ticket |

**`Тип: migration` is always a wave of one ticket** — the same reason nothing parallelises with ticket 01: every later ticket reads the shape it writes. Its zone is `migrations/` plus the repository code of the tables it changes; two migration tickets never share a wave. Its criteria: the migration runs up on a copy of the fixture database; a second run changes nothing (ub-mode «Make Operations Idempotent»); down exists, or the ticket says «необратимо» in words; the repository tests pass on the new schema. In SQLite a column change is «create the new table → copy → rename», never an `ALTER` SQLite does not have. **Applying a migration to the production database is not part of any ticket** — it is an outward-facing action, rule 4: `ap.py ask action --note "миграция NN на прод-БД"`, and only on the user's yes.

**Attention** — whether the owner, not a subagent, has to look:

- `none` — nobody needs to. Most tickets.
- `review` — it lands without the owner, but its result goes into «нужно от тебя» as «посмотри»: a text the user's users will read, a tone, a prompt's behaviour on real cases.
- `owner` — it cannot be built without a decision only the owner can make: a methodical rule, a business rule (`phases/2-briefing.md`). Open in the manifest → the ticket waits for the answer; it never flies at night.

**Night** — `Ночью: да | нет`, computed, never wished: `нет` until the night-queue rules below say `да`.


**Review** — whether the ticket gets a point review after its commit (`phases/6-review.md`). It never holds up the build: the next tickets fly while it runs. **Every ticket is reviewed once at the end anyway**, as part of the whole branch — a point review is only for what is worth catching earlier.

- `да — фундамент` — ticket 01, when later tickets build on it, and the expand step of a wide change. Nothing else is foundation.
- `да — <риск>` — a ticket whose **own code** is one of these: sign-in, passwords, sessions, 2FA; keys and secrets; money; deleting or migrating user data. A ticket that only checks permissions inside an ordinary feature is not a risk ticket — the whole-branch review covers it. Most tickets in a product with access rights touch them; marking them all is how a run reviews 12 tickets of 15.
- `нет` — the rest. Most tickets. **At T0 the one ticket is `нет` too**: the whole-branch review is its review, and a point review would read the same diff twice.

**Model and effort** — who builds it, and how hard it thinks. Both go into the subagent call as they are (`phases/5-subagents.md`); the money and the limits go to the executors, so this is where a run is made cheap or expensive. Decided from **what the ticket's core is**, first match wins:

| The core of the ticket | `Модель:` | `Усилие:` |
|---|---|---|
| a schema, a state machine, concurrency, architecture; ticket 01; the expand step of a wide change; anything `Ревью: да` | `opus` | `high` |
| a genuinely hard algorithm, an unfamiliar integration | `opus` | `high` |
| `Тип: prompt` — a prompt is the product here, and its defects are invisible to every test | `opus` | `high` |
| CRUD, an adapter to a ready contract, a migration to a ready schema, a handler over decided boundaries | `sonnet` | `medium` |
| renames, fixtures, docs, moving code without changing it | `haiku` | `low` |

`xhigh` is never a first choice — it is the escalation step (`phases/5-repair.md`). The reviewers and checkers are not tickets, and their models are fixed: the point reviewer, the Spec reviewer, the prompt reviewer, the G2 reader and the G4 blind checker run on `opus`; the Craft reviewer of the whole branch and the re-review of a repair run on `sonnet` (`phases/6-review.md`). A harness without a model choice ignores the field silently.

Calibrate, do not trust: after two or three runs, `repairs` by model in `state.js` says whether `sonnet` tickets come back more often than `opus` ones — a model that needs a repair every other ticket costs more than the one it saved.

### Night — computed from five conditions

`Ночью: да` only when **all five** hold; one doubt is `нет`. A night ticket is one nobody will be asked about before morning (`phases/5-night.md`):

1. **No open question to the owner** — none of its manifest rows is `open`, and `Внимание` is not `owner`. Method that is assumed, not settled, is `owner` (`phases/2-briefing.md`).
2. **No outward action** — nothing it does reaches past the machine: no deploy, no message to a real person, no webhook registration, no migration of the production database. Those are questions by rule 4, and at night there is nobody to ask.
3. **Deterministic tests** — its check runs on cassettes and stubs; a check that calls a live model or service is `нет`.
4. **Live calls only behind a cap** — a `prompt` or `e2e` ticket that needs a live run flies at night only with `EVAL_MAX_USD` / `E2E_MAX_USD` set; an empty cap is `нет`.
5. **An isolated zone** — no ticket of the day's work is expected to touch it, and its parents are landed or ahead of it in the night queue.

`check-plan` refuses `да` beside `Внимание: owner` and beside an `open` row; the other three are your judgement, and a ticket you are unsure of stays a day ticket.

## The ticket file

`.autopilot/<dir>/tickets/NN-<slug>.md`. The header lines are read by `ap.py` — keep their names:

```markdown
# 03 — Приём заявки от клиента

**Требования:** R01, R01.1, A01
**Зависит от:** 01, 02
**Зона:** `src/bot/` · `tests/bot/`
**Волна:** 2
**Архитектура:** §4 bot · §7 приём заявки
**Тип:** code
**Ревью:** нет
**Модель:** sonnet
**Усилие:** medium
**Внимание:** none
**Ночью:** да

## Что должно заработать

Клиент пишет боту, отвечает на три вопроса — что сломалось, адрес, телефон —
и получает подтверждение с номером заявки. Если сеть отвалилась на середине,
следующее сообщение продолжает с того же места.

## Из брифа, дословно

> «принимает заявки на ремонт техники»

## Разделы спецификации

Истории 1–5, Решения §2 и §4.

## Критерии приёмки

- [ ] Диалог из трёх шагов доходит до подтверждения
- [ ] Номер заявки уникален и виден клиенту
- [ ] Прерванный диалог продолжается, а не сбрасывается
- [ ] Незаполненный телефон даёт понятную ошибку, а не падение
```

- **The verbatim brief quotes are not decoration** — they are the last thing standing between a fresh context and a plausible reinterpretation, and the point reviewer judges the Manifest axis from them.
- **Every criterion is checkable and false at the commit the executor starts from.** A criterion already true tests nothing; the executor proves each one red before building it (`prompts/executor.md`).
- **A plan never quietly promises less than was asked.** `check-plan` searches every ticket for the words a task shrinks by: «v1», «упрощённо», «пока статично», «заглушка», «потом допилим», «в первой версии». Only the owner may postpone part of a request, so a hit is refused unless the ticket carries the line `**Урезание:** «слова владельца»`. A row already `placeholder` in the manifest does not count, nor does a stub in a test, a quote from the brief, or anything in backticks. A hit with no shrinking behind it — a criterion about removing a stub — is rewritten as what must work.
- **Every closed edge and every prohibition has a home.** A row of «Края данных» closed by a criterion, and a `Z#` checked by a test, is a line in «Критерии приёмки» of the ticket that owns that behaviour, and the test lives there. `Проверка: отдельный тест` stays on the criterion. A test that something does not happen is green before anything is built: its `REDPROOF` is a deliberate violation, put in and taken out.
- No file paths or code snippets except a structure prose states worse — a schema, a state machine.
- `Зависит от` lists ticket numbers only — `01, 02`, or `—`. A reference that is not a ticket's id fails `check-plan`.
- **`Тип`, `Модель`, `Усилие`, `Внимание`, `Ночью` are required** — `check-plan` refuses a ticket without one, with a value outside the lists above, with `Ночью: да` beside `Внимание: owner`, or a `migration` sharing its wave.

## Before the first ticket flies

**`interfaces.md` carries more than the boundaries** Phase 3 wrote there. Add the project rules an executor cannot derive: stack and versions; how to install — **in a fresh worktree**, since every executor gets one — run, and **one check command** — tests, types and lint together — plus how to run a single test file (ticket 01 creates the check command if the project has none); **the gates command**, `make gates CHANGED=1`, and the code standard, the `ub-mode` skill; the test tiers L0 and L1 (`phases/8a-e2e.md`); what must not be touched. **At T0 in a project that has no `make gates`, none is built**: one small fix does not pay for three tools; the report says so in one line. Otherwise, **ticket 01 installs every dependency «Решения по реализации» names** and builds `make gates` to the contract in `standards/gates.md` (by path from `skillDir`, to its executor only); any other dependency comes back from an executor as `BLOCKED` (`phases/5-repair.md`).

## Gate G3, publishing, and the plan commit

`python3 .autopilot/ap.py tickets` publishes every ticket to the dashboard and moves their manifest rows to `in-ticket`; `python3 .autopilot/ap.py check-plan` is the gate. It checks both directions — every live requirement in some ticket, every ticket tracing to a requirement — and that every ticket has a zone and a wave, waves respect the dependencies, and no two tickets in one wave write the same zone. Each `!` line is a plan defect: fix the ticket files and run both again.

**Then the plan commit** — the run's first, and the base every later diff is measured from. Run the redaction gate over `.autopilot/` (`phases/1-manifest.md`), then commit exactly the files this skill wrote so far — never anything else in the tree:

```bash
git add -A -- .autopilot .gitignore AGENTS.md CLAUDE.md .env.example && git commit -qm "Autopilot: план сборки" --trailer "Autopilot-Run: <папка>" -- .autopilot .gitignore AGENTS.md CLAUDE.md .env.example \
  && python3 .autopilot/ap.py set baseCommit="$(git rev-parse --short HEAD)"
```

Leave out of both lists any file that does not exist, and the memory file if it is the user's own. `<папка>` is `dir` without `--wip`, the same in every commit of the run. **The plan commit must exist before the first executor flies**: a worktree is cut from `HEAD`, and an executor whose checkout lacks the tickets builds blind.

A ticket that exists only in the dialogue is not a ticket — the user is shown a summary of files already on disk.

## Showing the plan

**Parallelism gets one line, and only if it is true**: «6 тасков в 4 волны, часть пойдёт параллельно».

- **semi, interview** — one screen, one plain line per ticket saying what the user will be able to do when it lands, then «Показываю план и начинаю. Скажи "стоп", если что-то не так» — and start. Never promise a countdown you cannot hold.
- **full** — the same screen as a notification.
- **manual** — a gate: `ap.py ask plan`, then technical detail, granularity and order discussed, an explicit «ок» before Phase 5.
