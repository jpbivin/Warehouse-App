# Phase 9 — Regression guardrails

**Goal.** Make the gains from Phases 1 through 8 permanent. Performance work
decays silently: the next feature adds a query in a loop, and six months later the
app is slow again with no single commit to blame.

**Risk.** None to the app. This phase adds tests and checks.

**Prerequisites.** Phases 1 through 8, or at least 1 through 5.

## Why now rather than earlier

A performance test needs a target to assert against, and the targets come from the
measurements taken in each phase. Written earlier, the thresholds would have been
guesses. Written now, every one of them is a number the app has actually achieved.

The important property of these checks is that they fail on the commit that causes
the regression, not months later when someone notices. A check that runs only when
someone remembers to run it provides nothing.

## Guardrails

- Thresholds come from the recorded results, with headroom. A test that fails
  intermittently will be disabled, and then it protects nothing.
- Tests must not need a developer's machine. Everything is seeded from a script.

---

## Task 9.1 — Make the test database reproducible

**Why.** Every check below needs the same data every time. A test against
whatever happens to be in the developer's database is not a test.

**Do.** Promote the Phase 0 seed script into test infrastructure: a fixed random
seed, a deterministic row count, and a single command that produces the database
from nothing. Add a smaller variant for fast unit tests and keep the full-volume
one for the performance checks.

Assert the determinism, because a seed script that drifts invalidates every
threshold in this phase: generate twice and compare row counts and a checksum of
the sorted contents of each table.

**Files.** The seed script and the test setup.

**Verify.** Generating twice produces identical checksums. A clean checkout plus
one command yields a usable test database.

**Commit.** `test: make the seeded test database reproducible`

---

## Task 9.2 — Assert the query plans

**Why.** This is the highest-value and least obvious check in the phase. An index
can be dropped, or a query edited so it can no longer use one, and nothing fails —
the app just gets slower as data grows. Asserting the plan catches it at the
commit that caused it, and unlike a timing test it is not flaky, because the plan
is deterministic.

**Do.** For each query in `tools/app_queries.sql`, add a test that runs
`EXPLAIN QUERY PLAN` and asserts on the result:

- No step is a bare `SCAN <table>` without an index, except where the query is
  documented as legitimately needing a full scan.
- No step mentions an `AUTOMATIC` index.
- No `USE TEMP B-TREE` for any query that has a `LIMIT`.
- For the queries that matter most, assert the specific index name, so dropping or
  renaming it fails loudly.

Run against the full-volume database, since the planner's choices depend on the
statistics.

**Files.** A new test file.

**Verify.** The tests pass. Then prove each one works: drop an index locally,
confirm the relevant test fails, restore it. A test that cannot be made to fail is
not testing anything.

**Commit.** `test: assert query plans use indexes`

---

## Task 9.3 — Add a performance smoke test

**Why.** Catches the regressions a plan assertion cannot: a query in a loop, a
newly chatty screen, a write that got slower.

**Do.** Add a test that, against the full-volume database, runs each query from
`tools/app_queries.sql` a fixed number of times and asserts the median is within
the budget from `budget.md`. Use the median rather than the mean, discard the first
run as a warm-up, and set the threshold with generous headroom — two to three times
the measured value — so it catches a real regression and not CI noise.

Add a second assertion on the number of queries a screen issues, which is far more
stable than timing and catches the N+1 pattern directly: count the statements
executed while rendering each screen and assert the count is a constant, not a
function of row count.

**Files.** A new test file, plus a counting hook in the database module.

**Verify.** The tests pass. Then prove they work: add a query inside a row loop,
confirm the count assertion fails, remove it.

**Commit.** `test: assert query timings and per-screen query counts`

---

## Task 9.4 — Run the diagnostic in CI

**Why.** Catches schema regressions directly — a migration that adds a foreign key
without an index, or a table that grows past the point where it needs one.

**Do.** Add a CI job that builds the seeded database and runs:

```bash
python3 tools/sqlite_doctor.py <db> --sql-file tools/app_queries.sql --fail-on high
```

`--fail-on high` exits non-zero when any high-severity finding is present, so the
build fails. The per-connection pragma checklist the tool prints is deliberately
excluded from the gate, because it cannot be checked from outside the application;
cover those with a unit test on the module from Phase 1 that asserts each pragma's
value after `open()`.

If any high-severity finding is a documented, accepted exception, record it in the
job configuration with the reason rather than lowering the gate.

**Files.** The CI configuration.

**Verify.** The job passes on the current tree. Then push a branch that drops an
index and confirm the job fails. Link both runs.

**Commit.** `ci: fail the build on high-severity database findings`

---

## Task 9.5 — Write down the rules that keep it fast

**Why.** The plan's phase files describe one-time work. What survives is a short
list of rules applied to every future change — including by the next agent, which
will read `AGENTS.md` and nothing else.

**Do.** Add a short section to `AGENTS.md` (creating it if absent) and to the
project README covering:

- All database access goes through the module from Phase 1. Never open a
  connection elsewhere.
- Every schema change is a numbered migration. Never edit a shipped migration.
- Every new query is added to `tools/app_queries.sql` with a plan assertion.
- No query on the UI thread.
- No query inside a loop over rows.
- New colours, spacing, and type sizes come from the tokens.
- Animate only `transform` and `opacity`.
- Run `python3 tools/sqlite_doctor.py <db> --fail-on high` before opening a PR.
- The performance budget, inline, with the measured figures.

Keep it to one screen of text. A long document is not read.

**Files.** `AGENTS.md` and `README.md`.

**Verify.** Have a fresh session read only `AGENTS.md` and add a trivial query.
It should put the SQL in the right module, add it to `app_queries.sql`, and add a
plan assertion without being told. If it does not, the document is not clear
enough — revise it.

**Commit.** `docs: record the rules that keep the app fast`

---

## Exit criteria

- [ ] The test database is reproducible from one command, with asserted
      determinism.
- [ ] Every query has a plan assertion, and each was proven to fail when its index
      is dropped.
- [ ] Query timings and per-screen query counts are asserted against the budget.
- [ ] The per-screen count assertion was proven to fail on an introduced N+1.
- [ ] `sqlite_doctor --fail-on high` runs in CI and was proven to fail on a
      dropped index.
- [ ] Pragma values are asserted by a unit test on the database module.
- [ ] `AGENTS.md` records the rules, and a fresh session follows them unaided.

## Final results

Copy the figures from each phase's results table so the whole improvement is
visible in one place.

| Measurement | Phase 0 baseline | Final | Budget |
| --- | --- | --- | --- |
| High-severity findings | | | 0 |
| Slowest query median | | | |
| Queries per screen render | | | |
| Longest UI-thread task | | | under 50 ms |
| Longest frame while scrolling | | | under 32 ms |
| Scan to acknowledgement | | | under 100 ms |
| Cold start to usable | | | under 2 s |
| Worst stall from the lag inventory | | | |
