#!/usr/bin/env python3
"""Read-only health and performance diagnostics for a local SQLite database.

Built for apps that open a SQLite file directly instead of talking to an API
server. In that arrangement query cost is paid on, or next to, the UI thread,
so slow queries surface as interface lag rather than as slow network calls.

Stdlib only. The database is opened read-only, so running this against a live
application database cannot modify it.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

SEVERITY_ORDER = ("high", "medium", "low", "info")

LARGE_TABLE_ROWS = 5_000
FREELIST_WASTE_RATIO = 0.25
MIN_RECOMMENDED_CACHE_KIB = 8_000

FILE_FACT_PRAGMAS = ("page_size", "page_count", "freelist_count", "encoding")
PERSISTENT_PRAGMAS = ("journal_mode", "auto_vacuum", "user_version", "application_id")
CONNECTION_PRAGMAS = (
    "synchronous",
    "foreign_keys",
    "cache_size",
    "temp_store",
    "mmap_size",
    "busy_timeout",
    "wal_autocheckpoint",
)

# Values a local desktop/offline app generally wants on every connection it opens.
RECOMMENDED_CONNECTION_PRAGMAS = {
    "synchronous": "1 (NORMAL)",
    "foreign_keys": "1 (ON)",
    "cache_size": "-16000 (16 MiB)",
    "temp_store": "2 (MEMORY)",
    "mmap_size": "268435456 (256 MiB)",
    "busy_timeout": ">= 5000",
}


@dataclass
class Finding:
    severity: str
    code: str
    title: str
    detail: str
    fix: str


@dataclass
class QueryReport:
    name: str
    sql: str
    params: list[Any]
    plan: list[str] = field(default_factory=list)
    plan_findings: list[Finding] = field(default_factory=list)
    rows_returned: int | None = None
    timings_ms: list[float] = field(default_factory=list)
    error: str | None = None

    @property
    def p50_ms(self) -> float | None:
        return statistics.median(self.timings_ms) if self.timings_ms else None

    @property
    def worst_ms(self) -> float | None:
        return max(self.timings_ms) if self.timings_ms else None


def connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise SystemExit(f"sqlite_doctor: no such file: {path}")
    uri = f"file:{quote(str(path.resolve()))}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    except sqlite3.Error as exc:
        raise SystemExit(f"sqlite_doctor: cannot open {path} read-only: {exc}") from exc
    conn.row_factory = sqlite3.Row
    return conn


def pragma(conn: sqlite3.Connection, name: str) -> Any:
    try:
        row = conn.execute(f"PRAGMA {name}").fetchone()
    except sqlite3.Error:
        return None
    return None if row is None else row[0]


def collect_settings(conn: sqlite3.Connection, path: Path) -> dict[str, Any]:
    file_facts = {name: pragma(conn, name) for name in FILE_FACT_PRAGMAS}
    page_size = file_facts.get("page_size") or 0
    page_count = file_facts.get("page_count") or 0
    freelist = file_facts.get("freelist_count") or 0
    return {
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "sidecar_files": [
            p.name for p in (path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")) if p.exists()
        ],
        "sqlite_library_version": sqlite3.sqlite_version,
        "file_facts": file_facts,
        "logical_size_bytes": page_size * page_count,
        "freelist_bytes": page_size * freelist,
        "persistent_settings": {name: pragma(conn, name) for name in PERSISTENT_PRAGMAS},
        "connection_settings": {name: pragma(conn, name) for name in CONNECTION_PRAGMAS},
    }


def index_key_columns(conn: sqlite3.Connection, index_name: str) -> list[str]:
    columns: list[str] = []
    for row in conn.execute(f"PRAGMA index_info({quote_ident(index_name)})"):
        # A NULL name marks an expression or the rowid, which cannot satisfy a
        # column-list prefix match, so stop collecting at that point.
        if row["name"] is None:
            break
        columns.append(row["name"])
    return columns


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def collect_schema(conn: sqlite3.Connection, count_rows: bool) -> dict[str, Any]:
    objects = conn.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()

    tables: list[dict[str, Any]] = []
    virtual_tables: list[str] = []
    fts_tables: list[str] = []

    for obj in objects:
        if obj["type"] != "table":
            continue
        sql = obj["sql"] or ""
        upper = sql.upper()
        if "CREATE VIRTUAL TABLE" in upper:
            virtual_tables.append(obj["name"])
            if "USING FTS" in upper:
                fts_tables.append(obj["name"])
            continue
        if is_fts_shadow_table(obj["name"], fts_tables, objects):
            continue

        name = obj["name"]
        columns = [dict(row) for row in conn.execute(f"PRAGMA table_info({quote_ident(name)})")]
        indexes = []
        for row in conn.execute(f"PRAGMA index_list({quote_ident(name)})"):
            indexes.append(
                {
                    "name": row["name"],
                    "unique": bool(row["unique"]),
                    "origin": row["origin"],
                    "partial": bool(row["partial"]),
                    "columns": index_key_columns(conn, row["name"]),
                }
            )
        foreign_keys = group_foreign_keys(conn, name)

        row_count = None
        if count_rows:
            try:
                row_count = conn.execute(f"SELECT count(*) FROM {quote_ident(name)}").fetchone()[0]
            except sqlite3.Error:
                row_count = None

        tables.append(
            {
                "name": name,
                "row_count": row_count,
                "without_rowid": "WITHOUT ROWID" in (sql or "").upper(),
                "columns": columns,
                "indexes": indexes,
                "foreign_keys": foreign_keys,
            }
        )

    return {
        "tables": tables,
        "virtual_tables": virtual_tables,
        "fts_tables": fts_tables,
        "views": [o["name"] for o in objects if o["type"] == "view"],
        "triggers": [o["name"] for o in objects if o["type"] == "trigger"],
        "has_analyze_stats": table_exists(conn, "sqlite_stat1"),
    }


def is_fts_shadow_table(name: str, fts_tables: Sequence[str], objects: Sequence[sqlite3.Row]) -> bool:
    known_virtual = [o["name"] for o in objects if o["sql"] and "CREATE VIRTUAL TABLE" in o["sql"].upper()]
    suffixes = ("_data", "_idx", "_content", "_docsize", "_config", "_segments", "_segdir", "_stat")
    for base in list(fts_tables) + known_virtual:
        if any(name == base + suffix for suffix in suffixes):
            return True
    return False


def group_foreign_keys(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    grouped: dict[int, dict[str, Any]] = {}
    for row in conn.execute(f"PRAGMA foreign_key_list({quote_ident(table)})"):
        entry = grouped.setdefault(
            row["id"],
            {"references": row["table"], "from": [], "to": [], "on_delete": row["on_delete"]},
        )
        entry["from"].append(row["from"])
        entry["to"].append(row["to"])
    return [grouped[key] for key in sorted(grouped)]


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (name,)
    ).fetchone()
    return row is not None


def primary_key_columns(table: dict[str, Any]) -> list[str]:
    pk = [col for col in table["columns"] if col["pk"]]
    pk.sort(key=lambda col: col["pk"])
    return [col["name"] for col in pk]


def covers_prefix(index_columns: Sequence[str], wanted: Sequence[str]) -> bool:
    return len(index_columns) >= len(wanted) and list(index_columns[: len(wanted)]) == list(wanted)


TIMESTAMP_COLUMN_HINTS = ("_at", "_on", "_date", "_time", "timestamp", "created", "updated", "modified")


def searchable_text_columns(table: dict[str, Any]) -> list[str]:
    """Text columns a user might plausibly type into a search box.

    Timestamps stored as text are excluded; they are text by storage choice
    rather than because anyone searches them.
    """
    columns = []
    for col in table["columns"]:
        if not str(col["type"]).upper().startswith(("TEXT", "VARCHAR", "CHAR", "CLOB")):
            continue
        lowered = col["name"].lower()
        if any(hint in lowered for hint in TIMESTAMP_COLUMN_HINTS):
            continue
        columns.append(col["name"])
    return columns


def audit_settings(settings: dict[str, Any]) -> list[Finding]:
    """Findings about settings the database file itself carries.

    Only pragmas stored in the file are judged here. Per-connection pragmas
    cannot be observed from outside the application, so they are handled by
    connection_checklist instead.
    """
    findings: list[Finding] = []
    persistent = settings["persistent_settings"]

    journal_mode = str(persistent.get("journal_mode") or "").lower()
    if journal_mode not in ("wal", "memory", "off"):
        findings.append(
            Finding(
                "high",
                "WAL_OFF",
                f"journal_mode is {journal_mode or 'unknown'}, not wal",
                "In rollback-journal mode a writer blocks every reader. A single slow write "
                "stalls the queries feeding the interface, which is a common source of "
                "intermittent, hard-to-reproduce lag.",
                "Run `PRAGMA journal_mode = WAL` once; the setting is stored in the file. "
                "WAL adds -wal and -shm sidecar files that must ship with the database.",
            )
        )

    if persistent.get("user_version") == 0:
        findings.append(
            Finding(
                "medium",
                "NO_SCHEMA_VERSION",
                "user_version is 0, so the file carries no schema version",
                "Without a version stamp there is no safe way to tell an old database from a "
                "new one, so the next schema change risks breaking existing installations.",
                "Adopt `PRAGMA user_version` as a migration counter before making further "
                "schema changes. See the Phase 1 plan.",
            )
        )

    freelist_bytes = settings["freelist_bytes"]
    logical = settings["logical_size_bytes"] or 1
    if freelist_bytes and freelist_bytes / logical > FREELIST_WASTE_RATIO:
        findings.append(
            Finding(
                "low",
                "HIGH_FREELIST",
                f"{freelist_bytes / 1024:.0f} KiB of the file is on the free list",
                "Reclaimed-but-unused pages fragment the file and inflate scans.",
                "Run `VACUUM` during maintenance, or `VACUUM INTO 'copy.db'` to compact "
                "without holding a long write lock on the live file.",
            )
        )

    return findings


def connection_checklist(settings: dict[str, Any]) -> list[Finding]:
    """Per-connection pragmas the application is responsible for setting.

    These cannot be read out of the database file. The values printed in the
    report are the ones this tool's own connection received, so they describe
    SQLite's defaults rather than the application's behaviour. Each entry is a
    thing to verify in the code that opens the database, which is why they are
    kept out of `findings` and out of the `--fail-on` gate.
    """
    items: list[Finding] = []
    journal_mode = str(settings["persistent_settings"].get("journal_mode") or "").lower()

    items.append(
        Finding(
            "high",
            "VERIFY_FOREIGN_KEYS",
            "every connection runs `PRAGMA foreign_keys = ON`",
            "SQLite leaves foreign key enforcement off by default, per connection. If the "
            "application never enables it, declared references are not checked and orphaned "
            "rows accumulate silently, surfacing later as blank or duplicated records.",
            "Enable it immediately after opening, before any statement runs.",
        )
    )
    items.append(
        Finding(
            "medium",
            "VERIFY_BUSY_TIMEOUT",
            "every connection sets `PRAGMA busy_timeout` to at least 5000",
            "With no busy timeout, a connection that finds the database locked fails at once "
            "with SQLITE_BUSY rather than waiting. These appear to users as random, "
            "unreproducible save failures.",
            "Set the timeout and still handle SQLITE_BUSY, since the timeout only bounds the wait.",
        )
    )
    if journal_mode == "wal":
        items.append(
            Finding(
                "medium",
                "VERIFY_SYNCHRONOUS_NORMAL",
                "every connection sets `PRAGMA synchronous = NORMAL`",
                "This file uses WAL, where FULL costs a device flush on every commit. NORMAL "
                "still protects against application and OS crashes and only risks the most "
                "recent transactions on sudden power loss.",
                "Prefer NORMAL under WAL; keep FULL only if losing the last commits is unacceptable.",
            )
        )
    items.append(
        Finding(
            "low",
            "VERIFY_PAGE_CACHE",
            f"every connection raises `PRAGMA cache_size` above the ~2 MiB default "
            f"(suggest {MIN_RECOMMENDED_CACHE_KIB // 1000 * 2} MiB)",
            f"This database is {human_bytes(settings['size_bytes'])}. When the working set "
            "exceeds the page cache, list renders re-read pages from disk.",
            "Use a negative value to mean KiB, for example `PRAGMA cache_size = -16000`.",
        )
    )
    items.append(
        Finding(
            "low",
            "VERIFY_TEMP_STORE",
            "every connection sets `PRAGMA temp_store = MEMORY`",
            "Sorting and grouping that spills to disk costs far more than the same work in "
            "memory, and shows up as an occasional stall rather than a steady slowdown.",
            "Set it per connection; it cannot be persisted in the file.",
        )
    )
    return items


def audit_schema(schema: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []

    if not schema["has_analyze_stats"] and schema["tables"]:
        findings.append(
            Finding(
                "medium",
                "NO_ANALYZE_STATS",
                "no sqlite_stat1 table, so ANALYZE has never run",
                "Without statistics the query planner guesses selectivity and can pick the "
                "wrong index, which makes query cost unpredictable between similar screens.",
                "Run `ANALYZE` after seeding and after any bulk import, then periodically.",
            )
        )

    for table in schema["tables"]:
        name = table["name"]
        indexes = table["indexes"]
        row_count = table["row_count"]

        if not primary_key_columns(table):
            findings.append(
                Finding(
                    "medium",
                    "NO_PRIMARY_KEY",
                    f"table {name} has no primary key",
                    "Rows can only be addressed by their implicit rowid, which is not stable "
                    "across a VACUUM or an export/import cycle. Updates and deletes driven "
                    "from the interface can then hit the wrong row.",
                    f"Add an explicit primary key to {name}, or declare the existing "
                    "identifier column as INTEGER PRIMARY KEY.",
                )
            )

        for fk in table["foreign_keys"]:
            child_columns = fk["from"]
            if any(covers_prefix(idx["columns"], child_columns) for idx in indexes):
                continue
            if covers_prefix(primary_key_columns(table), child_columns):
                continue
            findings.append(
                Finding(
                    "high",
                    "UNINDEXED_FOREIGN_KEY",
                    f"{name}({', '.join(child_columns)}) references {fk['references']} with no index",
                    "Every join or lookup across this reference must scan the whole child "
                    "table, and a delete on the parent scans it again to enforce the "
                    "constraint. This is the single most common cause of a list view that is "
                    "fast with test data and slow with real data.",
                    f"CREATE INDEX idx_{name}_{'_'.join(child_columns)} "
                    f"ON {name}({', '.join(child_columns)});",
                )
            )

        secondary = [idx for idx in indexes if idx["origin"] == "c"]
        if row_count is not None and row_count >= LARGE_TABLE_ROWS and not secondary:
            findings.append(
                Finding(
                    "high",
                    "LARGE_TABLE_NO_SECONDARY_INDEX",
                    f"table {name} holds {row_count:,} rows with no non-constraint index",
                    "Any filter or sort other than by primary key has to read every row. "
                    "The cost grows with the data, so the interface degrades as the warehouse "
                    "fills up rather than being slow from the start.",
                    f"Capture the queries the interface actually runs against {name}, then "
                    "index their filter and sort columns. Confirm with EXPLAIN QUERY PLAN.",
                )
            )

        for outer in secondary:
            for inner in indexes:
                if inner["name"] == outer["name"] or not outer["columns"]:
                    continue
                if covers_prefix(inner["columns"], outer["columns"]) and len(inner["columns"]) > len(outer["columns"]):
                    findings.append(
                        Finding(
                            "low",
                            "REDUNDANT_INDEX",
                            f"index {outer['name']} is a prefix of {inner['name']}",
                            f"({', '.join(outer['columns'])}) is already served by the leading "
                            f"columns of {inner['name']}. The extra index costs write time and "
                            "file size without adding read paths.",
                            f"Consider dropping {outer['name']} unless it enforces uniqueness.",
                        )
                    )
                    break

    large_text_tables = [
        t["name"]
        for t in schema["tables"]
        if (t["row_count"] or 0) >= LARGE_TABLE_ROWS and len(searchable_text_columns(t)) >= 2
    ]
    if large_text_tables and not schema["fts_tables"]:
        findings.append(
            Finding(
                "info",
                "NO_FULL_TEXT_INDEX",
                f"no FTS table alongside large text tables: {', '.join(large_text_tables)}",
                "A substring search written as LIKE '%term%' cannot use a normal index and "
                "always scans. If the interface has a search box over these tables, every "
                "keystroke pays for a full scan.",
                "Add an FTS5 table kept in sync by triggers and query it for search, keeping "
                "the base table as the source of truth. See the Phase 2 plan.",
            )
        )

    return findings


def audit_plan(name: str, plan_lines: Sequence[str]) -> list[Finding]:
    findings: list[Finding] = []
    for line in plan_lines:
        upper = line.upper()
        # A virtual table reports SCAN even when its own index satisfies the
        # constraint, which is the intended fast path for FTS and R-tree.
        if "VIRTUAL TABLE INDEX" in upper:
            continue
        if "AUTOMATIC" in upper and "INDEX" in upper:
            findings.append(
                Finding(
                    "high",
                    "AUTOMATIC_INDEX",
                    f"{name}: SQLite builds a throwaway index at runtime",
                    f"Plan step: {line.strip()}. SQLite decided an index was worth building "
                    "for this one query and discards it afterwards, repeating the work on "
                    "every call.",
                    "Create the equivalent permanent index.",
                )
            )
        elif upper.lstrip().startswith("SCAN") and "USING" not in upper:
            findings.append(
                Finding(
                    "high",
                    "FULL_TABLE_SCAN",
                    f"{name}: full table scan",
                    f"Plan step: {line.strip()}. Every row is read regardless of how few match.",
                    "Add an index covering the filter columns, or narrow the query.",
                )
            )
        elif upper.lstrip().startswith("SCAN") and "INDEX" in upper:
            findings.append(
                Finding(
                    "medium",
                    "FULL_INDEX_SCAN",
                    f"{name}: full index scan",
                    f"Plan step: {line.strip()}. Cheaper than a table scan but still "
                    "proportional to table size.",
                    "Check whether the filter can seek instead of scan; a leading-column "
                    "mismatch or a function applied to the indexed column prevents seeking.",
                )
            )
        if "USE TEMP B-TREE" in upper:
            findings.append(
                Finding(
                    "medium",
                    "TEMP_BTREE_SORT",
                    f"{name}: result is sorted or grouped in a temporary B-tree",
                    f"Plan step: {line.strip()}. The whole result set is materialised and "
                    "sorted before the first row can be displayed, so the interface waits "
                    "even when it only shows the first screenful.",
                    "Add an index whose column order matches the ORDER BY or GROUP BY so the "
                    "rows arrive already ordered.",
                )
            )
        if "CORRELATED" in upper:
            findings.append(
                Finding(
                    "medium",
                    "CORRELATED_SUBQUERY",
                    f"{name}: correlated subquery runs once per row",
                    f"Plan step: {line.strip()}.",
                    "Rewrite as a join or a window function so the work happens once.",
                )
            )
    return findings


def parse_sql_file(text: str) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    buffer: list[str] = []
    meta: dict[str, Any] = {}
    auto_index = 1

    def flush() -> None:
        nonlocal buffer, meta, auto_index
        sql = "\n".join(buffer).strip().rstrip(";").strip()
        buffer = []
        pending_meta, meta = meta, {}
        if not sql:
            return
        queries.append(
            {
                "name": pending_meta.get("name") or f"query_{auto_index}",
                "sql": sql,
                "params": pending_meta.get("params", []),
            }
        )
        auto_index += 1

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("--"):
            directive = stripped.lstrip("-").strip()
            key, _, value = directive.partition(":")
            key = key.strip().lower()
            if key == "name" and value.strip():
                meta["name"] = value.strip()
                continue
            if key == "params" and value.strip():
                try:
                    parsed = json.loads(value.strip())
                except json.JSONDecodeError as exc:
                    raise SystemExit(f"sqlite_doctor: bad `-- params:` JSON: {exc}") from exc
                meta["params"] = parsed if isinstance(parsed, list) else [parsed]
                continue
            continue
        buffer.append(raw_line)
        if sqlite3.complete_statement("\n".join(buffer)):
            flush()
    flush()
    return queries


def analyse_queries(
    conn: sqlite3.Connection, queries: Sequence[dict[str, Any]], runs: int, bench: bool
) -> list[QueryReport]:
    reports: list[QueryReport] = []
    for query in queries:
        report = QueryReport(name=query["name"], sql=query["sql"], params=list(query["params"]))
        try:
            plan_rows = conn.execute(f"EXPLAIN QUERY PLAN {query['sql']}", report.params).fetchall()
            report.plan = [row["detail"] for row in plan_rows]
            report.plan_findings = audit_plan(report.name, report.plan)
        except sqlite3.Error as exc:
            report.error = f"EXPLAIN QUERY PLAN failed: {exc}"
            reports.append(report)
            continue

        if bench:
            try:
                for _ in range(max(1, runs)):
                    start = time.perf_counter()
                    rows = conn.execute(query["sql"], report.params).fetchall()
                    report.timings_ms.append((time.perf_counter() - start) * 1000)
                    report.rows_returned = len(rows)
            except sqlite3.Error as exc:
                report.error = f"execution failed: {exc}"
        reports.append(report)
    return reports


def check_integrity(conn: sqlite3.Connection, deep: bool) -> dict[str, Any]:
    check = "integrity_check" if deep else "quick_check"
    try:
        result = [row[0] for row in conn.execute(f"PRAGMA {check}")]
    except sqlite3.Error as exc:
        result = [f"failed: {exc}"]
    try:
        violations = [dict(row) for row in conn.execute("PRAGMA foreign_key_check")]
    except sqlite3.Error as exc:
        violations = [{"error": str(exc)}]
    return {"check": check, "result": result, "foreign_key_violations": violations}


def audit_integrity(integrity: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    if integrity["result"] != ["ok"]:
        findings.append(
            Finding(
                "high",
                "INTEGRITY_FAILED",
                f"PRAGMA {integrity['check']} did not return ok",
                "; ".join(str(line) for line in integrity["result"][:10]),
                "Restore from a backup. Do not keep writing to a database that fails an "
                "integrity check.",
            )
        )
    violations = integrity["foreign_key_violations"]
    if violations:
        findings.append(
            Finding(
                "high",
                "FOREIGN_KEY_VIOLATIONS",
                f"{len(violations)} row(s) violate a declared foreign key",
                "These rows reference parents that no longer exist, which usually means "
                "foreign key enforcement was off while the application was writing.",
                "Repair or delete the orphaned rows, then enable `PRAGMA foreign_keys = ON` "
                "on every connection so they cannot reappear.",
            )
        )
    return findings


def sort_findings(findings: Sequence[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (SEVERITY_ORDER.index(f.severity), f.code, f.title))


def human_bytes(value: int | None) -> str:
    if not value:
        return "0 B"
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:,.1f} {unit}" if unit != "B" else f"{size:,.0f} B"
        size /= 1024
    return f"{size:,.1f} GiB"


def render_text(report: dict[str, Any], out) -> None:
    settings = report["settings"]
    schema = report["schema"]

    def header(title: str) -> None:
        out.write(f"\n{title}\n{'-' * len(title)}\n")

    out.write("sqlite_doctor report\n")
    out.write("=" * 20 + "\n")
    out.write(f"database : {settings['path']}\n")
    out.write(f"file size: {human_bytes(settings['size_bytes'])}")
    if settings["freelist_bytes"]:
        out.write(f" ({human_bytes(settings['freelist_bytes'])} on the free list)")
    out.write("\n")
    out.write(f"sqlite   : library {settings['sqlite_library_version']}\n")
    if settings["sidecar_files"]:
        out.write(f"sidecars : {', '.join(settings['sidecar_files'])}\n")

    header("Settings stored in the file")
    for key, value in settings["persistent_settings"].items():
        out.write(f"  {key:<20} {value}\n")

    header("Settings the app must apply on every connection")
    out.write(
        "  These are per-connection and are NOT stored in the database file, so the\n"
        "  'this tool' column shows SQLite's defaults rather than what the app does.\n"
    )
    out.write(f"  {'pragma':<20} {'this tool':<22} recommended for the app\n")
    for key, value in settings["connection_settings"].items():
        recommended = RECOMMENDED_CONNECTION_PRAGMAS.get(key, "-")
        out.write(f"  {key:<20} {value!s:<22} {recommended}\n")

    header("Schema")
    out.write(
        f"  {len(schema['tables'])} table(s), {len(schema['views'])} view(s), "
        f"{len(schema['triggers'])} trigger(s), {len(schema['virtual_tables'])} virtual table(s)\n"
    )
    out.write(f"  ANALYZE statistics present: {'yes' if schema['has_analyze_stats'] else 'no'}\n")
    if schema["tables"]:
        out.write(f"\n  {'table':<28}{'rows':>12}  {'cols':>4}  indexes\n")
        for table in sorted(schema["tables"], key=lambda t: -(t["row_count"] or 0)):
            rows = f"{table['row_count']:,}" if table["row_count"] is not None else "-"
            index_names = [idx["name"] for idx in table["indexes"]] or ["(none)"]
            out.write(
                f"  {table['name']:<28}{rows:>12}  {len(table['columns']):>4}  {', '.join(index_names)}\n"
            )

    if report.get("integrity"):
        header("Integrity")
        out.write(f"  PRAGMA {report['integrity']['check']}: {', '.join(map(str, report['integrity']['result']))}\n")
        out.write(f"  foreign key violations: {len(report['integrity']['foreign_key_violations'])}\n")

    if report["queries"]:
        header("Queries")
        for query in report["queries"]:
            out.write(f"\n  [{query['name']}]\n")
            for line in query["sql"].splitlines():
                out.write(f"    | {line}\n")
            if query["params"]:
                out.write(f"    params: {json.dumps(query['params'])}\n")
            if query["error"]:
                out.write(f"    ERROR: {query['error']}\n")
                continue
            out.write("    plan:\n")
            for line in query["plan"]:
                out.write(f"      {line}\n")
            if query["timings_ms"]:
                out.write(
                    f"    timing: median {query['p50_ms']:.2f} ms, worst "
                    f"{query['worst_ms']:.2f} ms over {len(query['timings_ms'])} run(s), "
                    f"{query['rows_returned']:,} row(s)\n"
                )

    header("Findings in this database")
    findings = report["findings"]
    if not findings:
        out.write("  No findings. Nothing in this database file tripped a check.\n")
    for finding in findings:
        out.write(f"\n  [{finding['severity'].upper()}] {finding['code']}: {finding['title']}\n")
        out.write(f"    why: {finding['detail']}\n")
        out.write(f"    fix: {finding['fix']}\n")

    header("Checklist for the code that opens the database")
    out.write(
        "  Not findings: these cannot be checked from outside the application. Read the\n"
        "  connection setup code and confirm each one.\n"
    )
    for item in report["connection_checklist"]:
        out.write(f"\n  [ ] ({item['severity']}) {item['code']}: {item['title']}\n")
        out.write(f"      why: {item['detail']}\n")
        out.write(f"      note: {item['fix']}\n")

    counts = report["summary"]["counts_by_severity"]
    header("Summary")
    out.write("  " + ", ".join(f"{severity}: {counts.get(severity, 0)}" for severity in SEVERITY_ORDER) + "\n")
    out.write(f"  plus {len(report['connection_checklist'])} connection checklist item(s) to verify by hand\n")


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    path = Path(args.database)
    conn = connect_readonly(path)
    try:
        settings = collect_settings(conn, path)
        schema = collect_schema(conn, count_rows=not args.skip_counts)

        findings = audit_settings(settings) + audit_schema(schema)
        checklist = connection_checklist(settings)

        integrity = None
        if not args.skip_integrity:
            integrity = check_integrity(conn, deep=args.deep)
            findings += audit_integrity(integrity)

        queries: list[dict[str, Any]] = []
        if args.sql:
            queries.append({"name": "inline", "sql": args.sql.strip().rstrip(";"), "params": args.param})
        if args.sql_file:
            queries += parse_sql_file(Path(args.sql_file).read_text(encoding="utf-8"))

        query_reports = analyse_queries(conn, queries, runs=args.runs, bench=not args.no_bench)
        for query_report in query_reports:
            findings += query_report.plan_findings
    finally:
        conn.close()

    findings = sort_findings(findings)
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1

    serialised_queries = []
    for query_report in query_reports:
        payload = asdict(query_report)
        payload["plan_findings"] = [asdict(f) for f in query_report.plan_findings]
        payload["p50_ms"] = query_report.p50_ms
        payload["worst_ms"] = query_report.worst_ms
        serialised_queries.append(payload)

    return {
        "settings": settings,
        "schema": schema,
        "integrity": integrity,
        "queries": serialised_queries,
        "findings": [asdict(f) for f in findings],
        "connection_checklist": [asdict(f) for f in checklist],
        "summary": {
            "counts_by_severity": counts,
            "total_findings": len(findings),
            "connection_checklist_items": len(checklist),
        },
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="sqlite_doctor",
        description="Read-only health and performance diagnostics for a local SQLite database.",
        epilog=(
            "Examples:\n"
            "  sqlite_doctor.py warehouse.db\n"
            "  sqlite_doctor.py warehouse.db --sql-file queries.sql --runs 20\n"
            "  sqlite_doctor.py warehouse.db --json > baseline.json\n"
            "  sqlite_doctor.py warehouse.db --fail-on high   # for CI\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("database", help="path to the SQLite file (opened read-only)")
    parser.add_argument("--sql", help="a single query to explain and time")
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        help="bind parameter for --sql, repeatable, applied in order",
    )
    parser.add_argument(
        "--sql-file",
        help="file of ;-separated queries, optionally labelled with `-- name:` and `-- params:` lines",
    )
    parser.add_argument("--runs", type=int, default=5, help="timed runs per query (default 5)")
    parser.add_argument("--no-bench", action="store_true", help="explain queries without timing them")
    parser.add_argument("--skip-counts", action="store_true", help="skip SELECT count(*) per table")
    parser.add_argument("--skip-integrity", action="store_true", help="skip the integrity checks")
    parser.add_argument("--deep", action="store_true", help="use integrity_check instead of quick_check")
    parser.add_argument("--json", action="store_true", help="emit the full report as JSON")
    parser.add_argument(
        "--fail-on",
        choices=SEVERITY_ORDER,
        help="exit non-zero when a finding at this severity or higher is present",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(args)

    if args.json:
        json.dump(report, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        render_text(report, sys.stdout)

    if args.fail_on:
        threshold = SEVERITY_ORDER.index(args.fail_on)
        if any(SEVERITY_ORDER.index(f["severity"]) <= threshold for f in report["findings"]):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
