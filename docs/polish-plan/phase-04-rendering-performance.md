# Phase 4 — Rendering performance

**Goal.** Hold 60 frames per second while scrolling and interacting. After Phase 3
the data arrives without blocking; this phase stops the act of displaying it from
blocking either.

**Risk.** Moderate. Virtualising a list changes how it is built, which affects
selection, keyboard navigation, and anything that measures the list's height.

**Prerequisites.** Phase 3 complete.

**Scope note.** Tasks 4.1 through 4.5 assume a web-based interface (Electron,
Tauri, or browser). For a Python or .NET desktop interface, skip to the
native-toolkit section at the end, which covers the same problems with different
mechanisms.

## The budget

At 60 fps a frame is 16.7 ms, and the browser needs part of that for layout,
paint, and compositing. Scripting per frame should stay near 10 ms. Two
measurements matter more than the average: the longest frame, and whether any
frame exceeds 32 ms, which is the point at which a scroll visibly hitches.

## Guardrails

- Measure with the realistic-volume database from Phase 0. A list of twenty rows
  is fast however it is built.
- Profile before each change and after. Rendering work is easy to move around
  without reducing it.
- Do not change what is displayed, only how.

---

## Task 4.1 — Virtualise the long lists

**Why.** A thousand inventory rows is a thousand subtrees the browser must lay out,
paint, and keep in memory, for perhaps thirty that are visible. The cost is paid on
the first render and again on every change that invalidates layout. This is
normally the largest single rendering cost in an inventory app.

**Do.** For each list or table that can exceed roughly 100 rows, render only the
visible window plus a small overscan. Either use the framework's established
virtualiser (TanStack Virtual, `react-window`, or the equivalent) if a dependency
is acceptable, or implement it directly: a scroll container of the full height, an
absolutely positioned window of rows, and an index derived from `scrollTop`.

Fixed row heights make this much simpler and are usually acceptable for a data
table. If rows must vary, measure and cache heights rather than guessing, or
accept an estimated-height implementation and its slight scrollbar drift.

Things that break when a list is virtualised, and must be re-checked:

- "Select all" that walks DOM nodes rather than the data.
- Keyboard navigation to a row that is not currently rendered.
- Browser find-in-page, which cannot see unrendered rows. If the app relies on it,
  its own search must be good enough to replace it.
- Anything reading the list's `scrollHeight` to infer row count.

**Files.** One list component per commit.

**Verify.** Record the DOM node count and the time to first paint for the list,
before and after, at realistic volume. Then scroll the full length of the list
while profiling and record the longest frame. Paste all three numbers.

**Commit.** `perf: virtualise the <name> list`

---

## Task 4.2 — Stop re-rendering the whole list for one row's change

**Why.** Updating a single quantity should touch one row. A naive implementation
rebuilds the list's markup from the full data array, so every change costs a full
render — most visible when a scan updates a count and the whole table flashes.

**Do.** Depends on how the interface is built:

- **A framework with a virtual DOM:** give each row a stable key derived from the
  row's identity, never the array index. Index keys make the framework reuse the
  wrong nodes on insert or sort, which produces both wasted work and visible
  glitches. Memoise the row component so it re-renders only when its own data
  changes, and make sure the props it receives are stable — a fresh object or
  arrow function created in the parent's render defeats memoisation entirely.
- **Direct DOM manipulation:** keep a map from row id to its element and update
  that element's text in place instead of rebuilding `innerHTML`. Reassigning
  `innerHTML` destroys and recreates nodes, which also loses focus and selection.

**Files.** The list and row components.

**Verify.** With a render counter or the framework's profiler, change one row's
quantity and confirm only that row re-renders. Paste the before and after counts.

**Commit.** `perf: update single rows without re-rendering the list`

---

## Task 4.3 — Animate only `transform` and `opacity`

**Why.** Animating `width`, `height`, `top`, `left`, or `margin` forces layout on
every frame of the animation, and layout cost scales with how much of the page is
affected. `transform` and `opacity` are handled by the compositor and can run
without layout or paint at all. The visual result is usually identical.

**Do.** Find the animated properties:

```bash
rg -n 'transition|@keyframes|animate' -- <style dir>
```

Rewrite each to use `transform` (`translate`, `scale`) or `opacity`. A slide-in
becomes `translateX`; a grow becomes `scale`. Where a genuine height animation is
needed — an expanding detail panel — animate `transform: scaleY` on a wrapper, or
accept the cost and keep it off anything that animates during scroll.

Keep transitions short. 150 to 200 ms for small state changes and up to 300 ms for
a panel or modal; longer than that reads as sluggish rather than polished.

Use `will-change` only on elements that are about to animate, and remove it
afterwards. Left permanently on many elements it costs memory and can make things
slower.

**Files.** Stylesheets, and any inline animation.

**Verify.** Profile one animation before and after. Layout and paint should drop to
near zero per frame. Record the longest frame during the animation.

**Commit.** `perf: animate with transform and opacity only`

---

## Task 4.4 — Skip work for off-screen content

**Why.** Content that is scrolled out of view, in a collapsed panel, or on an
inactive tab still costs layout and paint unless the browser is told it can skip
it.

**Do.** Apply `content-visibility: auto` with a `contain-intrinsic-size` hint to
large off-screen blocks — collapsed sections, inactive tab panels, cards below the
fold. The size hint matters: without it the scrollbar jumps as content is
realised. Add `contain: layout paint` to components whose internal changes should
not be able to invalidate layout outside themselves.

Do not apply `content-visibility: auto` to rows inside the virtualised list from
4.1; the virtualiser already handles that, and the two together just add work.

**Files.** Stylesheets.

**Verify.** Record layout and paint time for the heaviest screen before and after.
Then confirm the scrollbar does not jump while scrolling, and that in-page search
still finds what users expect.

**Commit.** `perf: skip layout and paint for off-screen content`

---

## Task 4.5 — Remove layout thrash

**Why.** Reading a geometry property (`offsetHeight`, `getBoundingClientRect`,
`scrollTop`) forces the browser to flush pending layout. Alternating reads and
writes in a loop forces a layout per iteration — the pattern is quadratic and is
the usual explanation for a surprisingly slow interaction in otherwise reasonable
code.

**Do.** Find the reads:

```bash
rg -n 'offsetWidth|offsetHeight|offsetTop|scrollTop|scrollHeight|getBoundingClientRect|getComputedStyle' -- <source dir>
```

For each one inside a loop or interleaved with style writes, batch all the reads
first, then all the writes. Where the write can wait a frame, do it in
`requestAnimationFrame`. For visibility checks, prefer `IntersectionObserver`,
which reports asynchronously and does not force layout at all.

**Files.** The call sites found.

**Verify.** Profile the affected interaction and confirm the repeated
"Recalculate Style" and "Layout" entries are gone. Record the total layout time
before and after.

**Commit.** `perf: batch DOM reads and writes to avoid forced layout`

---

## Native toolkit equivalents

Skip the above if the interface is Python or .NET, and do these instead. The
problems are the same; only the mechanisms differ.

**Tkinter.** A `Treeview` holding thousands of rows is slow to populate and to
update. Insert only the visible window and re-populate on scroll, which is
virtualisation by hand. Never call `update()` inside a loop — it pumps the event
loop re-entrantly and causes both slowness and subtle bugs; use
`update_idletasks()` if a redraw is genuinely needed. Batch inserts between a
single pair of detach/reattach calls on the tree.

**PyQt / PySide.** Replace any widget-per-row approach with `QTableView` or
`QTreeView` over a model derived from `QAbstractTableModel`. Qt's views are
virtualised already — they only request data for visible cells — so the main thing
to get right is that `data()` is cheap and never touches the database. Emit
`dataChanged` for the specific index that changed rather than calling
`modelReset`, which rebuilds the whole view and loses selection and scroll
position.

**WPF.** Confirm `VirtualizingStackPanel.IsVirtualizing` is on (it is by default
for `ListView` and `DataGrid`, and is silently disabled by wrapping the list in a
`ScrollViewer` or by grouping without `VirtualizingPanel.IsVirtualizingWhenGrouping`).
Set `VirtualizationMode="Recycling"` to reuse row containers. Use
`ObservableCollection` so a single item change does not rebind the whole list, and
raise `PropertyChanged` for the specific property.

**Verify.** Same as the web tasks: record the time to populate the list and the
responsiveness of scrolling at realistic volume, before and after.

**Commit.** `perf: virtualise the <name> list`

---

## Exit criteria

- [ ] Every list over 100 rows renders only its visible window.
- [ ] Selection, keyboard navigation, and scroll position still work in every
      virtualised list.
- [ ] A single row's change re-renders only that row.
- [ ] No animation animates a layout-affecting property.
- [ ] Off-screen content is excluded from layout and paint.
- [ ] No forced layout inside a loop.
- [ ] Scrolling the longest list holds 60 fps with no frame over 32 ms.
- [ ] The results table below is filled in.

## Results

| List | Rows at realistic volume | DOM nodes before | after | First paint before | after |
| --- | --- | --- | --- | --- | --- |
| | | | | | |

| Measurement | Phase 3 | After phase 4 |
| --- | --- | --- |
| Longest frame while scrolling | | |
| Frames over 32 ms during a full scroll | | |
| Re-renders when one row changes | | |
| Layout time on the heaviest screen | | |
