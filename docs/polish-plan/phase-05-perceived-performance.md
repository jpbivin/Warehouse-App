# Phase 5 — Perceived performance

**Goal.** Make the app feel instant. The previous phases reduced real latency;
this one removes the remaining latency from the user's experience of it, which is
what "fluid" actually means.

**Risk.** Moderate. Optimistic updates show a result before it is durable, so they
need a correct rollback path. Get that wrong and the interface lies about stock
levels, which is worse than being slow.

**Prerequisites.** Phases 3 and 4 complete.

## The idea

Three numbers define how speed is experienced: under 100 ms reads as immediate,
up to about a second keeps the user's train of thought with no feedback needed,
and beyond that attention wanders and an indication of progress is required. The
aim is for every action to acknowledge within 100 ms, whether or not the
underlying work has finished.

A warehouse app has an unusual advantage here. Its most frequent action — scanning
an item — almost always succeeds, and the user is looking at the scanner, not the
screen. Showing the expected result immediately and reconciling afterwards is both
accurate in practice and dramatically better to use.

## Guardrails

- An optimistic update must be reverted visibly and unmistakably when the write
  fails. Silent divergence between screen and database is not acceptable in a
  stock system.
- Never show a skeleton that does not match the shape of what loads. A placeholder
  that reflows into something different is worse than a blank area.
- Do not fake progress. A bar that fills and then waits destroys trust.

---

## Task 5.1 — Apply writes optimistically

**Why.** Even a 20 ms write plus a re-query costs a visible round trip. Updating
state first and persisting behind it makes the action feel free, and it is
truthful as long as failure is handled.

**Do.** Start with the single most frequent write, which in this app is almost
certainly recording a scan or adjusting a quantity. For each one:

1. Apply the change to the view's state and render it at once.
2. Issue the write.
3. On success, reconcile with what the database returned — do not assume the
   values match, because a trigger, a default, or a concurrent change may differ.
4. On failure, restore the previous value, show a message naming what failed and
   on which item, and leave the user in a position to retry.

Keep the pre-change value for the rollback. Where several optimistic updates can
be outstanding, key them by request id so a late failure reverts the right one.

Do not apply this to actions whose outcome is not predictable — anything that
depends on server-side or trigger-computed values, or that can legitimately be
rejected by a constraint. Guessing wrong there produces a flicker as the display
corrects itself, which feels worse than waiting.

**Files.** One action per commit.

**Verify.** Measure the time from click or scan to visible change; it should be
under one frame. Then force the write to fail (make the file read-only, or
temporarily throw in the module) and confirm the value reverts and the error names
the item. Record both.

**Commit.** `feat: apply <action> optimistically with rollback`

---

## Task 5.2 — Replace spinners with layout-stable skeletons

**Why.** A spinner says "something is happening" and nothing else. A skeleton that
occupies the same space as the content communicates what is coming and, because
the layout does not move when the data arrives, removes the jolt that makes an app
feel unfinished.

**Do.** For each loading state, render a placeholder with the real content's
dimensions: rows of the right height, columns of the right width, a subtle shimmer
driven by `transform` or `opacity` only (per Phase 4). Reserve space for anything
whose size is known in advance, including images and icons.

Two rules that matter more than the visual design:

- **Do not show a skeleton for fast loads.** After Phases 2 and 3 most screens
  load in well under 100 ms, and a skeleton that appears and vanishes reads as a
  flicker. Delay showing it by about 150 ms, and once shown, keep it for a minimum
  of about 300 ms so it cannot flash.
- **Match the final layout exactly.** If the skeleton shows five rows and the data
  renders twelve, the page jumps, which is the thing being avoided.

**Files.** The loading states, one screen per commit.

**Verify.** Capture the layout shift across the load — in a browser, a
`PerformanceObserver` on `layout-shift` entries should report no shift
attributable to the transition. Confirm a fast load shows no skeleton at all.

**Commit.** `feat: layout-stable loading skeletons for <screen>`

---

## Task 5.3 — Make startup usable sooner

**Why.** First impressions of speed are set at launch, and the first interaction
after launch is the one that pays for anything deferred — opening the file,
compiling wasm, preparing statements, warming the page cache.

**Do.** Move that cost to where it is not blocking an interaction:

- Open the database and run migrations during startup, not on first query.
- Prepare the statements the first screen needs at startup.
- Run the first screen's query concurrently with building the interface rather
  than after it.
- Warm the page cache with the first screen's query during startup.
- Where the stack loads wasm (`sql.js`, `wa-sqlite`), begin fetching it as early
  as possible so it overlaps with everything else.

Then measure what is left. Deferring work is only an improvement if it is not
needed immediately; moving the same cost from startup to first click makes the app
feel worse, not better.

**Files.** The startup path and the database module.

**Verify.** Record cold start to usable interface, and separately the time for the
*first* interaction versus a subsequent identical one. The gap between them is
what this task is reducing. Paste before and after for both.

**Commit.** `perf: warm the data path during startup`

---

## Task 5.4 — Make the scan path the fastest path

**Why.** Scanning is the action performed hundreds of times a day. Anything in its
way is multiplied, and this is the interaction by which the app will be judged.

**Do.** Establish how the scanner delivers input (recorded in `STACK.md`); most
behave as a keyboard that types the code and presses Enter. Then:

- Keep focus in the scan field by default, and return focus there after every
  completed action, so no click is needed between scans.
- Never debounce the scan field; it arrives as one discrete event.
- Acknowledge within one frame: the code echoed, the item named, the new quantity
  shown. An optimistic update from 5.1 is what makes that possible.
- Distinguish success from failure without requiring the screen to be read — a
  colour change plus a short sound, since the user is looking at the item. Make
  the sound optional.
- Never block the next scan on a dialog. A rapid double scan must not be lost;
  queue it.
- Handle the unknown barcode as a first-class case, not an error dialog: say what
  was scanned and offer the next step.

**Files.** The scan input handler and its feedback.

**Verify.** Scan twenty codes in rapid succession, including one unknown. All
twenty are recorded in order, none is lost, and the unknown one does not interrupt
the sequence. Record the median time from scan to acknowledgement.

**Commit.** `feat: make the scan path immediate and uninterruptible`

---

## Task 5.5 — Smooth the state transitions

**Why.** Instant state changes with no transition read as abrupt; slow ones read
as sluggish. The small, consistent motion is most of what separates an interface
that feels finished from one that does not.

**Do.** Apply a consistent, short transition to the state changes that already
happen: rows appearing and leaving, panels opening, toasts arriving, tabs
changing. Use the token values Phase 6 will formalise — pick them now and record
them so Phase 6 adopts the same numbers rather than contradicting them.

- Small state changes: 150 ms.
- Panels and modals: 200 to 250 ms.
- Easing: ease-out for things entering, ease-in for things leaving.
- `transform` and `opacity` only.

Honour `prefers-reduced-motion` from the start by reducing durations to near zero
rather than removing the transition, so nothing depends on a transition's
completion. Phase 7 audits this.

Do not animate on first paint. A list that animates every row in on load is slow
to settle and draws attention to loading.

**Files.** Stylesheets and the components with state changes.

**Verify.** Profile one transition and confirm it holds 60 fps. Confirm that with
reduced motion requested, the interface still works and nothing is stuck
mid-transition.

**Commit.** `feat: consistent short transitions for state changes`

---

## Exit criteria

- [ ] The most frequent write applies optimistically and reverts visibly on failure.
- [ ] Every loading state is a layout-stable skeleton, delayed so fast loads show
      nothing.
- [ ] No measurable layout shift when data replaces a skeleton.
- [ ] Cold start is inside the budget, and the first interaction is not
      noticeably slower than the second.
- [ ] The scan path acknowledges within one frame, keeps focus, loses no scan, and
      handles unknown codes without interrupting.
- [ ] Transitions are consistent, short, and compositor-only.
- [ ] `prefers-reduced-motion` is honoured.
- [ ] Every interaction in the lag inventory is inside the budget.

## Results

| Interaction | Time to visible feedback, phase 4 | After phase 5 |
| --- | --- | --- |
| | | |

| Measurement | Phase 4 | After phase 5 |
| --- | --- | --- |
| Cold start to usable | | |
| First interaction vs second | | |
| Scan to acknowledgement | | |
| Layout shift on data load | | |
