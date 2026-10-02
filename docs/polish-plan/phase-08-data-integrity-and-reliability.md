# Phase 8 — Data integrity and reliability

**Goal.** Make the database trustworthy. A warehouse app whose stock figures can
be wrong is worse than one that is slow, and the failure modes below are the ones
a single-pass generated app most often misses.

**Risk.** Moderate. Transaction boundaries and an audit log change how writes
behave.

**Prerequisites.** Phases 1 and 2 complete. Migrations and the central module
exist. This phase is independent of Phases 6 and 7 and can run in parallel with
them.

## Why this belongs in a polish plan

Most of these are invisible until they are not, and then they are expensive: a
transfer that credits one location without debiting the other, a quantity that
cannot be explained because nothing recorded why it changed, a corrupted file with
no backup. Each is cheap to prevent now and effectively unfixable after the fact,
because the information needed to reconstruct the truth was never written down.

## Guardrails

- Every schema change is a migration. No exceptions.
- Test every one of these against a copy, never the user's only database.
- Do not conflate a write failing with a write being rejected. A constraint
  violation is an expected outcome needing a message; a disk error is not.

---

## Task 8.1 — Make multi-step operations atomic

**Why.** A stock transfer is two writes: decrement here, increment there. If the
process dies between them, inventory is wrong in a way no one will notice until a
count, and no one will be able to explain. SQLite gives atomicity for free inside a
transaction; outside one, each statement commits alone.

**Do.** Find every operation that writes more than once and wrap it in the
`transaction()` helper from Phase 1 so it either fully applies or does not apply
at all. In this app that is at least: transfers, receiving against a purchase
order, adjustments that also write history, anything cascading to a child table,
and any import.

Keep transactions short — they hold the write lock, and SQLite allows one writer
at a time, so a long transaction stalls every other write. Do no I/O, no user
interaction, and no waiting inside one. In particular never open a confirmation
dialog mid-transaction.

Use `IMMEDIATE` for transactions that will certainly write. A deferred transaction
takes its write lock at the first write, which means it can fail with
`SQLITE_BUSY` part-way through after doing work; `IMMEDIATE` fails at the start
instead, where retrying is simple.

**Files.** The operations that write more than once, one per commit.

**Verify.** For each operation, induce a failure at the midpoint — raise after the
first statement — and confirm the database is unchanged afterwards. Record a
before-and-after row count or sum for each.

**Commit.** `fix: make <operation> atomic`

---

## Task 8.2 — Parameterise every query

**Why.** SQL assembled by string concatenation is both an injection route and a
correctness problem: a SKU containing an apostrophe breaks the query, and a
maliciously or accidentally crafted value can do worse. Generated code often
interpolates values into SQL because it reads more naturally.

**Do.** Take the list produced in Task 1.5 and convert each one to bind
parameters. For every value, `?` and a bound argument.

Identifiers cannot be bound — a table or column name has to be interpolated. Where
a sort column or direction is chosen by the user, validate against an explicit
allow-list of permitted names and reject anything else. Never pass the value
through. For `IN` lists, generate the right number of `?` placeholders and bind
each value.

While here, add input validation at the boundary: quantities are integers within a
sensible range, SKUs match their expected shape, dates parse, text fields have
length limits. Rejecting bad input with a clear message is better than storing it.

**Files.** The statements identified, plus a validation module.

**Verify.** `rg` for string concatenation or interpolation adjacent to SQL
keywords returns nothing outside the validated identifier cases. Then enter
`'); DROP TABLE items; --` and `O'Brien` into every text field and confirm both
are stored and displayed literally with no error.

**Commit.** `fix: parameterise all queries and validate input`

---

## Task 8.3 — Record stock movements in an append-only log

**Why.** The question a warehouse always eventually asks is "why is this number
what it is". If the app only stores current quantities, that is unanswerable. An
append-only log of changes makes every figure reconstructible and turns a
discrepancy into an investigation instead of a mystery.

**Do.** Skip if an equivalent table already exists; verify instead that it is
written in the same transaction as the quantity change, which is the part usually
missed.

Otherwise add, in a migration, a table recording for every quantity change: when,
which item, which location (from and to where it is a transfer), the delta, the
resulting quantity, who or what caused it, and a reason or reference. Write it in
the same transaction as the change itself — a log that can disagree with the data
is worse than none.

Treat it as append-only: never update or delete a row. A correction is a new
compensating row. Index it on `(item_id, recorded_at)` so history for one item
seeks rather than scans, which is the index Phase 2 would have added anyway.

Then add a view showing an item's history, which is the feature this enables and
the thing that makes the log worth its cost.

**Files.** The migrations file, the write path, and a history view.

**Verify.** Perform ten movements of different kinds and confirm replaying the log
from zero reproduces the current quantity exactly for every item affected. Paste
the comparison. Confirm an interrupted movement leaves neither a quantity change
nor a log row.

**Commit.** `feat: append-only stock movement log`

---

## Task 8.4 — Handle a damaged or locked database

**Why.** These are the two ways a local SQLite app fails in the field, and the
default behaviour for both is an unhandled exception at startup with no
explanation, which is indistinguishable from the app being broken.

**Do.** Three cases.

**Corruption.** Run `PRAGMA quick_check` at startup when the app did not shut down
cleanly — track a clean-shutdown flag. On failure, do not write. Explain what
happened, offer to restore the most recent backup from Task 1.4, and name the file.

**Locked.** With `busy_timeout` from Phase 1, a lock usually resolves. When it does
not, catch the busy error and retry a few times with increasing delay, then tell
the user that another copy of the app may be running, which is the usual cause.

**Missing or unreadable.** A missing file is a first run: create and migrate it. A
file that exists but cannot be opened — permissions, a half-written download, a
disconnected network share — is a different message. Distinguish them; treating a
permissions error as a first run can overwrite real data.

Also handle the disk being full, which on a write surfaces as a distinct error and
should say so rather than appearing as a generic save failure.

**Files.** The database module's startup path.

**Verify.** Induce each case against copies and confirm the message and the
recovery path: truncate a copy mid-file for corruption, hold a write lock from
another process, remove read permission, point at a nonexistent path. Record the
message shown for each.

**Commit.** `feat: handle corrupt, locked, and unreadable databases`

---

## Task 8.5 — Back up on a schedule and verify the backups

**Why.** Task 1.4 protects against a bad migration. This protects against
everything else: corruption, a mistaken bulk edit, hardware failure. An unverified
backup is a guess.

**Do.** Write a backup with `VACUUM INTO` on a schedule — daily on first launch is
enough for most sites — keeping a rotation of the last seven plus one per month.
`VACUUM INTO` produces a consistent copy of a live database and compacts it, which
a plain file copy cannot do safely because it may miss the `-wal` contents.

After writing each backup, open it and run `PRAGMA quick_check`. If it fails,
delete it and warn, rather than keeping a backup that cannot be restored.

Then build the restore path, and make it reachable from the interface. A backup
with no tested restore is not a backup. Restoring must itself take a backup of the
current state first, so a mistaken restore is recoverable.

**Files.** A backup module and its settings view.

**Verify.** Let a backup run, confirm it passes `quick_check` and that
`python3 tools/sqlite_doctor.py <backup> --deep` reports `integrity_check: ok`.
Then restore it into a scratch copy and confirm the data matches. Confirm rotation
prunes correctly by running it repeatedly with the date advanced.

**Commit.** `feat: scheduled verified backups with a restore path`

---

## Task 8.6 — Surface errors instead of swallowing them

**Why.** A caught-and-ignored error is the reason a bug reported as "it sometimes
doesn't save" cannot be diagnosed. On a local app there are no server logs to fall
back on.

**Do.** Find the silent handlers:

```bash
rg -n -A2 'catch\s*\([^)]*\)\s*\{\s*\}' -- <source dir>
rg -n -A2 'except[^:]*:\s*$' -- <source dir>
rg -n 'except\s*:\s*pass|catch\s*\{\s*\}' -- <source dir>
```

For each, either handle it meaningfully or let it propagate. Add a top-level
handler that catches what reaches it, writes to a rotating local log file with a
timestamp and a stack trace, and shows the user a message that says what failed
and whether their data was saved — which is the only question they actually have.

Make the log reachable from the interface, with a way to copy or export it for a
support request. Keep values out of the log where they could be sensitive; an item
id is fine, a full row dump is usually unnecessary.

Add an error boundary per screen if the framework supports one, so a failure in one
view does not blank the whole window.

**Files.** The handlers found, plus a logging module and the log viewer.

**Verify.** The searches return no empty handlers. Induce a failure in each screen
and confirm the app stays usable, the message states whether data was saved, and
the log contains the trace. Record the messages.

**Commit.** `fix: log and surface errors instead of swallowing them`

---

## Exit criteria

- [ ] Every multi-step operation is atomic, each proven by a mid-point failure test.
- [ ] Transactions contain no I/O or user interaction.
- [ ] No SQL is assembled from unvalidated input; injection strings store literally.
- [ ] Input is validated at the boundary with clear rejection messages.
- [ ] An append-only movement log exists, written in the same transaction, and
      replaying it reproduces current quantities exactly.
- [ ] An item's history is viewable in the interface.
- [ ] Corrupt, locked, unreadable, and missing databases each produce a distinct
      message and a recovery path.
- [ ] Backups run on a schedule, are verified after writing, rotate, and restore.
- [ ] No empty exception handler remains.
- [ ] Errors are logged locally and the log is reachable from the interface.
- [ ] `sqlite_doctor --deep` reports `integrity_check: ok` and zero foreign key
      violations.

## Results

| Check | Result |
| --- | --- |
| Operations made atomic | |
| Mid-point failure tests passed | |
| Queries parameterised | |
| Movement log replay matches current quantities | |
| Failure modes handled, with messages | |
| Backup verified and restored | |
| Empty handlers removed | |
