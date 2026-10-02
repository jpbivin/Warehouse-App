-- Representative read queries for a warehouse interface, for use with:
--   python3 tools/sqlite_doctor.py <db> --sql-file tools/warehouse_queries.sql
--
-- Replace these with the queries the application actually runs during Phase 0.
-- Each query may be preceded by `-- name:` and `-- params:` directive lines;
-- `-- params:` takes a JSON array of bind values.

-- name: inventory_list_by_location
-- params: [12, 50]
SELECT i.sku, i.name, s.quantity, s.updated_at
FROM stock AS s
JOIN items AS i ON i.id = s.item_id
WHERE s.location_id = ?
ORDER BY i.name
LIMIT ?;

-- name: item_search_substring
-- params: ["%sleeve 4%"]
SELECT id, sku, name
FROM items
WHERE name LIKE ?
ORDER BY name
LIMIT 50;

-- name: movement_history_for_item
-- params: [4242]
SELECT moved_at, quantity, operator, from_location_id, to_location_id
FROM movements
WHERE item_id = ?
ORDER BY moved_at DESC
LIMIT 100;

-- name: low_stock_report
-- params: []
SELECT i.sku, i.name, i.reorder_at, sum(s.quantity) AS on_hand
FROM items AS i
JOIN stock AS s ON s.item_id = i.id
GROUP BY i.id
HAVING on_hand < i.reorder_at
ORDER BY on_hand ASC
LIMIT 100;

-- name: inventory_page_keyset
-- params: ["stainless bracket 40mm", 9999, 50]
SELECT i.name, i.id, s.quantity
FROM stock AS s
JOIN items AS i ON i.id = s.item_id
WHERE (i.name, i.id) > (?, ?)
ORDER BY i.name, i.id
LIMIT ?;
