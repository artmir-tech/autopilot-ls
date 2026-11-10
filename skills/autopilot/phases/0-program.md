# A program — the whole project as a master plan

Read when Phase 2b's sizing says the work is over one run (more than ~36K lines, or several weeks), or when `.autopilot/program.md` exists at preflight or resume. One run is at most ~36K lines and twelve tickets; a real product is several. **A program is the whole project written down before the first line of code: its runs, what each gives the owner, what depends on what, roughly when — and a page where the owner sees all of it.**

The owner does not read a single run's report and know where the project stands. Run 3 of what? A hundredth of it, or half? This phase exists so that question always has an answer.

## 1. The planning session

The first session of a big project builds nothing. It goes through the ordinary phases as a run, and lands as a plan:

| Step | What | Result |
|---|---|---|
| 1 | Manifest, Briefing (`phases/1-manifest.md`, `phases/2-briefing.md`) — the whole brief, once | the run's `manifest.md`; a copy of the brief as `.autopilot/program-brief.md` |
| 2 | Prior art, scope `project` (`phases/2a-scout.md`) | `.autopilot/prior-art.*` |
| 3 | Architecture, scope `project` (`phases/2b-architecture.md`) | `.autopilot/architecture.md`, gate GA |
| 4 | The master plan (§2, §3) | `.autopilot/program.md`, one brief per run |
| 5 | `ap.py program check` — zero `!` | every run sized, every requirement placed |
| 6 | The owner's page published (§6) | the whole project visible before any code exists |
| 7 | `ap.py program plan --result "<сколько прогонов и что в итоге будет>"` | stages from Spec on closed as skipped; the run's folder loses `--wip` |
| 8 | commit: `git add -A -- .autopilot AGENTS.md CLAUDE.md .gitignore`, «Autopilot: план программы», only paths that exist | the plan is on record |

`semi`, `interview`, `manual`: show the list of runs in plain words and wait for «ок» before step 7. `full`: go on and put it in the report.

## 2. The file

`.autopilot/program.md`, committed, read by people as well as by `ap.py`:

```markdown
# Программа — <проект>

Бриф программы: `.autopilot/program-brief.md`. Архитектура: `.autopilot/architecture.md`.
Параллельно: 1

## Прогоны

| ID | Прогон | Зависит от | Статус | Папка | Итог | Тасков | Дней | Простыми словами | Что это даёт | Начат | Сдан |
|----|--------|------------|--------|-------|------|--------|------|------------------|--------------|-------|------|
| P01 | Ядро: автомат, схема БД, миграции | — | landed | `2026-11-10-core` | ядро есть | 8 | 3 | Ядро | Правила продукта работают и проверены | 2026-11-10 | 2026-11-12 |
| P02 | LLM-слой: реестр, роутер, кассеты | P01 | in-flight | `2026-11-12-llm` | — | 11 | 4 | Подключение моделей | Бот может спрашивать нейросеть | 2026-11-13 | — |
| P03 | Стадии: обработчики и промпты | P02 | pending | — | — | 12 | 5 | Разговор с автором | Бот ведёт автора по шагам | — | — |
| P05 | Блок интервью | P01 | blocked | — | ждёт методику от владельца | 10 | 4 | Интервью | Бот знает автора | — | — |

## Ключевые моменты

| ID | Момент | После | Что станет можно |
|----|--------|-------|------------------|
| M1 | Первый настоящий разговор | P03 | Попробовать продукт самому |
```

| Column | Written by | Rule |
|---|---|---|
| `Статус`, `Папка`, `Итог`, `Начат`, `Сдан` | `ap.py` | `in-flight` at `init --program P02`, `landed` at `finish`; `blocked` and back: `ap.py program P05 block --note "…"` / `program P05 pending` |
| `Тасков` | you, then `ap.py` | an estimate now; replaced by the real count when the run publishes its tickets. It is the run's weight on the page |
| `Дней` | you | calendar days, an honest guess. A real week of runs is the calibration, not optimism |
| `Простыми словами`, `Что это даёт` | you | **the owner's words**: no codes, no jargon. «Подключение моделей», never «LLM-слой» |

`Параллельно: N` is how many runs may fly at once; the Gantt lays runs into that many lanes. **Rows go in dependency order**: a run depends only on rows above it, `program check` says so.

## 3. Cutting the runs

- Cut along section 16 of the architecture, «Порядок сборки». Each run a coherent product slice that **lands green on its own**, the groundwork first, by the size rules of `phases/4-plan.md` one level up.
- **Every live requirement belongs to a run**: the manifest's «Где» column names its `P##`, and `program check` refuses a row left without one. Nothing quietly vanishes between runs either.
- **Shared resources are dealt out here**: migration numbers, shared files, contracts between runs. Parallel runs that were not told collide — two runs both took migration number three in a real rebuild.
- **Each run gets its brief now**: `.autopilot/briefs/P03.md` — first line «Прогон P03 программы — фрагмент брифа программы, дословно», then the verbatim slice of `program-brief.md`, then the architecture sections it builds and what it may rely on from the runs before it. That is what «the project is already written down» means: a later session needs no memory of this one.
- Dependencies are runs, not tickets: P03 needs what P02 *landed*, read from P02's `interfaces.md` and `PROGRESS.md`, never from a run still in flight.
- Cutting is your process decision. **What is in the product is not**: whether a capability is wanted at all stays the owner's.

## 4. A run inside the program

Each run has its own master plan: its tickets in waves, which the page draws as a small Gantt inside its report. The run reads the project's architecture and prior art instead of redoing them:

```bash
python3 .autopilot/ap.py stage scout skip --note "поиск готового сделан на весь проект"
python3 .autopilot/ap.py stage architecture skip --note "архитектура проекта принята, этот прогон её не меняет"
```

If its brief does change the architecture: `arch delta` (`phases/2b-architecture.md` §6).

Its brief: `.autopilot/briefs/P03.md` becomes the run's `<дата>-brief.md`. Its manifest atomises only that slice; G4 checks only that slice.

## 5. Moving through the program

`python3 .autopilot/ap.py program` — works without a `state.js` — prints the next runnable row, what waits on what, what is blocked. It is the whole of the top level:

1. **A run lands** → its row is `landed`; the report names the next: «Следующий прогон — “Разговор с автором”. Скажи `/autopilot-ls` в новой сессии — продолжу с него».
2. **A new session, not this one.** A run leaves the orchestrator's context at its heaviest. With the owner's standing permission — asked once, like the night task (`phases/5-night.md`) — a one-off scheduled task a few minutes ahead says `/autopilot-ls` in a fresh session; without it, the owner says it.
3. **`/autopilot-ls` with no unfinished run and a program on disk** → the next row: `init --program P03`, and Phase 1 from its brief file. No row runnable → say why in one line and stop.
4. **After the last row lands** — one blind check of the whole program against `program-brief.md`, exactly as G4 (`phases/8-final.md`), one line per drift into the last run's report.

Night runs never start a new run of the program: the night flies the queue of the run in flight.

## 6. The owner's page

**The owner looks at one page for the whole project and one more for what needs them.** `ap.py` builds both, with the data inside, so they open by double-click: `.autopilot/project/index.html` — where the project stands, the Gantt of runs, the architecture score, what was taken ready-made, each run's report and plan — and `questions.html`, reached from a band at the top.

It rebuilds itself on `init`, `tickets`, `ticket`, `stage`, `tests` and `finish`. The numbers are arithmetic; the sentences are yours, and they are the point:

```bash
python3 .autopilot/ap.py project now --state "Идёт сейчас: разговор с автором" \
  --headline "Бот умеет расспросить автора. Писать пост он ещё не умеет." \
  --sentence "Что сделано, что идёт, что дальше — двумя фразами." --aside "Оговорка, если есть."
python3 .autopilot/ap.py project change "Сдан разговор с автором" --since "с 8 ноября"
python3 .autopilot/ap.py project spend --window "Вся неделя=40" --ceiling 80 --ceiling-label "дальше ночные прогоны не запускаем" --reset-label "Обновится 15 ноября."
python3 .autopilot/ap.py project next-list "12–13 ноября"
python3 .autopilot/ap.py project lint
```

**Every line on these pages is for someone who does not read code.** `project lint` catches requirement codes, branch words, disk paths, anything shaped like a secret. A `!` is fixed in its source before publishing.

**Publish** with the Artifact tool, same address every time, so the link the owner keeps stays good: `file_path` `.autopilot/project/index.html`, `files` `{"questions.html": ".autopilot/project/questions.html"}`, `url` the address from `ap.py project` once there is one. After the first publish: `ap.py project url <адрес>`. No Artifact tool in this harness → name the file.

Publish when a run lands, when the plan is first made, and before every list of questions.

## 7. Questions and manual actions

**The owner is not a bottleneck and not a colleague in the chat.** Questions collect and go in one list every two or three days, or whenever a list has something that truly stops the work.

```bash
python3 .autopilot/ap.py question add --title "Длина реплики: 500 знаков или больше" \
  --about "контекст: откуда вопрос, почему важен" --before "как сейчас (по желанию)" \
  --agrees "на что именно он соглашается" --recommend "что советуем" --why "почему" \
  --silence "что будет, если промолчит" --urgency "Работу не останавливает"
python3 .autopilot/ap.py manual add bank --title "Подписать договор" --only-you "почему этого не может агент" \
  --why "зачем" --step "шаг" --step "шаг" --short "договор"
python3 .autopilot/ap.py question list      # текст для чата: на него можно ответить, не открывая страницу
```

Every field is mandatory because the owner must be able to answer without opening anything else. On the page each question has «Ок, как рекомендуешь» or their own text, and one button copies all the answers into one message. **A decision is only what arrives in the chat**: then `ap.py question answer N --by-user "<их слова>" [--decision "…"]`, `ap.py manual done KEY --by-user "<их слова>"`. Numbers are never reused, so an answer saved in the browser cannot land on a different question.

- **Reversible** → go by the recommendation, record it, keep the card until they have seen it.
- **Write at once only** if all the work is stopped, or it is safety, money beyond what was approved, or something irreversible.
- **When you send the list to the chat**, send the text of `question list`, not a link and a count.
