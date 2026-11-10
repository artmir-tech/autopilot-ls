# Phase 8a — E2E: replaying real dialogues

Read in Phase 8 **after the blind acceptance and before the memory agent and the report** (`phases/8-final.md`, §1a), and by the night run after its queue (`phases/5-night.md`). The test tiers below are also project rules: Phase 4 copies them into `interfaces.md`, so every executor writes L0 and L1 without opening this file.

A coaching bot can pass every test and still ask fourteen questions where the method says ten, or put words into an author's mouth. Only a whole dialogue shows that — and a whole dialogue on live models costs money and is never twice the same, so it lives in its own tier, outside every ticket's check.

## Three tiers

| Tier | What | When | Cost |
|---|---|---|---|
| **L0** | the pure core — the state machine, validators, the model router, parsers of the model's answers | every ticket, inside the check | none; no I/O |
| **L1** | each stage on **cassettes** — the model's answer recorded once, keyed by `hash(prompt version + input)`; a missing cassette is red, never a live call | every ticket, inside the check | none; offline, deterministic |
| **L2** | **replay** of real dialogues through the CLI channel, on live models, judged by a model of another family | at night or by hand — never in a ticket's check | capped by `E2E_MAX_USD` |

A test that calls a live model inside L0 or L1 is a defect of that test — a red check that depends on the weather teaches everyone to ignore red.

## L2 — how a replay runs

- **The corpus** — two halves (`phases/1-manifest.md`, the personal-data gate): `tests/e2e/dialogues/*.yaml`, committed — only dialogues whose people agreed to git, anonymised before the commit; and `tests/e2e/local/*.yaml`, **never committed** — everyone else's, used in local runs only. Each file: the author's persona, the author's real turns as the skeleton, the stage transitions the dialogue must pass. A report of a local run names dialogues by id, never by content.
- **The channel** — the bot's transport behind one interface with a CLI implementation (`CliChannel`), so neither L2 nor the blind checker needs a Telegram token. An `e2e` ticket builds it, early.
- **The simulated author** — a model that answers the coach as the persona would, using the real turns wherever the coach asked what the real coach asked, and the persona where it did not. It never sees the rubric.
- **The judge** — a model of **another family** than the coach's, pinned to an exact model id, with a fixed rubric per stage, `tests/e2e/rubrics/<stage>.md`: the stage kept and its transitions taken; the number of the coach's questions within the owner's range; **no invented fact about the author**; the author's voice kept in the drafts; the drafts W1–W3 by the owner's criteria; each `Z#` of the spec's «Запреты» that only a reading can check. **The rubric is method** — its criteria and numbers are the owner's (`phases/2-briefing.md`); which judge family and vendor is a question too, since it costs money and ties them to a vendor.
- **Three repeats** per dialogue. A dialogue passes when the mean score clears the threshold **and** the spread between repeats stays within its own — both in `tests/e2e/thresholds.yaml`, the owner's numbers; until they give them, the run reports scores without a verdict.
- **The cap** — `E2E_MAX_USD` in `.env`; empty means L2 does not run, and the report says so. The harness counts the spend and stops at the cap; a partial run is reported as partial.
- **A baseline** — every run's report goes to `tests/e2e/reports/<date>.json` with the judge's model id; a run is compared with the last green one, never with memory.

## What happens to the result

`python3 .autopilot/ap.py e2e dialogues=12 passed=11 usd=3.4 --regression "d07 — коуч задал 14 вопросов при 5–10"` — one call per run; the numbers whole or nothing.

- **A regression** — a dialogue that passed in the baseline and fails now, or a score that fell past its spread — **becomes a ticket**, `E1`, built like `F2` (`phases/8-final.md`): the failing dialogues and the judge's lines as its criteria, `Тип: prompt` or `code` by where the cause is, one executor, one more L2 run **on those dialogues only**, then the report. What still fails goes to «Открытые вопросы». At night the `E1` ticket is written and left for the day.
- **A dialogue that never passed** is not a regression: it goes to the report as what the bot does not do yet, with the dialogue's id.
- **Judge drift** — the same dialogue, the same coach version, a different score across runs: a line in the report and a pinned judge, not a ticket.
