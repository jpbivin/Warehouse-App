# Phase 3 — Off-thread data access

**Goal.** No database work on the thread that draws the interface. After Phase 2
the queries are fast, but "fast" is not "never blocks" — this phase makes a slow
query degrade into a brief loading state rather than a frozen window.

**Risk.** Moderate. Every call site's calling convention changes. Do it in small
commits, one screen at a time.

**Prerequisites.** Phases 1 and 2 complete. All database access already goes
through one module, which is what makes this a contained change.

## Why this is still needed after Phase 2

Phase 2 fixed the queries you knew to measure, at the volume you measured at. It
cannot fix:

- A query against data larger than you tested with.
- A write that happens to land while a read is in flight.
- A report that is genuinely expensive and cannot be indexed away.
- An operating-system level stall: a flush, a virus scanner touching the file, a
  slow disk.

Each of those freezes the window if queries run on the UI thread, and none of them
is reliably reproducible — which matches "occasional lag" more closely than a
simple slow query does. Moving the work off-thread converts every one of them from
a freeze into a delay, and a delay can be shown to the user.

The budget to hold is 50 ms: a task longer than that on the UI thread delays input
handling and is perceptible.

## Guardrails

- Convert one screen at a time, and keep the app working after each commit.
- Do not add a caching layer in this phase. Correctness of the async conversion
  first; caching is Phase 5.
- Never use a synchronous cross-thread call. It reintroduces exactly the block
  this phase removes, with extra steps.

---

## Task 3.1 — Establish the boundary

**Why.** Each runtime has one correct way to get blocking work off the UI thread.
Picking it and writing it down prevents the following tasks from mixing idioms.

**Do.** Choose per `STACK.md` and record the choice at the bottom of this file.

**Electron.** `better-sqlite3` is synchronous by design, so running it in the main
process blocks the main process, which also services window and input events.
Move the database module into a `utilityProcess` (or a `worker_threads` worker)
and talk to it over a message port. In the renderer, expose it through
`contextBridge` with `ipcRenderer.invoke`, which is promise-based. Delete every
`ipcRenderer.sendSync` — it blocks the renderer until the main process replies,
and it is the most common cause of a frozen Electron window.

**Tauri.** Rust commands declared `async` run off the UI thread already, but
`rusqlite` is blocking, so wrap its calls in `tauri::async_runtime::spawn_blocking`
to keep them off the async executor's threads. Hold connections in a pool
(`r2d2_sqlite`) in managed state, and apply the Phase 1 pragmas in the pool's
connection customiser so pooled connections are configured too.

**Browser-only (`sql.js` / `wa-sqlite`).** This is the stack where the problem is
most severe: on the main thread, every query blocks rendering, and loading the
wasm module and the database blocks the first paint. Move the database into a
dedicated Web Worker and communicate by `postMessage` (Comlink makes this tidy if
a dependency is acceptable). For `wa-sqlite` with OPFS, a worker is required
anyway, because the synchronous access handle API is only available there.

**Python desktop.** Any `sqlite3` call in a Tk callback or a Qt slot freezes the
window for its duration. Run a single database thread that consumes a request
queue. For Tkinter, deliver results back by polling a result queue from
`root.after(16, …)` — Tk widgets may only be touched from the main thread. For
Qt, emit a signal from a `QThread` or use `QThreadPool` with `QRunnable`; Qt
delivers signals to the receiving thread's event loop, so this is safe. Pass
`check_same_thread=False` only if the connection really is shared, and serialise
access with a lock if so.

**.NET desktop.** Use `async`/`await` with `Task.Run` for the blocking call, and
return to the UI context for the update. Never `.Result` or `.Wait()` on the UI
thread.

**Files.** This file only — a decision record, no code.

**Verify.** The chosen approach is written down with the specific API names, and
it matches what `STACK.md` says the runtime is.

**Commit.** `docs: record the off-thread data access approach`

---

## Task 3.2 — Move the database module across the boundary

**Why.** One move, after which every call site's change in 3.3 is mechanical.

**Do.** Relocate the module from Phase 1 behind the boundary chosen in 3.1 and
give it a request/response protocol: a message carrying a statement name, bind
parameters, and a request id; a reply carrying the same id and either rows or an
error. Serialise errors properly — an exception crossing a worker boundary
usually arrives as an empty object unless the message and stack are copied
explicitly, and losing error detail here will cost hours later.

Keep the public API of the module the same shape as before, except that every
method now returns a promise or future. Nothing else should need to know where the
database lives.

**Files.** The database module, the new worker/process entry point, and the build
configuration if workers need bundling.

**Verify.** One screen is converted and works end to end. The app starts, the
screen loads, and an induced error (query a table that does not exist) surfaces a
useful message rather than a silent failure.

**Commit.** `refactor: run the database module off the UI thread`

---

## Task 3.3 — Make every call site await

**Why.** Any remaining synchronous call either blocks or, worse, silently receives
a pending promise and renders nothing.

**Do.** Convert the call sites one screen at a time, one commit per screen. In each
one: await the result, show the loading state the screen already has (if it has
none, that is Phase 5's job — leave a `TODO` referencing it), and handle the
error case.

Watch for patterns that compile but are wrong: a database call inside a render
function, a loop that awaits sequentially where the calls are independent and
should be `Promise.all`, and a result used before it resolves.

**Files.** One screen per commit.

**Verify.** `rg` finds no synchronous database call outside the module. Every
screen in `STACK.md` loads, and each one still shows the same data as before —
compare against a screenshot taken before the conversion.

**Commit.** `refactor: await database access in the <name> screen`

---

## Task 3.4 — Guard against stale responses

**Why.** Once calls are asynchronous, replies can arrive out of order. Type
`abc` quickly and the response for `ab` may land after the response for `abc`,
leaving the list showing results for a query the user has moved past. This reads
as a bug, not as lag, and it is introduced by Phase 3 itself.

**Do.** For every view that issues a query in response to changing input, keep the
id of the most recent request and discard any reply that does not match it.
Where the runtime supports cancellation (`AbortController`, a cancellation token,
a Tauri channel), also cancel the superseded request so the work is not wasted.

**Files.** The views that query on input change.

**Verify.** Type a long search term quickly, then delete it quickly. The results
shown must always correspond to the text in the box. Add a temporary log of
request id, query text, and whether the reply was applied or discarded, confirm
the behaviour, then remove the log before committing.

**Commit.** `fix: ignore stale query responses`

---

## Task 3.5 — Debounce and coalesce rapid input

**Why.** A query per keystroke is a query per keystroke even when it is fast.
Debouncing removes most of them for free.

**Do.** Debounce text inputs that trigger queries by 150 to 250 ms — long enough
to skip intermediate keystrokes, short enough to feel immediate. Leading-edge
behaviour (fire at once, then suppress) feels better for short queries than
trailing-edge.

Two cases must *not* be debounced, because they are single discrete events where
any delay is pure added latency: a barcode scan, and pressing Enter.

Also coalesce duplicate in-flight requests: if the same statement with the same
parameters is already pending, attach to it rather than issuing a second one.

**Files.** The input handlers, plus the database module for coalescing.

**Verify.** Log the queries issued while typing a ten-character search at normal
speed. Before: about ten. After: two or three. Paste both counts. Confirm a
scanned barcode still resolves without any added delay.

**Commit.** `perf: debounce query-triggering input and coalesce duplicates`

---

## Task 3.6 — Verify the UI thread stays free

**Why.** The exit condition for the phase, and the measurement the user will feel.

**Do.** Reproduce every stall in the lag inventory while recording.

- **Web-based:** Performance panel, or `PerformanceObserver` on `longtask`
  entries. Record the longest task during each interaction.
- **Python:** log elapsed time around each UI callback and record the maximum.
- **.NET:** the diagnostic tools' UI responsiveness view.

Record the longest blocking task per interaction in the results table. Anything
over 50 ms still has work on the wrong thread; find it before closing the phase.

**Files.** `docs/polish-plan/baseline/after-phase-3.md` and this file.

**Verify.** No interaction exceeds 50 ms of blocking work on the UI thread.

**Commit.** `docs: record UI thread measurements after phase 3`

---

## Exit criteria

- [ ] The boundary approach is recorded and matches the runtime.
- [ ] No database call runs on the UI thread, demonstrated by search and by profile.
- [ ] No synchronous cross-thread or cross-process call remains.
- [ ] Every screen loads and shows the same data as before the conversion.
- [ ] Stale responses are discarded; fast typing never shows results for stale input.
- [ ] Query-triggering input is debounced; scans and Enter are not.
- [ ] Duplicate in-flight requests are coalesced.
- [ ] No interaction blocks the UI thread for more than 50 ms.
- [ ] Errors crossing the boundary arrive with a usable message.

## Decision record

| Question | Choice |
| --- | --- |
| Boundary mechanism | |
| Message protocol | |
| Cancellation mechanism | |
| Debounce interval | |

## Results

| Interaction | Longest blocking task, phase 2 | After phase 3 |
| --- | --- | --- |
| | | |

| Measurement | Phase 2 | After phase 3 |
| --- | --- | --- |
| Queries per ten-character search | | |
| Worst stall from the lag inventory | | |
| Longest UI-thread task overall | | |
