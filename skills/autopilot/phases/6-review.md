# Phase 6 — Review

Two moments, both done by someone who did not write the code:

- **Point review during the build** — for tickets whose file says `Ревью: да` (the foundation and the narrow list of risks, `phases/4-plan.md`), and for a ticket whose contract reports one of its own requirements as not done. **After the commit, never before it**: the ticket lands on a green check, the next wave flies, and the review runs beside it. At T0 there is none: the whole-branch review is that ticket's review.
- **The whole-branch review** — once, after the last ticket, as the `review` stage. **Always**, at every tier and in every mode.

Every other ticket is reviewed only as part of the branch. Why this shape, with the measurements behind it: `docs/autopilot/design.md` in the skill's repository.

## Three axes, reported separately

| Axis | Question | Fails when |
|---|---|---|
| **Manifest** | does it deliver what the user asked for, in their words? | a requirement quietly shrank |
| **Spec** | does it implement what the spec decided? | the executor improvised |
| **Craft** | is the code fit to build on? | it works today and blocks tomorrow |

**The gates are not an axis — they are facts.** Before any reviewer sees the code, the check and `make gates` have run (`phases/5-subagents.md`, steps 5–6): a red build, typecheck or lint, CRAP ≥ 10, a duplicate pair ≥ 0.8 and a surviving mutant are already `BLOCKING` and already on their way back as a дозапрос. A reviewer gets the `GATES` line so it knows what the machine checked, and judges what the machine cannot see — design, Model the Domain, Boundary Discipline (`prompts/review.md`). A gate finding repeated by a reviewer is noise, not a second vote.

Merged or ranked together, one axis masks another. **Which axis a finding belongs to: could the executor have known?** It saw its ticket, the spec sections named, `interfaces.md`. Yes → Spec or Craft, fixed in this ticket. No → Manifest, and the defect is in the spec or the cut — repair those first, never re-run the executor against words it was never given.

## Point review

**One fresh subagent per review**, `model: "opus"` — it judges all three axes, Manifest included — never a reviewer kept alive across tickets.

**Launch it in the background right after the commit** — `ap.py ticket NN review`, then the subagent — and go on with the build: launch the next wave, land other tickets. Waiting on a point review is never a reason to hold a wave.

It gets, by path: **`prompts/review.md`** (`skillDir`), required reading before the diff; the ticket file — its brief quotes are the Manifest axis; the spec sections the ticket names, and always the section «Запреты»; `interfaces.md`; whatever the repo documents about how code is written. Pasted: the executor's `TESTS`, `GATES` and `REDPROOF` lines, and **why it is reviewed** — «фундамент», the named risk, or «оговорка о требовании»: that decides what blocks. And the command that shows the whole ticket — `git diff <base>..<commit>` (`tickets[].base` and `.commit` in `state.js`: a ticket lands as a series of small commits). It must not repair, refactor, spawn agents or invoke any skill but `ub-mode`.

What comes back is a verdict per axis and a `BLOCKING` line. Nothing blocking → `ap.py ticket NN done` again, and the ticket is finished. `BLOCKING` → `phases/5-repair.md`, verbatim: the fix is a second commit of the same zone. `FINDINGS` → `ap.py add concerns "…" "…"`, one call, each with its file and line. Neither the diff nor the reasoning reaches you.

**When a blocking fix changes an interface** that tickets now in flight call, append the change to `interfaces.md` and send each of them one line when it returns — before its commit.

**The re-review of a repair** — mode «ремонт» in `prompts/review.md`, again a fresh subagent, `model: "sonnet"`, **at most once per ticket**. It gets `git diff <ticket commit>..<repair commit> -- <zone>` — the fix, not the whole ticket again — and the conditions the repair had to close, and answers each closed or not.

## What blocks

**Only the reviewer's `BLOCKING` line triggers a repair**, and what may appear there is short:

- **Manifest `partial` or `missing`** — a requirement the user asked for is not delivered.
- **An invented fact** — a plausible price, address or text where the user's own fact belongs.
- **Spec *extra*** — surface nobody asked for, unless the rest genuinely needs it.
- **A red check or a red gate** — build, typecheck, lint, CRAP, duplicates, mutants. These block **before** review, by the orchestrator's own run; they appear here so nobody waits for a reviewer to say it.
- **A test bound to internals** the next ticket has the right to rewrite.
- **A broken prohibition** (`Z#` in the spec), and **a criterion marked `Проверка: отдельный тест` that has no test**.
- **In the foundation, a defect the following tickets will build on** — a wrong key in the schema, a shared client that fails the next ticket's call, access that ignores the boundary the spec drew.
- **For a risky ticket, a hole in that risk** — the security list in `prompts/review.md`.

Everything else waits for the whole-branch review. **You do not widen the list**: not «блокирующего нет, но раз уж нашлось», not a finding from `FINDINGS` you happen to agree with. That is the cost rule in `SKILL.md` — widening it is a line to the user with its price, never a quiet decision.

## The whole-branch review — the `review` stage

After the build: `ap.py stage review`.

**First the gates over the whole run** — no `make gates` in the project (a T0 without them, `phases/4-plan.md`): one line in the report and on — `make gates CHANGED=1 BASE=<baseCommit> 2>&1 | tail -15` — after every executor has landed, alone on the machine, with `MUTATE_WORKERS` workers (`standards/gates.md`, «Нагрузка на машину»). Red lines go straight into `F1` as criteria — they are facts, not findings, and no reviewer is spent on them. The full mutation run without `CHANGED` is a night job (`phases/5-night.md`), not this step.

**Two fresh subagents, in parallel, one message** — the axes split, because merged they mask each other and because Craft is the half the gates already narrowed:

| Half | Model | Judges | Mode in `prompts/review.md` |
|---|---|---|---|
| Spec + security | `opus` | does the branch implement what the spec decided; the security list, always | «ветка-spec» |
| Craft | `sonnet` | tests first, smells, ub-mode beyond the gates | «ветка-craft» |

At T3 with a large diff, each half may go out as up to two subagents, each given a group of zones — four at most. Each gets `prompts/review.md` with its mode, the range `git diff <baseCommit>..HEAD` (`baseCommit` in `state.js`) to run itself, `spec.md`, `interfaces.md` and — for the Spec half — `.autopilot/architecture.md` by path, the `ub-mode` skill (each loads it itself), the gates' summary line, and the deferred findings from `state.js` → `concerns`, so it confirms or drops those of its axis rather than rediscovering them. It may open files outside the diff where an interaction needs it. The Manifest axis is not judged here — the blind acceptance in Phase 8 closes it against the brief. A run with `Тип: prompt` tickets adds the prompt reviewer of `phases/5-prompts.md` for the prompt zone, on `opus`.

It returns every finding sorted into three: **fix now** — it costs more to leave than to close, and the fix is bounded; **report** — real, not worth holding delivery for; **drop** — taste, or the code it pointed at is gone. Anything repeated across three or more tickets is **fix now**: that is a convention the project never settled. A security finding is fix now or report — never drop.

**All the fix-now findings and red gate lines become one ticket, `F1`**: `tickets/F1-<slug>.md` with the requirements the fixed code serves, `Зависит от: —`, the wave after the last one, the union of the files named as its zone, `Тип: code`, `Ревью: да — ремонт ветки`, `Модель: opus`, `Усилие: high`, `Внимание: none`, `Ночью:` by the night rules of `phases/4-plan.md`, and the findings as its acceptance criteria, verbatim. A fix inside `prompts/**` is a separate `F1p`, `Тип: prompt` — the prompt zone belongs to prompt tickets only. `ap.py tickets`, one executor, the check, one re-review in mode «ремонт» — what it still finds open goes to the report, not to a second round — one commit — never by you, never by the reviewer: a fix that skips the ticket path skips the rollback point and the green check. Every «report» finding → `ap.py add report "…" "…"`, in words the user understands; the final report reads them from there.

Then `phases/8-final.md`.

## Reporting

To the user, nothing per ticket. After the whole-branch review, one line: «Код-ревью: нашлось 7 замечаний, 4 поправил, 3 — в отчёте».
