#!/usr/bin/env python3
"""Generate a demo warehouse database for exercising sqlite_doctor.py.

This is a fixture, not the application's schema. Its purpose is to give the
diagnostic tool and the Phase 0 baseline procedure something realistic to run
against, and to show the difference the Phase 1 and Phase 2 work makes.

  --mode untuned   plausible AI-generated starting point: primary keys only,
                   rollback journal, no statistics, no schema version
  --mode tuned     the same data after the Phase 1 and Phase 2 changes
"""

from __future__ import annotations

import argparse
import random
import sqlite3
import sys
from pathlib import Path

CATEGORIES = ("fasteners", "abrasives", "adhesives", "packaging", "tooling", "safety", "electrical")
ADJECTIVES = ("stainless", "galvanised", "heavy duty", "low profile", "reinforced", "insulated", "anti-static")
NOUNS = ("bracket", "washer", "sleeve", "coupler", "gasket", "spool", "clamp", "bushing", "anchor", "shim")
OPERATORS = ("agarcia", "bchen", "dokafor", "ekowalski", "fmorrow", "receiving-kiosk")

SCHEMA = """
CREATE TABLE locations (
    id          INTEGER PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    zone        TEXT NOT NULL
);

CREATE TABLE items (
    id          INTEGER PRIMARY KEY,
    sku         TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    description TEXT NOT NULL,
    category    TEXT NOT NULL,
    reorder_at  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE stock (
    id          INTEGER PRIMARY KEY,
    item_id     INTEGER NOT NULL REFERENCES items(id),
    location_id INTEGER NOT NULL REFERENCES locations(id),
    quantity    INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL
);

CREATE TABLE movements (
    id               INTEGER PRIMARY KEY,
    item_id          INTEGER NOT NULL REFERENCES items(id),
    from_location_id INTEGER REFERENCES locations(id),
    to_location_id   INTEGER REFERENCES locations(id),
    quantity         INTEGER NOT NULL,
    moved_at         TEXT NOT NULL,
    operator         TEXT NOT NULL,
    note             TEXT
);
"""

TUNING_INDEXES = """
CREATE INDEX idx_stock_item_id              ON stock(item_id);
CREATE INDEX idx_stock_location_id          ON stock(location_id);
CREATE UNIQUE INDEX idx_stock_item_location ON stock(item_id, location_id);
CREATE INDEX idx_movements_item_moved_at    ON movements(item_id, moved_at DESC);
CREATE INDEX idx_movements_from_location    ON movements(from_location_id);
CREATE INDEX idx_movements_to_location      ON movements(to_location_id);
CREATE INDEX idx_movements_moved_at         ON movements(moved_at DESC);
CREATE INDEX idx_items_category_name        ON items(category, name);
CREATE INDEX idx_items_name                 ON items(name);
"""

FTS = """
CREATE VIRTUAL TABLE items_fts USING fts5(
    sku, name, description, content='items', content_rowid='id'
);
INSERT INTO items_fts(rowid, sku, name, description)
    SELECT id, sku, name, description FROM items;

CREATE TRIGGER items_fts_ai AFTER INSERT ON items BEGIN
    INSERT INTO items_fts(rowid, sku, name, description)
        VALUES (new.id, new.sku, new.name, new.description);
END;
CREATE TRIGGER items_fts_ad AFTER DELETE ON items BEGIN
    INSERT INTO items_fts(items_fts, rowid, sku, name, description)
        VALUES ('delete', old.id, old.sku, old.name, old.description);
END;
CREATE TRIGGER items_fts_au AFTER UPDATE ON items BEGIN
    INSERT INTO items_fts(items_fts, rowid, sku, name, description)
        VALUES ('delete', old.id, old.sku, old.name, old.description);
    INSERT INTO items_fts(rowid, sku, name, description)
        VALUES (new.id, new.sku, new.name, new.description);
END;
"""


def has_fts5(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE temp.__fts_probe USING fts5(x)")
        conn.execute("DROP TABLE temp.__fts_probe")
        return True
    except sqlite3.OperationalError:
        return False


def build_rows(rng: random.Random, item_count: int, location_count: int, movement_count: int):
    location_rows = [
        (
            index,
            f"{rng.choice('ABCDE')}{index // 20 + 1:02d}-{index % 20 + 1:02d}",
            f"Rack {index // 20 + 1} bay {index % 20 + 1}",
            rng.choice(("receiving", "bulk", "pick-face", "overflow", "shipping")),
        )
        for index in range(1, location_count + 1)
    ]

    item_rows = []
    for index in range(1, item_count + 1):
        adjective = rng.choice(ADJECTIVES)
        noun = rng.choice(NOUNS)
        item_rows.append(
            (
                index,
                f"SKU-{index:06d}",
                f"{adjective} {noun} {rng.randint(2, 96)}mm",
                (
                    f"{adjective.capitalize()} {noun}, "
                    f"{rng.choice(('box of 50', 'box of 100', 'each', 'pack of 10'))}, "
                    f"{rng.choice(('zinc', 'nylon', 'brass', 'steel', 'aluminium'))} finish"
                ),
                rng.choice(CATEGORIES),
                rng.choice((0, 10, 25, 50, 100)),
            )
        )

    stock_rows = []
    stock_id = 1
    for item_id in range(1, item_count + 1):
        for location_id in rng.sample(range(1, location_count + 1), rng.choice((1, 1, 2, 3))):
            stock_rows.append(
                (
                    stock_id,
                    item_id,
                    location_id,
                    rng.randint(0, 900),
                    f"2026-{rng.randint(1, 9):02d}-{rng.randint(1, 28):02d}T{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:00Z",
                )
            )
            stock_id += 1

    movement_rows = []
    for index in range(1, movement_count + 1):
        from_location = rng.choice((None, rng.randint(1, location_count)))
        movement_rows.append(
            (
                index,
                rng.randint(1, item_count),
                from_location,
                rng.randint(1, location_count),
                rng.randint(1, 120),
                f"2026-{rng.randint(1, 9):02d}-{rng.randint(1, 28):02d}T{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:00Z",
                rng.choice(OPERATORS),
                rng.choice((None, None, "cycle count", "damaged on arrival", "customer return", "replenishment")),
            )
        )

    return location_rows, item_rows, stock_rows, movement_rows


def generate(path: Path, mode: str, item_count: int, location_count: int, movement_count: int, seed: int) -> None:
    for suffix in ("", "-wal", "-shm"):
        sidecar = path.with_name(path.name + suffix)
        if sidecar.exists():
            sidecar.unlink()

    rng = random.Random(seed)
    locations, items, stock, movements = build_rows(rng, item_count, location_count, movement_count)

    conn = sqlite3.connect(path)
    try:
        if mode == "tuned":
            conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = OFF")
        conn.executescript(SCHEMA)

        with conn:
            conn.executemany("INSERT INTO locations VALUES (?, ?, ?, ?)", locations)
            conn.executemany("INSERT INTO items VALUES (?, ?, ?, ?, ?, ?)", items)
            conn.executemany("INSERT INTO stock VALUES (?, ?, ?, ?, ?)", stock)
            conn.executemany("INSERT INTO movements VALUES (?, ?, ?, ?, ?, ?, ?, ?)", movements)

        if mode == "tuned":
            conn.executescript(TUNING_INDEXES)
            if has_fts5(conn):
                conn.executescript(FTS)
            else:
                print("note: this sqlite build has no FTS5; skipping the full-text table", file=sys.stderr)
            conn.execute("ANALYZE")
            conn.execute("PRAGMA user_version = 1")
        conn.commit()
    finally:
        conn.close()

    print(
        f"wrote {path} [{mode}] with {len(items):,} items, {len(locations):,} locations, "
        f"{len(stock):,} stock rows, {len(movements):,} movements"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("database", help="path of the database file to create (overwritten if present)")
    parser.add_argument("--mode", choices=("untuned", "tuned"), default="untuned")
    parser.add_argument("--items", type=int, default=20_000)
    parser.add_argument("--locations", type=int, default=200)
    parser.add_argument("--movements", type=int, default=150_000)
    parser.add_argument("--seed", type=int, default=20261002, help="fixed by default so runs are comparable")
    args = parser.parse_args(argv)

    generate(Path(args.database), args.mode, args.items, args.locations, args.movements, args.seed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
