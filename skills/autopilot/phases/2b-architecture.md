# Phase 2b — Architecture

`ap.py stage architecture`. The brief says what the product is; the manifest says nothing may vanish; **this phase decides how the product is built so that it is that product** — before the spec, before a single ticket. A boundary chosen by ticket 01 having seen an eighth of the work is the most expensive decision in a long project; a real audit of a rebuild scored 3.6 of 5 two runs in, and ten architectural repairs had to be threaded into briefs already in flight.

An architect designs. A critic who has never met the architect scores the design against a long list. They go round until the score is at least **9 of 10**. You carry files between them and do neither job.

## 1. Size first — does this need it, and is it one run at all?

One line to yourself, from the brief and the briefing: «~N тысяч строк: …», by the table in `phases/4-plan.md`. Then:

| Estimate | Route |
|---|---|
| up to ~6K lines (T0, T1), depth not `deep`, the owner did not ask | `ap.py stage architecture skip --note "<почему не нужна, простыми словами>"` → Phase 3 |
| ~6–36K lines (T2, T3), or `deep`, or the owner asked | this phase, scope `run` |
| over ~36K lines, or several weeks of work | this phase, scope `project`, then the master plan: **read `phases/0-program.md`** after the gate |

**A project that already has an accepted architecture** (`ap.py arch status` says «принята») does not get a new one. The run reads it, and if its brief does not change it: `stage architecture skip --note "архитектура проекта принята, этот прогон её не меняет"`. If it does — §6.

## 2. Existing code goes first

When Phase 0 found code, run the exploring subagent described at the top of `phases/3-spec.md` **now**, and hand its `notes.md` to both agents. Phase 3 does not repeat it.

## 3. The loop

```bash
python3 .autopilot/ap.py arch start --scope run        # или project
```

| Step | Who | Model · effort | Gets | Writes |
|---|---|---|---|---|
| Design | architect | `opus` · `xhigh` | `prompts/architect.md`, every `*-brief.md`, `manifest.md`, `notes.md`, `.autopilot/prior-art.md`, `standards/architecture-rubric.md`, the project's memory and ADRs | `.autopilot/architecture.md` |
| Audit | critic, **a fresh one every round** | `opus` · `xhigh` | `prompts/architecture-critic.md`, mode `audit`, the briefs, the manifest, `prior-art.md`, the document, the rubric, the code if any | `.autopilot/architecture-audit/NN.json` |
| Score | `ap.py` | — | `ap.py arch round --file .autopilot/architecture-audit/NN.json` | the number, the verdict |
| Repair | the architect again, or a fresh one with the files | `opus` · `xhigh` | `prompts/architect.md`, «Ремонт», the audit file verbatim | the document |
| Confirm | a **second independent critic**, blind | `opus` · `xhigh` | the same as Audit, mode `confirm` — no earlier audit, no mention that one exists | `NN.json`, `arch round --kind confirm` |

Spawn with the Agent tool, `model` and `effort` as in the table — this skill requires those efforts. No worktree: nothing here touches code, and only these two agents and you write in `.autopilot/`.

**From the second round on**, the critic's prompt says, after the path list: «После того как поставишь все оценки, открой `<path to the previous NN.json>` и заполни `prior`». Before the scores it must not open it: an old score is an anchor.

**`ap.py` does the arithmetic and refuses a bad audit.** A criterion left out, a score without evidence, a score under 9 without a `gap`, a blocking finding on a score above 7, an earlier finding left unanswered: the whole file goes back to the critic. You never average anything and you never edit a critic's file.

Reading the verdict:

- **«ещё круг»** — the architect repairs, a new critic audits.
- **«порог взят — теперь подтверждение»** — the confirming critic. A score that only the first critic gave is one opinion; two blind ones agreeing is a result.
- **«GA пройден»** — `ap.py stage architecture done`, on to §5.
- **«потолок кругов»** — six rounds, audits and confirmations together. Each new look finds something new, and a design that has not reached 9 in six rounds has a question in it that the architect cannot answer. §4.

**Tell the user two lines at the end**: the score, and the one thing the design decided that they would most want to know. In `manual`, the document is a gate: `ap.py ask spec`, show section 1, section 2 and section 18, wait for «ок».

## 4. What belongs to the owner

Section 18 of the document and every finding with `owner: true` are decisions the agents may not make: money, what is in the product, method, law. Each becomes a card on the owner's page, in plain words:

```bash
python3 .autopilot/ap.py question add --title "…" --about "…" --agrees "…" --recommend "…" --why "…" --silence "…" --urgency "Закрывает запуск"
```

**You** carry them over from section 18; the architect reads `.autopilot/project/questions.json` so it does not ask twice. A question that does not stop building but blocks going live carries the urgency «Закрывает запуск» and is named again in every report until it is answered.

- `semi`, `interview`, `manual`: ask before the next round when the answer changes the design. A question that does not change it waits for the next list.
- `full`: the recommendation is taken, recorded as an `ASSUMPTION` row, and listed in the report.

**At the ceiling, in every mode**: `ap.py ask stop --note "…"`; say what is missing in plain words, what you recommend, and what going ahead would risk. Only on their answer: `ap.py arch waive --by-user "<их слова>"`. The page then shows the real score and «принято с оговоркой», never a nine.

## 5. What reads it afterwards

An accepted architecture is a contract, like the manifest:

- **Spec** (`phases/3-spec.md`) takes its boundaries from sections 4–9 and may refine, never contradict.
- **Plan** (`phases/4-plan.md`) cuts zones along the components; each ticket names its sections in `**Архитектура:**`.
- **Executors** read those sections after `interfaces.md`. A conflict is `BLOCKED`, never a quiet workaround (`prompts/executor.md`).
- **The whole-branch review** checks conformance (`phases/6-review.md`).

**Commit it now** — the design outlives this session: `git add -A -- .autopilot && git commit -qm "Autopilot: архитектура принята" --trailer "Autopilot-Run: <папка>" -- .autopilot`.

## 6. Changing an accepted architecture

Building will prove some of it wrong. That is not a failure; quietly building something else is.

```bash
python3 .autopilot/ap.py arch delta --note "что меняется и почему"
```

The architect edits the document, one critic in mode `delta` audits it, `arch round --kind delta`. No confirmation; three rounds at most. Until it passes, `ap.py finish` refuses a run whose architecture stage is done and whose gate is open.

## 7. Checking the code against it

**After every landed run of a program** (`phases/8-final.md`): one critic, `opus` · `high`, mode `as-built`, gets the document and the code; `arch round --kind as-built`. It does not move the gate. It answers a different question — does what we built still follow what we designed — and its findings go into the next run's brief, or become a delta. Two runs without this check is how a rebuild drifts to 3.6 of 5 with nobody noticing.
