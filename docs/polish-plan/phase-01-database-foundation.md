# Phase 1 — Connection, pragma, and migration foundation

**Goal.** One place that opens the database, correct pragmas on every connection,
and a safe way to change the schema. This is the cheapest latency win in the plan
and the precondition for every schema change that follows.

**Risk.** Low. No query is rewritten and no schema is changed except to add a
version stamp.

**Prerequisites.** Phase 0 complete, including its results table.

## Why this phase is first

Three things here each remove a whole class of intermittent stall:

- **WAL mode** stops a writer from blocking readers. In the default rollback
  journal mode, any write holds an exclusive lock, so a single slow write freezes
  every query feeding the interface. That is the classic shape of lag that is
  "occasional" and never reproduces on demand.
- **A larger page cache and in-memory temp store** stop list renders from
  re-reading pages and stop sorts from spilling to disk.
- **Reused prepared statements** remove per-call SQL parsing and planning, which
  is pure overhead paid on the UI thread.

The migration runner is here rather than later because Phase 2 adds indexes. Any
schema change shipped without a version stamp will either be re-applied or
skipped unpredictably on databases that already exist on users' machines.

## Guardrails

- `journal_mode` is stored in the file and is set once. Every other pragma in
  this phase is per-connection and must be set on **every** connection, every
  time, including short-lived ones.
- Do not change any query's text in this phase.
- Take a copy of the test database before the first migration run.

---

## Task 1.1 — Funnel all database access through one module

**Why.** The pragmas, the statement cache, the migration runner, and Phase 3's
move off the UI thread all have to attach somewhere. If connections are opened in
several places, each of those changes has to be made several times and will be
made inconsistently.

**Do.** Using the inventory from Task 0.2, create a single module that owns the
connection — `db.js`, `db.py`, `Database.cs`, or the equivalent for the stack —
exposing roughly:

- `open()` / `getConnection()`: opens the file, applies the pragmas, runs
  migrations, returns the shared connection.
- `close()`: closes cleanly, including a WAL checkpoint.
- `query(name, params)` and `execute(name, params)`: run a named statement.
- `transaction(fn)`: run `fn` inside a transaction, committing on return and
  rolling back on error.

Then change every call site from the inventory to use it. Move the SQL text, do
not rewrite it. If the inventory has more than about fifteen call sites, split
this across several commits by screen, and note in the commit body which call
sites remain.

**Files.** The new module, plus the call sites listed in the inventory.

**Verify.** `rg` for the driver's connection-opening API returns hits only in the
new module. The app starts and every screen in `STACK.md` still loads.

**Commit.** `refactor: route all database access through a single module`

---

## Task 1.2 — Apply the right pragmas on every connection

**Why.** SQLite's defaults are tuned for compatibility and for being embedded
everywhere, not for a desktop app that wants a responsive interface.

**Do.** In the module from 1.1, immediately after opening and before any other
statement runs:

```sql
PRAGMA journal_mode = WAL;      -- stored in the file; set once, harmless to repeat
PRAGMA busy_timeout = 5000;     -- wait rather than failing with SQLITE_BUSY
PRAGMA foreign_keys = ON;       -- off by default, per connection
PRAGMA synchronous = NORMAL;    -- safe under WAL; removes a flush per commit
PRAGMA cache_size = -16000;     -- negative means KiB, so 16 MiB
PRAGMA temp_store = MEMORY;     -- keep sorts out of temp files
PRAGMA mmap_size = 268435456;   -- 256 MiB; ignored where unsupported
```

Notes that matter:

- Check the result of the `journal_mode` statement. It returns the mode actually
  in effect, and it will not be `wal` if the file is on a network share. Log a
  warning in that case rather than failing silently.
- `foreign_keys` cannot be enabled inside a transaction.
- WAL adds `-wal` and `-shm` sidecar files next to the database. Any backup,
  copy, or "export my data" feature must account for them. The safe way to copy a
  live database is `VACUUM INTO`, used in Task 1.4.
- `synchronous = NORMAL` under WAL survives application and operating-system
  crashes; it risks only the most recent transactions on sudden power loss. If
  the warehouse has unreliable power and losing the last scan is unacceptable,
  keep `FULL` and record that decision here.

**Branch by stack.**

- **Browser-only with `sql.js`:** the database lives in memory, so `journal_mode`
  and `synchronous` do not apply. `cache_size` and `temp_store` still do. The
  dominant cost is serialising the whole database to persist it — Task 1.6 covers
  that. With `wa-sqlite` over OPFS, all of the above applies normally.
- **Tauri / `rusqlite`:** apply the pragmas when building each pooled connection,
  not once at startup, or pooled connections will get the defaults.
- **Python / `sqlite3`:** `connect(..., timeout=5.0)` already sets
  `busy_timeout`; the rest must be issued explicitly as `PRAGMA` statements.

**Files.** The database module only.

**Verify.**

```bash
python3 tools/sqlite_doctor.py <db> --skip-counts --skip-integrity
```

The "Settings stored in the file" section reports `journal_mode wal`. The
per-connection pragmas cannot be verified this way, because the tool reports its
own connection — instead, add a startup assertion or log line that prints each
pragma's value after setup, and paste that output into the commit body.

**Commit.** `perf: enable WAL and tune per-connection SQLite pragmas`

---

## Task 1.3 — Add a migration runner keyed on `user_version`

**Why.** Phase 2 adds indexes and Phase 8 adds a table. Without a version stamp
there is no way to know what a given user's database already has, and the usual
workaround — `CREATE TABLE IF NOT EXISTS` scattered through startup — silently
diverges from the intended schema and cannot handle a column change at all.

**Do.** In the database module, add an ordered list of migrations and a runner:

- Read the current version with `PRAGMA user_version`.
- For each migration with a number greater than the current version, in order:
  begin a transaction, apply it, set `PRAGMA user_version = <n>`, commit.
- If a migration throws, roll back and fail loudly at startup. A half-migrated
  database must not be handed to the interface.
- Migration 1 is the current schema as it exists today, so that a fresh install
  and an existing database converge on the same state. Derive it from
  `sqlite_master`, do not retype it from memory.

Keep each migration as an immutable numbered unit. Never edit a migration that
has shipped; add another one.

`PRAGMA user_version` is a free integer slot in the database header, which is
what makes it the right place for this — it costs nothing and needs no table.

**Files.** The database module, plus a migrations file or directory.

**Verify.** Three checks, with output pasted into the commit body:

1. Against a copy of the Phase 0 database: starting the app sets `user_version`
   to the highest migration number, and `sqlite_doctor` no longer reports
   `NO_SCHEMA_VERSION`.
2. Against an empty file: the app creates the full schema and arrives at the same
   `user_version`. Compare `sqlite_master` between the two; they should match.
3. Starting twice in a row applies nothing the second time.

**Commit.** `feat: add user_version-based schema migrations`

---

## Task 1.4 — Back up before migrating

**Why.** A failed migration on a user's only copy of the warehouse's stock levels
is the worst outcome in this plan. The backup is three lines and removes that
risk.

**Do.** Before the runner applies any migration, write a copy:

```sql
VACUUM INTO 'warehouse-backup-v<old_version>-<timestamp>.db';
```

`VACUUM INTO` produces a consistent single-file copy of a live database without
needing to stop writers, and it compacts as it goes. A plain file copy is not
equivalent, because it can miss the contents of the `-wal` file.

Keep the backups beside the database, prune to the most recent five, and log the
path written.

**Files.** The database module only.

**Verify.** Run a migration against a copy of the Phase 0 database. The backup
file exists, and `python3 tools/sqlite_doctor.py <backup> --deep` reports
`integrity_check: ok` with the pre-migration `user_version`.

**Commit.** `feat: snapshot the database before applying migrations`

---

## Task 1.5 — Prepare statements once and reuse them

**Why.** Preparing a statement parses and plans the SQL. Doing that on every call
is overhead paid on the thread that is trying to draw the interface, and it is
most visible exactly where it hurts most: a query issued per keystroke or per
rendered row.

**Do.** Give the database module a map from statement name to prepared statement,
populated lazily and kept for the connection's life. Change `query`/`execute` to
look up by name. Every piece of SQL in the app becomes a named entry.

Per stack:

- **`better-sqlite3`:** keep the `Statement` objects returned by `prepare()`.
- **Python `sqlite3`:** the module keeps its own statement cache; raise it with
  `connect(..., cached_statements=128)`. Reuse requires passing *identical* SQL
  text, which is another reason to name statements rather than build strings.
- **`rusqlite`:** use `Connection::prepare_cached`.
- **`sql.js` / `wa-sqlite`:** keep the prepared statement and `reset()` plus
  `bind()` it rather than preparing again.

While doing this, confirm every statement takes its values as bind parameters.
Any statement still interpolating a value into its text cannot be cached and is
an injection risk; list those in the commit body for Phase 8 rather than fixing
them here.

**Files.** The database module, and any call site that passed raw SQL.

**Verify.** Add a counter that increments on each `prepare` and log it on exit.
Exercise the slowest screen from the lag inventory twice; the count must not grow
on the second pass. Paste the numbers into the commit body.

**Commit.** `perf: cache prepared statements for the connection's lifetime`

---

## Task 1.6 — Batch writes into single transactions

**Why.** Outside an explicit transaction, SQLite commits every statement
separately, and each commit is a durability barrier. A loop inserting 500 rows
pays that cost 500 times. This is the usual explanation for an import, a stock
take, or a bulk adjustment appearing to hang.

**Do.** Find every loop that writes (the inventory from 0.2 flagged them) and wrap
it in the `transaction()` helper from 1.1, so the whole batch commits once. Also
wrap any multi-statement operation that must not half-apply — a transfer that
decrements one location and increments another is the obvious case. Phase 8
audits these for correctness; here the goal is just to stop paying per-row commit
cost.

**Branch by stack.** For **`sql.js`**, the equivalent problem is persistence: if
the app serialises and writes the entire database after every change, that cost
grows with total database size and will dominate everything. Debounce persistence,
or move to `wa-sqlite` with OPFS, which writes pages rather than the whole file.
Record which was chosen.

**Files.** The call sites that write in a loop.

**Verify.** Time the largest bulk operation before and after against the
realistic-volume database. Paste both numbers into the commit body. Then
interrupt a bulk operation part-way and confirm no partial batch is left behind.

**Commit.** `perf: commit bulk writes in a single transaction`

---

## Task 1.7 — Re-measure

**Why.** Confirms the phase was worth it and establishes the input to Phase 2.

**Do.** Re-run the Task 0.5 commands, saving to
`docs/polish-plan/baseline/after-phase-1.{txt,json}`. Re-walk the lag inventory
and annotate each row with its new duration. Fill in the results table below.

**Files.** `docs/polish-plan/baseline/` and this file.

**Verify.** `WAL_OFF` and `NO_SCHEMA_VERSION` are gone from the findings.

**Commit.** `docs: record measurements after phase 1`

---

## Exit criteria

- [ ] Exactly one module opens the database.
- [ ] Every pragma from 1.2 is applied on every connection, demonstrated by a log.
- [ ] `journal_mode` reports `wal`.
- [ ] Migrations run from `user_version`, are idempotent, and converge from both
      an existing database and an empty one.
- [ ] A backup is written before any migration, and it passes `integrity_check`.
- [ ] Prepared statements are reused; the prepare counter does not grow on a
      second pass over a screen.
- [ ] Bulk writes commit once.
- [ ] `sqlite_doctor` no longer reports `WAL_OFF` or `NO_SCHEMA_VERSION`.
- [ ] The results table below is filled in.

## Results

| Measurement | Phase 0 baseline | After phase 1 |
| --- | --- | --- |
| High findings | | |
| Medium findings | | |
| Slowest query median | | |
| Worst stall from the lag inventory | | |
| Largest bulk write | | |
| Cold start | | |
