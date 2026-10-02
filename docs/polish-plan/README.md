# Warehouse-App polish plan

A phased plan to make the app feel fluid, remove the intermittent lag, and raise
the finish of the interface, while keeping direct SQLite file access instead of a
server.

## Read this before you do anything

**This plan was written without access to the application source.** The
`Warehouse-App` repository currently contains only `README.md`; the app itself
was never committed. Everything here is therefore derived from the constraints
that are known — a warehouse/inventory interface, a local SQLite file opened
directly, occasional lag, and a wish for more polish — plus the failure modes
that are near-universal in that architecture.

Two consequences:

1. **Phase 0 is not optional.** It replaces the guesses with facts about the real
   code, and every later phase reads the notes Phase 0 produces. Do not skip it
   or work phases out of order.
2. **Later phases contain branches by stack** (Electron, Tauri, browser-only
   with `sql.js`/`wa-sqlite`, Python desktop, .NET desktop). Phase 0 decides
   which branch applies. Delete the branches that do not apply so the executor
   is never choosing between them.

## Who executes this

The plan is written to be run by a smaller, cheaper model, one task at a time.
That shapes the format: every task names the files it may touch, states a single
change, and gives a command or observation that proves the change worked. No task
requires holding the whole codebase in mind.

### Rules for the executing model

Follow these exactly. They exist because the most common failure mode for a
small model on a large codebase is confident, unverified, out-of-scope change.

1. **One task per session.** Read this file and the one phase file you are
   working in. Do not read ahead.
2. **Do not start a phase until the previous phase's exit criteria are all
   checked off** in its file.
3. **Stay inside the task's file list.** If the change seems to require editing a
   file the task does not name, stop and report that instead of editing it.
4. **Run the task's verification step before committing.** If verification
   fails, revert with `git checkout -- <files>` and report what happened. Do not
   substitute a different fix.
5. **One commit per task**, using the commit message the task supplies.
6. **Add no dependencies** unless the task names the exact package.
7. **Change no schema outside a migration task.** Schema changes go through the
   migration runner built in Phase 1, never as a direct `ALTER TABLE` in app code.
8. **If the code does not match what the task describes, stop and report.** The
   task was written from assumptions; a mismatch means the assumption was wrong
   and a human should re-scope it. Guessing here is how a plan silently stops
   applying to the real app.
9. **Write measured numbers into the results table** at the bottom of each phase
   file. Later phases compare against them.
10. **Never widen scope.** No drive-by refactors, renames, formatting sweeps, or
    "while I was in here" fixes. They make the diff unreviewable and hide the
    change that mattered.

### Definition of done for any task

- The change is made, and only that change.
- The verification step was run, and its real output is pasted into the commit
  body or the phase file.
- The app still starts and the affected screen still works.
- One commit, message as specified.

## Phase map

Phases 1 through 3 are where the lag lives. Phases 4 and 5 are where the app
starts to *feel* fast. Phases 6 and 7 are the visual and ergonomic finish.
Phases 8 and 9 keep it from regressing.

| Phase | Title | Depends on | Changes behaviour? |
| --- | --- | --- | --- |
| [0](phase-00-discovery-and-baseline.md) | Discovery and baseline measurement | — | No |
| [1](phase-01-database-foundation.md) | Connection, pragma, and migration foundation | 0 | Low risk |
| [2](phase-02-query-and-index-layer.md) | Query and index layer | 1 | Low risk |
| [3](phase-03-off-thread-data-access.md) | Off-thread data access | 1, 2 | Yes |
| [4](phase-04-rendering-performance.md) | Rendering performance | 3 | Yes |
| [5](phase-05-perceived-performance.md) | Perceived performance | 3, 4 | Yes |
| [6](phase-06-visual-design-system.md) | Visual design system | 4 | Visual only |
| [7](phase-07-accessibility-and-input.md) | Accessibility and input ergonomics | 6 | Yes |
| [8](phase-08-data-integrity-and-reliability.md) | Data integrity and reliability | 1, 2 | Yes |
| [9](phase-09-regression-guardrails.md) | Regression guardrails | all | No |

Phases 6 and 7 are independent of 8. If two people or two sessions are working
in parallel, that is the safe split.

## Why the order is what it is

The instinct with "the app feels laggy and looks unfinished" is to start with the
interface. That order wastes work here. Query cost in this architecture is paid
on or next to the UI thread, so a slow query *is* a dropped frame. Virtualising a
list that is waiting 300 ms for its data just makes an empty list scroll
smoothly. So the data path is fixed first (1 through 3), then rendering (4),
then the perception of speed (5), and only then appearance (6, 7).

The exception is Phase 1's migration runner, which comes early for a different
reason: without a schema version, every later index and column change risks
breaking databases that already exist on real machines.

## Keeping direct SQLite access

This plan assumes no server, by requirement. Direct file access is a good fit for
a single-site warehouse app, and nothing in Phases 1 through 9 moves away from
it. Two consequences are worth stating so they are not rediscovered later:

- **One writer at a time.** SQLite allows many concurrent readers but a single
  writer. WAL mode (Phase 1) stops writers from blocking readers, which is the
  main source of intermittent stalls in this setup. It does not make concurrent
  writes possible.
- **A file on a network share is not safe.** SQLite's locking is unreliable over
  SMB and NFS. If two machines ever need to write, that is the point at which
  this architecture has to change, and it is a deliberate decision rather than
  something to work around. Phase 0 records whether the file is local.

## Tooling that ships with this plan

`tools/sqlite_doctor.py` is a read-only diagnostic for the database: it reports
the pragmas in effect, flags unindexed foreign keys, redundant indexes, missing
statistics and absent schema versioning, runs `EXPLAIN QUERY PLAN` over the
queries the app actually issues, and times them. It is stdlib-only and cannot
modify the database.

```bash
# Full report plus plans and timings for the app's real queries
python3 tools/sqlite_doctor.py path/to/warehouse.db --sql-file tools/app_queries.sql

# Machine-readable, for saving a baseline to compare against later
python3 tools/sqlite_doctor.py path/to/warehouse.db --json > baseline.json

# Gate for CI, used in Phase 9
python3 tools/sqlite_doctor.py path/to/warehouse.db --fail-on high
```

`tools/demo_warehouse_db.py` builds a demo database at realistic volume in two
shapes, `--mode untuned` and `--mode tuned`. It is a fixture for exercising the
diagnostic, **not** the app's schema. It exists so the tooling can be trusted
before it is pointed at real data. Running the diagnostic across both shapes shows
what Phases 1 and 2 are worth: on 150,000 movement rows the item-history query
goes from about 4.4 ms to about 0.01 ms, and the high-severity findings drop from
14 to 1. Absolute timings are specific to the machine; the ratios are the point.

See `tools/README.md` for details.
