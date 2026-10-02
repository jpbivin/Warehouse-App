# Tools

Supporting tools for the polish plan in `docs/polish-plan/`. Python 3.10 or later,
standard library only, no dependencies to install.

## `sqlite_doctor.py`

Read-only health and performance diagnostics for a local SQLite database. Written
for apps that open a SQLite file directly rather than talking to an API server,
where query cost lands on or beside the UI thread and surfaces as interface lag.

The database is opened with `mode=ro`, so running this against a live application
database cannot modify it.

### What it reports

- **Settings stored in the file** — `journal_mode`, `auto_vacuum`, `user_version`,
  `application_id`. These describe the database itself.
- **Settings the app must apply per connection** — `synchronous`, `foreign_keys`,
  `cache_size`, `temp_store`, `mmap_size`, `busy_timeout`, with the recommended
  value for a local desktop app beside each. The observed column shows what *this
  tool's* connection received, which is SQLite's default, because these cannot be
  read out of the file.
- **Schema** — tables with row counts, column counts and indexes, plus views,
  triggers, virtual tables and whether `ANALYZE` statistics exist.
- **Integrity** — `quick_check` by default, `integrity_check` with `--deep`, plus
  `foreign_key_check`.
- **Queries** — `EXPLAIN QUERY PLAN` and timing for each query supplied.
- **Findings in this database** — problems that genuinely reflect the file:
  unindexed foreign keys, redundant indexes, large tables with no secondary index,
  missing statistics, absent schema versioning, full scans, automatic indexes,
  temporary B-tree sorts, correlated subqueries.
- **Checklist for the code that opens the database** — the per-connection pragmas,
  listed as things to verify by reading the connection setup. Deliberately kept
  out of the findings and out of `--fail-on`, since the tool cannot observe them.

### Usage

```bash
# Everything the tool can determine from the file alone
python3 tools/sqlite_doctor.py warehouse.db

# Add plans and timings for the app's real queries
python3 tools/sqlite_doctor.py warehouse.db --sql-file tools/app_queries.sql --runs 25

# One ad-hoc query
python3 tools/sqlite_doctor.py warehouse.db \
  --sql "SELECT * FROM stock WHERE location_id = ?" --param 12

# Machine-readable, for a committed baseline
python3 tools/sqlite_doctor.py warehouse.db --json > baseline.json

# CI gate: non-zero exit if any high-severity finding is present
python3 tools/sqlite_doctor.py warehouse.db --fail-on high

# Thorough integrity check, for validating a backup
python3 tools/sqlite_doctor.py backup.db --deep
```

Useful flags: `--no-bench` to explain without timing, `--skip-counts` to avoid
`count(*)` per table on a very large database, `--skip-integrity` to skip the
checks, `--runs N` to set the timed repetitions.

### Query file format

```sql
-- name: inventory_list_by_location
-- params: [12, 50]
SELECT i.sku, i.name, s.quantity
FROM stock AS s
JOIN items AS i ON i.id = s.item_id
WHERE s.location_id = ?
ORDER BY i.name
LIMIT ?;
```

Statements are separated by `;`. `-- name:` labels the query in the report and
`-- params:` supplies a JSON array of bind values. Both are optional; unnamed
queries are numbered.

`tools/warehouse_queries.sql` holds examples written against the demo schema.
Phase 0 replaces them with the app's real queries in `tools/app_queries.sql`.

## `demo_warehouse_db.py`

Builds a demo warehouse database at realistic volume. **This is a fixture for
exercising `sqlite_doctor.py`, not the application's schema.** It exists so the
diagnostic can be trusted before it is pointed at real data, and so the value of
the Phase 1 and Phase 2 work can be seen concretely.

```bash
python3 tools/demo_warehouse_db.py /tmp/untuned.db --mode untuned
python3 tools/demo_warehouse_db.py /tmp/tuned.db   --mode tuned
```

`--mode untuned` is a plausible single-pass starting point: primary keys only,
rollback journal, no statistics, no schema version. `--mode tuned` holds the same
rows after the Phase 1 pragma work and the Phase 2 index and FTS5 work. The random
seed is fixed so the two are comparable.

Row counts are adjustable with `--items`, `--locations`, and `--movements`.

### What the comparison shows

With 20,000 items, 200 locations, 35,023 stock rows and 150,000 movements. Medians
of three passes of 25 timed runs; absolute values are machine-specific, so compare
the ratios rather than the milliseconds.

| Query | Untuned median | Tuned median | Change |
| --- | --- | --- | --- |
| `inventory_list_by_location` | 0.96 ms | 0.11 ms | 9x |
| `item_search_substring` | 1.56 ms | 0.32 ms | 5x |
| `movement_history_for_item` | 4.40 ms | 0.01 ms | 434x |
| `low_stock_report` | 11.44 ms | 9.02 ms | 1x |
| `inventory_page_keyset` | 2.86 ms | 0.04 ms | 75x |

High-severity findings drop from 14 to 1. Reproduce with:

```bash
python3 tools/demo_warehouse_db.py /tmp/untuned.db --mode untuned
python3 tools/demo_warehouse_db.py /tmp/tuned.db   --mode tuned
python3 tools/sqlite_doctor.py /tmp/untuned.db --sql-file tools/warehouse_queries.sql --runs 25
python3 tools/sqlite_doctor.py /tmp/tuned.db   --sql-file tools/warehouse_queries.sql --runs 25
```

Two of those rows are worth reading carefully, because they are the lessons the
tool is there to teach:

- `movement_history_for_item` improves by a factor of several hundred purely from
  indexing a foreign key. The query was already simple and correct; it was reading
  150,000 rows to return 10.
- `low_stock_report` barely improves, and is correctly still flagged. It aggregates
  every item's stock, so it genuinely has to read every row, and no index fixes
  that. The remedy is a design change — maintaining a running total in a column, or
  filtering before aggregating — which is why Phase 2 asks for an explanation of
  each remaining finding rather than assuming an index is always the answer.
