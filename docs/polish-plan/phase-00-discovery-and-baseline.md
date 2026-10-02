# Phase 0 — Discovery and baseline measurement

**Goal.** Replace the assumptions in this plan with facts about the real app, and
record numbers that later phases can be measured against.

**Changes to app behaviour: none.** This phase only adds documents under
`docs/polish-plan/baseline/` and a query file under `tools/`.

**Prerequisites.** The application source is in the repository. If it is not,
stop: everything downstream depends on it. The repo currently holds only
`README.md`, so the first real action may be getting the app committed.

## Why this phase exists

"Occasional lag" is the hardest class of performance problem to fix blind,
because the cause is usually a query whose cost depends on data volume, and
development data is small. Without a reproduction at realistic volume you cannot
tell an improvement from noise, and a small model asked to "make it faster" will
produce plausible changes with no measurable effect. Every task below exists to
make the lag reproducible and quantified before anything is optimised.

## Guardrails

- Do not fix anything in this phase, even something obviously broken. Write it
  down and move on. Fixes without a baseline cannot be defended.
- Do not run the app against the user's real database without taking a file copy
  first.
- Record real numbers. "Feels faster" is not a measurement.

---

## Task 0.1 — Record the stack facts

**Why.** Phases 1 through 7 each branch on the runtime, the driver, and the
threading model. One document answers all of those once.

**Do.** Copy `docs/polish-plan/STACK.template.md` to `docs/polish-plan/STACK.md`
and replace every `TODO`. Answer from the code and cite a file path for each
answer. Where the code cannot answer it (hardware, expected data volume), write
`unknown — ask user` rather than guessing, and add it to the open questions list.

**Files.** `docs/polish-plan/STACK.md` only.

**Verify.** No `TODO` remains in `STACK.md`. Every row in the "Application shape"
and "Database access" tables has a file path in its evidence column.

**Commit.** `docs: record Warehouse-App stack facts for the polish plan`

---

## Task 0.2 — Inventory every database call site

**Why.** Phase 1 centralises connection handling and Phase 3 moves queries off the
UI thread. Both need a complete list of where SQL enters the app. Code generated
in one pass tends to open connections and inline SQL wherever it was convenient,
so expect the list to be longer than you would guess.

**Do.** Search the source for the driver's API and for SQL keywords, and write
`docs/polish-plan/baseline/data-access-inventory.md` with one row per call site:
file and line, the operation, the SQL (or a reference to it), whether it runs on
the UI thread, and whether it is inside a transaction.

Useful searches, adapted to the stack:

```bash
rg -n --stats -e 'SELECT ' -e 'INSERT ' -e 'UPDATE ' -e 'DELETE ' -e 'CREATE TABLE' -- <source dir>
rg -n -e 'new Database' -e 'sqlite3\.' -e '\.prepare\(' -e '\.exec\(' -e 'connect\(' -- <source dir>
```

Also note, in the same document:

- Every distinct place a connection is opened.
- Any SQL built by string concatenation or interpolation with values that could
  come from user input. Do not fix these now; Phase 8 does, as a set.
- Any query issued inside a loop, which is the N+1 pattern Phase 2 removes.

**Files.** `docs/polish-plan/baseline/data-access-inventory.md` only.

**Verify.** The counts in the document match the `rg --stats` output. Spot-check
three rows against the source.

**Commit.** `docs: inventory database call sites`

---

## Task 0.3 — Extract the app's real queries into a runnable file

**Why.** `tools/sqlite_doctor.py` can explain and time queries, but only the ones
it is given. `tools/warehouse_queries.sql` is a placeholder written against a
demo schema; it must be replaced with the queries this app issues, or every
measurement that follows is measuring the wrong thing.

**Do.** Create `tools/app_queries.sql` in the same format as
`tools/warehouse_queries.sql`: each query preceded by `-- name:` and, where it
takes bind parameters, `-- params:` with a JSON array of realistic values. Cover
at minimum every query that runs while a screen is being displayed or while the
user is typing. Prefer realistic parameter values; a lookup for an id that
matches nothing is not representative.

**Files.** `tools/app_queries.sql` only.

**Verify.**

```bash
python3 tools/sqlite_doctor.py <db> --sql-file tools/app_queries.sql --no-bench
```

Every query parses and produces a plan. No query reports `ERROR:`.

**Commit.** `test: capture the app's real queries for plan analysis`

---

## Task 0.4 — Build a database at realistic volume

**Why.** This is the task that makes the lag reproducible. At development volume
a missing index costs nothing; the whole problem only appears at scale.

**Do.** Produce a database with the row counts from the "Data volume" table in
`STACK.md`, using the app's own schema. Prefer, in order:

1. A copy of the user's real database, if they can supply one.
2. A seed script that inserts generated rows through the app's own schema. Model
   it on `tools/demo_warehouse_db.py`, but use the real schema. Fix the random
   seed so runs are comparable.

Record in `docs/polish-plan/baseline/dataset.md`: how the database was produced,
the exact row counts per table, the file size, and the command to rebuild it.

Do not commit the database file. Add it to `.gitignore`.

**Files.** The seed script, `docs/polish-plan/baseline/dataset.md`, `.gitignore`.

**Verify.** Rebuilding from the recorded command twice produces the same row
counts. `python3 tools/sqlite_doctor.py <db>` reports the expected tables and
counts.

**Commit.** `test: add a realistic-volume seed for the warehouse database`

---

## Task 0.5 — Capture the database baseline

**Why.** A fixed, committed starting point. Phases 1, 2, and 9 all diff against it.

**Do.** Run the diagnostic against the realistic-volume database and save both
forms of the report:

```bash
python3 tools/sqlite_doctor.py <db> --sql-file tools/app_queries.sql --runs 25 \
  > docs/polish-plan/baseline/sqlite_doctor.txt
python3 tools/sqlite_doctor.py <db> --sql-file tools/app_queries.sql --runs 25 --json \
  > docs/polish-plan/baseline/sqlite_doctor.json
```

Then copy the summary counts and each query's median into the results table at
the bottom of this file.

**Files.** `docs/polish-plan/baseline/` only.

**Verify.** Both files exist and are non-empty. The findings summary line is
present in the text report.

**Commit.** `docs: capture database baseline at realistic volume`

---

## Task 0.6 — Build the lag inventory

**Why.** The user reports *occasional* lag. Occasional means triggered by
something. Naming the trigger for each stall is most of the diagnosis, and it is
the part no amount of static code reading will produce.

**Do.** With the realistic-volume database loaded, exercise every screen and
interaction in `STACK.md`. For each one that stalls, record a row in
`docs/polish-plan/baseline/lag-inventory.md`: the interaction, what was on screen,
how long the stall lasted, whether it happens every time or occasionally, and
what it correlates with (row count, first visit versus revisit, a concurrent
write, typing speed).

Measure, do not estimate:

- **Web-based UI** (Electron, Tauri, browser): the browser or Electron DevTools
  Performance panel. Record a profile while reproducing the stall, and note the
  long tasks — any task over 50 ms blocks input. Save the profile export
  alongside the document. `performance.mark()` and `performance.measure()` around
  suspect calls give exact numbers.
- **Python desktop**: wrap the suspect handler in `time.perf_counter()` and log
  the elapsed time, or run under `cProfile` and record the top entries by
  cumulative time.
- **.NET desktop**: the Visual Studio diagnostic tools, or `Stopwatch` around the
  handler.

Pay particular attention to interactions that are fine the first time and slow
later, or vice versa. Those point at cache behaviour or at a write that blocks
reads, rather than at a slow query, and they are the ones Phase 1's WAL change
tends to resolve.

**Files.** `docs/polish-plan/baseline/lag-inventory.md` and any profile exports.

**Verify.** Every row has a measured duration in milliseconds. At least one row
has a reproduction that works every time; if none does, keep going, because an
unreproducible stall cannot be verified as fixed.

**Commit.** `docs: record measured lag inventory`

---

## Task 0.7 — Set the performance budget

**Why.** Without a target, "faster" never terminates. With one, each later task
has a pass or fail condition, which is exactly what a small model needs.

**Do.** Write `docs/polish-plan/baseline/budget.md`. Start from these defaults and
adjust to the hardware recorded in `STACK.md`, justifying any change:

| Thing being measured | Budget |
| --- | --- |
| Any query run during rendering | under 10 ms median at realistic volume |
| Any query run per keystroke | under 5 ms median |
| Visible response to a click or a scan | under 100 ms |
| A screen's data fully loaded | under 300 ms |
| Longest blocking task on the UI thread | under 50 ms |
| Sustained scroll frame rate | 60 fps, no frame over 32 ms |
| Cold start to usable interface | under 2 s |
| High-severity `sqlite_doctor` findings | zero |

The 100 ms figure is the threshold below which a response reads as instantaneous;
the 50 ms task limit is what keeps input handling responsive.

**Files.** `docs/polish-plan/baseline/budget.md` only.

**Verify.** Every row has a number, and every interaction in the lag inventory
maps to at least one row of the budget.

**Commit.** `docs: set the performance budget`

---

## Exit criteria

- [ ] `docs/polish-plan/STACK.md` is complete, with evidence paths and no `TODO`.
- [ ] `docs/polish-plan/baseline/data-access-inventory.md` lists every call site.
- [ ] `tools/app_queries.sql` holds the app's real queries and all of them parse.
- [ ] A realistic-volume database can be rebuilt from a recorded command.
- [ ] `docs/polish-plan/baseline/sqlite_doctor.{txt,json}` are committed.
- [ ] `docs/polish-plan/baseline/lag-inventory.md` has at least one reliably
      reproducible stall with a measured duration.
- [ ] `docs/polish-plan/baseline/budget.md` exists and every row has a number.
- [ ] The results table below is filled in.
- [ ] The stack branches that do not apply have been deleted from phases 1
      through 7.

## Results

Fill this in from Task 0.5 and 0.6. Later phases compare against it.

| Measurement | Baseline |
| --- | --- |
| `sqlite_doctor` high findings | |
| `sqlite_doctor` medium findings | |
| Database file size | |
| Largest table and its row count | |
| Slowest query, and its median | |
| Worst measured stall, and its trigger | |
| Longest blocking UI task | |
| Cold start time | |
