# Phase 5 — The night run

Read only when `/autopilot-ls night` started the session — a scheduled task says it, the owner rarely does. First `phases/0-resume.md` as for any resume, then this file instead of asking anything. **A night run never asks**: everything that would be a question goes into the morning report, and the work it blocks waits.

## What flies

```bash
python3 .autopilot/ap.py night start      # строит очередь и открывает ночь
```

- **Only the queue** — tickets with `night_ok`, whose parents are landed or ahead of them in it (`ap.py queue` shows the order and why each other ticket is out). `ap.py` refuses to start anything else while the night is open.
- **The day's rules, unchanged** — worktree per executor, the check and the gates, repair caps, point reviews (`phases/5-subagents.md`), and the pacing rules there before every launch.
- **Hard stop after the first `failed`.** `ticket NN fail` closes the night by itself: nothing new launches, tickets in flight finish and land or are reset, dependents are not touched. A second failure at night costs a day of the owner untangling two.
- **A ticket that needs the owner** — `BLOCKED` on a decision, a method question, an outward action — is not a failure: `ap.py ticket NN reset`, `ap.py queue drop NN --note "что нужно от владельца"` (its dependents leave the queue with it), one line for the report, and on to the next.
- **Nothing outward, ever** — no push, no deploy, no message to anyone. A morning message to the owner in Telegram only if the project memory records their standing permission in their own words.
- **A budget the owner set** — at 85 % of the 5-hour window the night **pauses** (`ap.py pacing` sets it; a one-off task at the reset + 5 minutes says `/autopilot-ls night` again, and `night start` resumes it); at `pacing.night_weekly_max_pct` of the weekly limit spent since the night began it **stops** for good — the owner's number, written with `ap.py pacing --night-weekly-max-pct N`; unset, 15 % (`phases/5-subagents.md`, «Pacing»).

## After the queue

If the window allows, the slow checks no ticket pays for: the full mutation run (`make gates` without `CHANGED`), once the queue is empty and nothing else runs gates, with `LS_GATES_JOBS` workers — survivors to `ap.py add concerns`; the L2 replay of `phases/8a-e2e.md` when `E2E_MAX_USD` is set — a regression becomes a ticket for the day, never a night repair.

## The morning report

`.autopilot/<dir>/night-<YYYY-MM-DD>.md`, in Russian, from `state.js` → `night`, `queue` and `pacing`, re-read now:

```markdown
# Ночь на 2026-11-08 — <проект>

## Сделано
- Бот сохраняет черновик после каждого шага — таск 04, тесты 112/0, проверки качества зелёные

## Упало
- Таск 06 — экспорт: порт 8080 занят другим процессом. Зависимые 07, 08 не трогал

## Нужно от тебя
1. Обзор промпта коуча v1.3 — `.autopilot/<папка>/prompt-reviews/05-coach.html`: открой, ответь в чате «ок» или комментариями
2. Методика этапа 3: сколько вопросов до перехода к черновику? Ждут таски 09, 10

## Цифры
Окно: 41 % → 83 % · неделя: +9 % (кап 15 %) · тасков: 3 сделано, 1 упал, 2 ждут тебя
```

Sections with nothing in them say «—». Then `ap.py night end --report night-<дата>.md` and stop: the session ends with the report, not with a question.

## Starting it

The night run is a **local scheduled task of Claude Code Desktop** — it sees the local repo, the gates and `.env`; it runs while the app is open, and if the app was closed, at its next launch. Creating one is persistent configuration: **ask the owner once** (`ap.py ask action --note "ночная задача autopilot-ls в 01:00"`), and record their yes, in their words, in «Договорились» of `PROGRESS.md`. The same answer covers the one-off «продолжить после сброса окна» tasks of the pacing rules — say so in the question.

```
create_scheduled_task({ taskId: "autopilot-ls-night-<slug>", cronExpression: "0 1 * * *",
  description: "Ночная очередь autopilot-ls для <проект>",
  prompt: "/autopilot-ls night\nПроект: <абсолютный путь>. Перейди в эту папку. Продолжи сборку autopilot-ls в ночном режиме по phases/5-night.md: только очередь, без вопросов, стоп после первого упавшего, ничего наружу, утром — night-<дата>.md. Если команда /autopilot-ls не сработала, прочитай ~/.claude/skills/autopilot-ls/SKILL.md и phases/5-night.md и следуй им." })
```

- The task starts fresh, with no memory: the prompt carries the path and the rules, because nothing else will. It may stall on a permission prompt nobody answers — the owner chooses the permission mode it is saved in, not you.
- **`/schedule` (cloud routines) is not for this project's nights**: it needs the repo on GitHub and runs without the local `.env`, and the corpus here is people's private dialogues. Only for work with no private data and no keys — docs, a rename.
- `/loop` lives inside one session and dies with it — for polling a board within a working day (`phases/5-sessions.md`), never for the night.
