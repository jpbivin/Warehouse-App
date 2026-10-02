# Warehouse-App

> **The application source is not yet in this repository.** At the time of
> writing, this repo contains only this README and the planning material below.
> The app itself needs to be committed before any of the plan can be executed —
> see Phase 0.

## Polish and performance plan

[`docs/polish-plan/`](docs/polish-plan/README.md) holds a phased plan to make the
app feel fluid, remove its intermittent lag, and raise the finish of the
interface, while keeping direct SQLite file access rather than a server.

Start with [the plan's README](docs/polish-plan/README.md), which explains how the
phases are meant to be executed, then work
[Phase 0](docs/polish-plan/phase-00-discovery-and-baseline.md) first — the later
phases read the notes it produces.

## Tools

[`tools/`](tools/README.md) contains supporting tools used by the plan. Both are
stdlib-only Python with nothing to install.

| Tool | Purpose |
| --- | --- |
| `tools/sqlite_doctor.py` | Read-only health and performance diagnostics for a local SQLite database: pragmas, index problems, query plans, timings. |
| `tools/demo_warehouse_db.py` | Builds a demo database at realistic volume, untuned and tuned, for exercising the diagnostic. |

```bash
python3 tools/sqlite_doctor.py path/to/warehouse.db --sql-file tools/app_queries.sql
```
