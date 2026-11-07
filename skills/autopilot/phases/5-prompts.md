# Phase 5 — Prompt tickets

Read only when the plan has a `Тип: prompt` ticket — at its first launch, beside `phases/5-subagents.md`. Everything there holds — worktree, contract, landing — except what this file replaces. In «Легко Сказать» the prompts are the product: a defect in one is invisible to every test and every gate, so a prompt is an artifact with its own version, its own checks and its own review.

## The prompt zone

**`prompts/**` belongs to prompt tickets only.** A code ticket that needs a prompt changed returns `BLOCKED` naming it; `check-plan` refuses a code ticket whose zone reaches into `prompts/`, and a prompt ticket whose zone leaves `prompts/` and `evals/`. The output schema a stage returns lives in `schemas/` — it is a boundary between the prompt and the code that parses it, decided in the spec, written by a code ticket, read by prompt tickets. A prompt that needs a different schema is a code ticket first.

```
prompts/registry.yaml       one entry per prompt: name, stage, version, file, model_hint, schema, budget_tokens
prompts/CHANGELOG.md        newest first: дата — имя vX.Y → vX.Z — что — зачем — разница eval
prompts/lint.yaml           required sections; the default below until the project writes its own
prompts/<stage>/<name>.xml  <prompt_system> with <meta>: version, stage, model_hint
evals/<stage>/*.yaml        cases on the stage's contract
evals/<stage>/cassettes/    recorded answers, keyed by hash(prompt version + input)
```

**Every change is a version bump**: minor for wording, major for anything the output contract sees — and a major bump without the schema ticket behind it is `BLOCKED`. The registry entry and a CHANGELOG line go in the same ticket; the old version stays in git, which is what A/B compares against.

## Acceptance criteria — deterministic first

1. **Well-formed XML** — a parser, not an eye. (Of the prompts the owner had on 2026-11-07, `stage3_coach.xml` was not: a mismatched tag. A prompt that does not parse is read by a model however it guesses.)
2. **Lint of required sections**, from `prompts/lint.yaml`. The default, drawn from `stage1_*`, `stage2_*`, `stage3_coach.xml`: root `<prompt_system>`; `<meta>` carrying `version`, `stage` and `model_hint`, as attributes or child elements; a data section where the author's text arrives (`<inputs>` or `<data_layer>`); an output section naming its schema (`<output_specification schema="schemas/<stage>.json">`); a protection section (`<prompt_protection>` or `<guardrails>`).
3. **Token budget** — `budget_tokens` in the registry, measured, never estimated by eye.
4. **Eval** — `make eval STAGE=<stage>`: cassettes, offline, deterministic, free. `LIVE=1` calls the real model and records new cassettes, capped by `EVAL_MAX_USD`; **an empty cap means live is off** — the number is the owner's (it is money), and in full it stays empty with a line in the report. A changed prompt misses every cassette, so a prompt ticket needs live once: `.env` is copied into its worktree before launch, unopened, the way the blind checker gets it (`phases/8-final.md`).
5. **A/B against the previous version, on the same cases** — `make eval STAGE=<stage> AB=<base>`. A case the old version passed and the new one fails is a regression: it blocks, unless the ticket's own criteria change that behaviour on purpose, and then the case changes in the same ticket with its reason in the CHANGELOG.
6. **Judged checks only where a deterministic one cannot exist** — the coach's question is warm, the draft keeps the author's voice. The judge, the rubric and the repeats are the rules of `phases/8a-e2e.md`: another model family, a fixed rubric, three repeats, a threshold on the mean and on the spread.

These replace seam tests and `make gates` for this ticket; the check command for it is `make prompt-check STAGE=<stage>` — lint, budget, offline eval — and it runs in steps 5–6 of `phases/5-subagents.md` where the check and the gates would.

## The executor and the review

- **The executor reads `prompts/prompt-executor.md`** instead of `prompts/executor.md`, on `opus · high`. Its contract carries `EVAL:` where a code ticket carries `GATES:`.
- **Every prompt ticket gets a point review** — `Ревью: да — промпт`, one fresh subagent on `opus` with `prompts/prompt-review.md`: the axis «Prompt craft» replaces Craft; Manifest and Spec stay. A prompt costs one review; a broken one costs every author who meets it.
- **Method is the owner's** (`phases/2-briefing.md`). A prompt ticket whose method is still open is `Внимание: owner` and waits; one whose method is assumed carries `[МЕТОДИКА — подтверди]` in the prompt and `Внимание: review`. Neither is ever filled in from what coaching usually looks like.
- **Night** — a prompt ticket flies at night only with the method settled and `EVAL_MAX_USD` set (`phases/5-night.md`).
- **The whole branch** — with two or more prompt tickets in the run, the whole-branch review adds one prompt reviewer, mode «ветка», for what no single ticket shows: two stages that contradict each other, a hand-off field one stage writes and the next does not read.
