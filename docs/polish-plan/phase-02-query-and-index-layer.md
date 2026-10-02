# Phase 2 — Query and index layer

**Goal.** Every query the interface runs should seek to the rows it needs instead
of reading the table. This is where most of the remaining lag disappears.

**Risk.** Low to moderate. Indexes are additive and reversible. The search and
pagination rewrites change query text and need their results checked against the
old behaviour.

**Prerequisites.** Phase 1 complete. The migration runner exists — every index in
this phase ships as a migration, never as an ad-hoc statement.

## How to work in this phase

`EXPLAIN QUERY PLAN` is the arbiter, not intuition. The vocabulary you need:

| Plan text | Meaning |
| --- | --- |
| `SEARCH … USING INDEX` | Seeks straight to matching rows. The goal. |
| `SEARCH … USING COVERING INDEX` | Better still: answered from the index alone. |
| `SCAN <table>` | Reads every row. Cost grows with the table. |
| `SCAN <table> USING INDEX` | Reads the whole index. Cheaper, still linear. |
| `USE TEMP B-TREE FOR ORDER BY` | Sorts the whole result before returning a row. |
| `AUTOMATIC COVERING INDEX` | SQLite built an index for this one query and threw it away. Always means a missing permanent index. |
| `SCAN … VIRTUAL TABLE INDEX` | Normal and fast for FTS. Not a problem. |

Run the diagnostic after each task and watch the findings count fall:

```bash
python3 tools/sqlite_doctor.py <db> --sql-file tools/app_queries.sql --runs 25
```

For scale, on the demo database of 150,000 movement rows, adding the indexes in
this phase takes the item-history query from about 4.4 ms to about 0.01 ms, and
the paginated inventory query from about 2.9 ms to about 0.04 ms. Those are the
effects being chased. Absolute figures depend on the machine; compare ratios.

## Guardrails

- One index per migration, or one coherent group per migration.
- Never add an index without a plan output that shows it being used. An unused
  index is a permanent tax on every write.
- Do not change what a query *returns* except in the two tasks that say so, and
  in those, diff the results against the old query.

---

## Task 2.1 — Index every unindexed foreign key

**Why.** This is the single highest-value change in the phase. An unindexed
foreign key forces a full scan of the child table on every join across it, and
another full scan of the child table on every delete from the parent, to enforce
the constraint. It is the reason a list view is instant on test data and slow on
real data. SQLite indexes the parent side automatically and the child side never.

**Do.** Take the `UNINDEXED_FOREIGN_KEY` findings from the Phase 0 baseline
report; the tool prints the exact `CREATE INDEX` statement for each. Add them as
one migration.

**Files.** The migrations file only.

**Verify.** `sqlite_doctor` reports zero `UNINDEXED_FOREIGN_KEY` findings. Record
the before and after medians of every affected query in the results table.

**Commit.** `perf: index foreign key columns`

---

## Task 2.2 — Index to match each list view's filter and sort

**Why.** `USE TEMP B-TREE FOR ORDER BY` means SQLite materialises and sorts the
entire result set before it can return the first row. A screen showing fifty rows
pays for sorting all of them. An index whose column order matches the `ORDER BY`
lets the rows arrive already ordered, so `LIMIT` stops the work early.

**Do.** For each query in `tools/app_queries.sql` whose plan shows a temporary
B-tree, add an index on the filter columns followed by the sort columns, in that
order. Equality filters come first, then the range or sort column. Column order
is what matters: an index on `(a, b)` serves `WHERE a = ? ORDER BY b` and does
nothing for `WHERE b = ?`.

Where the query selects only a few columns, consider appending them to the index
so it can be answered from the index alone — the plan then reports `COVERING
INDEX`. Weigh that against the extra write cost; it is worth it for a query that
runs on every render and rarely worth it otherwise.

Two things that silently prevent an index from being used:

- A function applied to the indexed column: `WHERE lower(name) = ?` cannot use an
  index on `name`. Either store a normalised column or create an index on the
  expression.
- A leading-column mismatch, as above.

**Files.** The migrations file only.

**Verify.** For each query changed, paste the plan before and after. No
`USE TEMP B-TREE` remains for any query that has a `LIMIT`.

**Commit.** `perf: add composite indexes matching list view sort order`

---

## Task 2.3 — Replace substring search with FTS5

**Why.** `WHERE name LIKE '%term%'` cannot use an index — the leading wildcard
means every row has to be examined. In a search box that queries per keystroke,
every keystroke costs a full table scan, which is felt directly as typing lag.

**Do.** Skip this task if the app has no text search, or if its search is
prefix-only — `LIKE 'term%'` without the leading wildcard *can* use an index, so
in that case just add the index and move on.

Otherwise, add in one migration:

- An FTS5 virtual table over the searchable columns, declared as an external
  content table (`content='items', content_rowid='id'`) so the text is not stored
  twice and the base table stays the source of truth.
- A backfill from the existing rows.
- `AFTER INSERT`, `AFTER DELETE`, and `AFTER UPDATE` triggers to keep it in sync.

`tools/demo_warehouse_db.py` contains a complete worked example of all three
parts; copy its structure and substitute the real table and columns.

Then change the search query to `WHERE <fts_table> MATCH ?` joined back to the
base table on `rowid`. Note that user input needs escaping for FTS5 syntax: a
bare `-` or `"` in the query string is an operator. Quote each term, or strip
syntax characters.

Decide and record what happens to mid-word matching. FTS5 matches whole tokens
and prefixes, so searching `sleeve` finds "stainless sleeve" but searching `leev`
no longer finds it. If mid-word matching is a requirement, use a trigram
tokeniser (`tokenize='trigram'`) instead, which supports it at the cost of a
larger index.

**Files.** The migrations file, and the search query's statement.

**Verify.** Run twenty representative searches against the old and new
implementations and diff the result sets. Differences must be explained by the
tokenisation change above, not by bugs. Record the per-keystroke query median
before and after; on the demo database the equivalent change takes search from
about 1.6 ms to about 0.03 ms.

**Commit.** `perf: search items through an FTS5 index`

---

## Task 2.4 — Replace `OFFSET` pagination with keyset pagination

**Why.** `LIMIT 50 OFFSET 10000` makes SQLite walk and discard 10,000 rows to
produce 50. The cost grows the further the user scrolls, which produces the
distinctive symptom of a list that is fine at the top and slow further down.
Keyset pagination seeks directly to the position instead, so every page costs the
same.

**Do.** Skip if the app never paginates past the first page or uses no `OFFSET`.

Otherwise, change each paginated query to carry the last row's sort key forward:

```sql
-- instead of: ORDER BY name LIMIT ? OFFSET ?
SELECT … WHERE (name, id) > (?, ?) ORDER BY name, id LIMIT ?;
```

The `id` tiebreaker is required: without it, rows with equal sort keys can be
skipped or repeated across page boundaries. The supporting index must be on
`(name, id)`, matching Task 2.2.

Keyset pagination gives up random page access — there is no "jump to page 7". For
a scrolling list that is not a loss. If the interface shows numbered pages, either
change it to infinite scroll, or keep `OFFSET` only for the page-number control
and record the decision.

Also check for the related pattern of a `COUNT(*)` over the whole table on every
render to compute a total. That is a full scan too. Show "50+" or cache the count
and refresh it on write.

**Files.** The paginated statements and the code that tracks scroll position.

**Verify.** Page through the entire realistic-volume list and confirm no row is
skipped or duplicated — compare the collected ids against a single unpaginated
query. Record the median for the first page and for a deep page; they should now
be the same.

**Commit.** `perf: paginate lists by sort key instead of OFFSET`

---

## Task 2.5 — Eliminate queries issued per row

**Why.** A query per rendered row means fifty round trips for a fifty-row screen.
Each is individually fast, which is what makes this pattern survive review, and
together they are the slowest thing on the screen.

**Do.** For each loop-with-a-query flagged in Task 0.2, replace it with one query:

- A `JOIN` where the related row belongs to the same entity.
- `WHERE id IN (…)` with the collected ids, then group in application code, where
  the relationship is one-to-many.
- A window function or a `GROUP BY` where the per-row value is an aggregate.

Build the `IN` list from bind placeholders, never by interpolating the ids. Note
that SQLite caps bound parameters (999 in older builds, 32,766 in newer); chunk
if a list can exceed that.

**Files.** The call sites listed in the inventory.

**Verify.** Add a per-screen query counter and log it. Render the affected screen
and confirm the count is now a small constant rather than proportional to row
count. Paste both numbers.

**Commit.** `perf: fetch related rows in one query instead of per row`

---

## Task 2.6 — Drop redundant indexes

**Why.** Every index is maintained on every insert, update, and delete. An index
whose columns are a leading prefix of another index adds nothing a reader can use
and slows every write.

**Do.** Take the `REDUNDANT_INDEX` findings. Drop each in a migration — unless it
enforces a `UNIQUE` constraint, in which case keep it and note why.

**Files.** The migrations file only.

**Verify.** Re-run the diagnostic with `--sql-file`. No query's plan may change,
and no query may get slower. If any does, the index was not redundant: restore it
and record what the tool missed.

**Commit.** `perf: drop indexes made redundant by composite indexes`

---

## Task 2.7 — Keep planner statistics current

**Why.** Without `sqlite_stat1`, the query planner guesses how selective each
index is, and sometimes guesses wrong — which shows up as two similar screens
having very different speeds for no visible reason. The statistics are what make
query cost predictable.

**Do.** Run `ANALYZE` at the end of the migration that adds the Phase 2 indexes,
and again after any bulk import. Add a maintenance path that runs it periodically
— on startup if it has not run in a week is sufficient, and it is cheap.

**Files.** The migrations file and the database module.

**Verify.** `sqlite_doctor` reports `ANALYZE statistics present: yes` and no
longer reports `NO_ANALYZE_STATS`. Confirm no query regressed, since fresh
statistics can change plans.

**Commit.** `perf: maintain ANALYZE statistics`

---

## Task 2.8 — Re-measure and close the phase

**Do.** Re-run the Task 0.5 commands into
`docs/polish-plan/baseline/after-phase-2.{txt,json}`. Re-walk the lag inventory.
Fill in the results table.

Any remaining high-severity finding must be explained in writing. Some are
legitimate: a report that aggregates every row genuinely has to read every row,
and the fix is a design change — maintaining a running total in a column updated
by trigger, or filtering before aggregating — not an index. Record which category
each one falls into rather than leaving it unexplained.

**Verify.** Zero high-severity findings, or a written justification for each.

**Commit.** `docs: record measurements after phase 2`

---

## Exit criteria

- [ ] Zero `UNINDEXED_FOREIGN_KEY` findings.
- [ ] No query with a `LIMIT` sorts in a temporary B-tree.
- [ ] No `AUTOMATIC` index appears in any plan.
- [ ] Text search uses FTS5, or is prefix-only and indexed, or does not exist.
- [ ] Pagination costs the same at page 200 as at page 1.
- [ ] Per-screen query count is constant, not proportional to rows.
- [ ] `ANALYZE` statistics are present and maintained.
- [ ] Every index added appears in a plan; every index dropped changed no plan.
- [ ] All high-severity findings are resolved or justified in writing.
- [ ] Every query is inside the budget from `budget.md`.

## Results

| Query | Baseline median | After phase 2 | Plan before | Plan after |
| --- | --- | --- | --- | --- |
| | | | | |

| Measurement | Phase 1 | After phase 2 |
| --- | --- | --- |
| High findings | | |
| Medium findings | | |
| Slowest query median | | |
| Queries per screen render | | |
| Worst stall from the lag inventory | | |
