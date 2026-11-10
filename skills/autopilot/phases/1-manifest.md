# Phase 1 — Manifest

The brief is the only thing in this process the user actually authored; everything downstream is a paraphrase of it. This phase turns it into an artifact that survives every later rewrite, so that nothing can quietly stop existing. It runs **before** the briefing: the questions are themselves a re-encoding of the brief, and the anchor has to be dropped first.

## 1. Redaction gate — before anything is written

Every piece of user text — the brief, every answer, every pasted fragment — passes this gate on its way to a file, a prompt or the dashboard.

| Kind | Shape |
|---|---|
| Stripe / OpenAI-style | `sk-…`, `sk_live_…`, `sk_test_…`, `rk_live_…`, `pk_live_…` |
| GitHub | `ghp_…`, `gho_…`, `ghs_…`, `github_pat_…` |
| AWS | `AKIA…`, `ASIA…` |
| Google | `AIza…`, `ya29.…` |
| Slack | `xoxb-…`, `xoxp-…`, `xoxa-…` |
| Telegram bot | 8–10 digits, colon, 35 chars of `[A-Za-z0-9_-]` |
| JWT | `eyJ…` followed by a dot and more base64 |
| Connection string | `<scheme>://<user>:<something>@<host>` |
| Private key | `-----BEGIN … PRIVATE KEY-----` |
| Generic | ≥32 chars of hex or base64 next to `key`, `token`, `secret`, `password`, `ключ`, `токен`, `пароль`, `доступ` |

**Personal data — the gate's second half, for fixtures.** In «Легко Сказать» the test material is real people telling real stories: dialogues, extracted JSON dossiers, cassettes of the model's answers to them. **Consent decides what may enter git at all**: only the dialogues of people who agreed to it — in this project, the owner's own — are committed; everyone else's stay **local, outside git** (`tests/e2e/local/`, ignored from Phase 0), usable in local runs and never shown to anyone. And what is committed still never reaches a commit as it is — not in `tests/`, `evals/`, `prompts/` few-shot, `.autopilot/`, a ticket's quote:

| Kind | Shape | Becomes |
|---|---|---|
| Name, surname, patronymic | a capitalised Russian or Latin name in a dialogue, a dossier field `name` | «Автор-1», «Клиент-2» |
| Phone | `+7…`, `8 9…`, ten or more digits with separators | `+7 900 000-00-01` |
| Telegram handle, e-mail | `@…`, `…@…` | `@user_1`, `user1@example.com` |
| Company, workplace, brand | a dossier's `company`, «работаю в …» | «Компания-1» |
| City, address, school | a dossier's `city`, «живу в …» | «Город-1» |
| Dates that identify | a birthday, a dated life event | the year only, or «[дата]» |

**Consistent pseudonyms within a file**, so a dialogue still reads as one person's; **the mapping never committed** — it stays on the owner's machine or nowhere. The scan is regexes for the shapes above plus the list of names the corpus itself carries; the anonymising is done by the executor of the ticket that brings the corpus in (`Тип: e2e`), and `make pd-scan` joins its check. **You run the same scan** over `.autopilot/` before the first commit of the run, beside the secrets, and over the brief before it is written: a name from a test dialogue quoted into the brief becomes «Автор-1» there too, with one line to the owner — «В задаче были имена из тестовых диалогов — в файлах заменил на псевдонимы».

On a secret's hit: replace the value with `[REDACTED:<VAR_NAME>]` (the conventional name — `STRIPE_SECRET_KEY`, `TELEGRAM_BOT_TOKEN`, `DATABASE_URL`); add the name to `.env.example` with an empty value; tell the user in one plain line — «Ты прислал ключ Stripe — я его не сохранил. Впиши его сам в `.env`, а этот лучше отзови и выпусти новый: он уже побывал в переписке»; carry on. **Never echo the value**, not even to confirm what you found. Before the first commit — the architecture commit (`phases/2b-architecture.md` §5), the plan of a program, or the plan commit at the end of Phase 4 — run the gate over all of `.autopilot/`.

## 2. The brief file

The redacted brief, **word for word**, into `.autopilot/<dir>/<YYYY-MM-DD>-brief.md` (today's date), then `ap.py set briefFile=<name>`:

```markdown
# Изначальная задача

> Записано <дата>. Текст задачи не редактируется — он эталон, с которым
> сверяется готовый результат. Всё, что сказано позже, дописывается
> в «Дополнения» ниже.

<весь текст пользователя, дословно, после редактирования секретов>

## Дополнения

- <дата> — «SMS не надо, только телега»
```

- **No paraphrase, no cleanup, no reordering.** Bad grammar and contradictions stay: a tidied brief is already a spec, and a spec is what cannot be checked against.
- **Everything counts as brief** — asides, constraints, «и ещё хорошо бы», a stack preference, a deadline mentioned in passing.
- **The text above never changes; the file keeps growing.** Everything the user says later — a cancellation, an addition, a reversal at ticket four — is appended under `## Дополнения`, dated and verbatim. This matters because **both independent checks read the brief and are forbidden the manifest**: a change that reached the manifest but not this file does not exist for G2 and G4.
- A brief dictated on a **later day** is a new file with that day's date, in the same run directory.

## 3. Atomise into requirements

Split the brief into the smallest units that can independently be true or false about the finished product, into `.autopilot/<dir>/manifest.md`. Every row carries the **exact words it came from** — a paraphrased requirement drifts exactly like a paraphrased brief.

```markdown
# Манифест требований

Источник: `<дата>-brief.md`. Строку из этого списка может снять **только пользователь**.

| ID | Из брифа (дословно) | Статус | Основание | Где |
|----|---------------------|--------|-----------|-----|
| R01 | «принимает заявки на ремонт техники» | in-ticket | — | spec §2 → T02 |
| R02 | «складывает их в Google-таблицу» | in-ticket | — | spec §4 → T05 |
| R04 | «и дублировать на SMS» | dropped | пользователь: «SMS не надо, только телега» | — |
| R05 | «фирменные цвета студии» | placeholder | цвета не переданы | отчёт |
| R06i | *(подразумевается)* кто-то должен читать заявки | deferred | вне рамок §9: админки в брифе не было | отчёт |
```

Keep the column order: `ap.py` reads the ID from the first column and the status from the third, and appends ticket numbers and commits to «Где», the fifth. A `|` inside a quote is written `\|`.

| Status | Meaning | Set by |
|---|---|---|
| `open` | not resolved yet | initial |
| `in-spec` | landed in the spec, section noted | you |
| `in-ticket` | a ticket delivers it | `ap.py tickets` |
| `done` | built and committed | `ap.py ticket … done` |
| `placeholder` | built, with a visible stub where a user fact belongs | `ap.py ticket … done --placeholder` |
| `deferred` | consciously postponed, with its line in the spec's «Вне рамок» | you |
| `dropped` | **cancelled by the user** | **the user, never you** |

A fact the user does not have yet — «цены пришлю потом» — does not make the row a placeholder early: it stays live and goes through the spec and a ticket like any other, with the missing fact named in Основание, and becomes `placeholder` when the stub is built.

- **`dropped` requires the user's own words** in Основание. You may *propose* dropping — that is a question, not a status change.
- **`deferred` is not `dropped`**, and every `deferred` row reaches the report under «что не вошло».
- **Silence never cancels anything.** A requirement the user stopped mentioning is still live.

**Implicit requirements** get a trailing `i` (`R06i`) — what the brief plainly implies but never says: «принимает заявки» implies somewhere to read them. Too obvious to state, too big to skip: route them to the briefing as questions; in full they become `ASSUMPTION` decisions in the report.

**Discovered constraints** are `D##` — what the **build** proved that the plan did not know. After the briefing, a `D##` is the only row **you** may add, and only through `phases/5-repair.md`; the only other way the manifest grows is a `G##` the user asked for. A `D##` never retires a requirement. Its status is `in-spec` — the amended section — and it is a constraint, not a requirement: it is not counted and needs no ticket of its own.

**How fine:** one row = one thing that can be true or false on its own. «Бот принимает заявки и складывает в таблицу» is two rows. A 2000-word brief usually yields 25–50 rows; under 10 from a long brief means you summarised instead of atomising.

## 4. Report in one line

«Разобрал задачу на 23 требования — держу их под контролем до самого конца.» No table in the chat.

## The gates

A failed gate is not a warning — the phase is redone.

- **G1, after the briefing** — every row has a status; anything still `open` has a recorded reason — a fact the user will supply later, named in Основание. In full, no question stays open.
- **G2, after the spec** — zero `open`, **and** an independent reader given only the brief and the spec finds nothing missing (`phases/3-spec.md`).
- **G3, after the plan** — every `in-spec` row is in a ticket and every ticket traces to a row: `ap.py check-plan` (`phases/4-plan.md`).
- **G4, at the end** — blind acceptance against the brief, spec withheld (`phases/8-final.md`).

## Keeping it current

Edits of the affected rows, never a rewrite of the table. `ap.py` moves rows to `in-ticket`, `done` and `placeholder` by itself; you change them at the other moments: after each briefing answer, after the spec (`in-spec` / `deferred`), on a `D##`, and when the user changes something mid-flight — the row moves (`dropped` with the quote, or a new `G##`) **and the same words go into the brief's `## Дополнения`**. The procedure is in `phases/2-briefing.md`.
