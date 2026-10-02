# Phase 7 — Accessibility and input ergonomics

**Goal.** Make the app usable at speed, by keyboard, on the hardware it actually
runs on. In a warehouse this is not a compliance exercise — it is the difference
between an operator working through a pick list quickly and fighting the interface
with gloves on.

**Risk.** Low. Mostly additive.

**Prerequisites.** Phase 6 complete, so the tokens exist to fix contrast in one
place.

## Why this is more than compliance

The operating conditions here are specific and unusual: gloved hands, a tablet or
a fixed terminal, variable light, a barcode scanner acting as a keyboard, and a
user who repeats the same five actions hundreds of times a day. That user will
learn keyboard shortcuts and will never move their hand to the mouse if they can
avoid it. Optimising for that is both an accessibility improvement and the single
biggest throughput win available in the interface.

## Guardrails

- Test by keyboard only. Unplug the mouse, or resolve not to touch it, for the
  whole phase.
- Do not remove a focus outline. If one is visually wrong, restyle it.
- Measure contrast; do not judge it by eye, which is unreliable, especially on a
  good monitor.

---

## Task 7.1 — Fix contrast across all themes

**Why.** Low-contrast text is unreadable in bright light or on a cheap terminal
screen. The usual offenders are exactly the ones an app relies on for hierarchy:
muted labels, placeholder text, and disabled controls.

**Do.** Measure every foreground and background pairing in the tokens from Phase 6,
in all three themes. The thresholds are 4.5:1 for body text, 3:1 for text at 18 pt
or 14 pt bold and above, and 3:1 for the boundary of any interactive control and
for focus indicators.

Adjust the token values, not individual rules. Pay specific attention to:

- Muted and secondary text, which is almost always too light.
- Placeholder text, which is often below 3:1.
- Disabled controls, which must still be legible — "disabled" should be
  communicated by more than low contrast alone.
- White or light text on a mid-tone accent, which frequently fails.
- The focus ring against both the control and the page behind it.

Record every pairing and its measured ratio in the table at the bottom of this
file.

**Files.** The tokens stylesheet.

**Verify.** The table is complete, every ratio meets its threshold, and the ratios
were measured rather than estimated.

**Commit.** `fix: meet contrast thresholds across all themes`

---

## Task 7.2 — Make focus visible and managed

**Why.** Keyboard operation is impossible without knowing where focus is, and
focus that is lost after an action silently forces the user back to the mouse.

**Do.** Two parts.

**Visible.** Give every interactive element a `:focus-visible` style with a clear
outline, at least 2 px, 3:1 against its surroundings, with an offset so it does not
merge into the control's own border. Use `:focus-visible` rather than `:focus` so
the ring appears for keyboard users without decorating every mouse click.

**Managed.** Focus must go somewhere sensible after every action:

- Opening a dialog moves focus into it; closing it returns focus to whatever
  opened it.
- A dialog traps Tab within itself, and Escape closes it.
- Deleting a row moves focus to a neighbouring row, not to the top of the page.
- Submitting a form that stays on the page returns focus to the primary input —
  which for this app usually means the scan field.
- Content appearing asynchronously never steals focus from what the user is doing.

**Files.** The focus styles and the dialog and form components.

**Verify.** Tab through every screen with no mouse. Focus must be visible at every
stop, follow the visual order, and never disappear or land on something invisible.
Open and close every dialog by keyboard alone. Record a screen capture of a full
keyboard pass.

**Commit.** `fix: visible focus indicators and focus management`

---

## Task 7.3 — Make the frequent paths keyboard-driven

**Why.** This is the throughput win. An operator who can complete a receive or a
pick without leaving the keyboard works several times faster than one who clicks.

**Do.** Define shortcuts for the frequent actions and make them discoverable:

- `/` or `Ctrl`/`Cmd`+`F` focuses search.
- `Escape` cancels the current action, closes the dialog, or clears the search —
  consistently, in that priority order.
- `Enter` commits the field or the form. In a table, opens the focused row.
- Arrow keys move between table rows; `Home` and `End` jump to the ends.
- A single key returns to the scan field from anywhere.
- `?` shows the shortcut list, which must exist and be reachable from the
  interface, not only from documentation.

Then fix tab order: it must follow the visual order. Where it does not, the fix is
to reorder the markup rather than to apply `tabindex` values above 0, which create
a separate tab sequence that is difficult to maintain. Make sure no interactive
element is reachable only by mouse — a clickable `div` needs a real button, or at
minimum a role, a `tabindex`, and key handlers.

**Files.** A shortcut handler, the table navigation, and the help panel.

**Verify.** Complete the three most frequent workflows end to end using only the
keyboard, and record it as a screen capture. Confirm no shortcut fires while the
user is typing in a text field.

**Commit.** `feat: keyboard shortcuts and navigation for frequent actions`

---

## Task 7.4 — Announce what changes

**Why.** A confirmation that appears visually is invisible to a screen reader and
easy to miss on a busy screen. For scanning in particular, the user is looking at
the item rather than the display.

**Do.** Add a polite live region for status messages — scan confirmed, quantity
updated, saved — and an assertive one for errors, so they interrupt. Keep the
messages short and specific: the item and the new value, not "Success".

Also give the interface a correct semantic structure, since that is what makes it
navigable: one `h1` per screen with headings in order, landmarks for the main
regions, labels properly associated with every input (not placeholder text acting
as a label, which vanishes on typing), and real `<table>` markup with `<th>` and
scope for tabular data rather than a grid of `div`s.

**Files.** The live region component, and the markup of each screen.

**Verify.** Run an automated check — browser devtools accessibility audit, or
`axe` — and record the remaining issues with a reason for each. Then perform one
scan and one error with a screen reader enabled (VoiceOver, NVDA, or Narrator) and
confirm both are announced.

**Commit.** `feat: announce status changes and correct the semantic structure`

---

## Task 7.5 — Size the targets for gloves

**Why.** A control sized for a mouse pointer cannot be hit reliably with a gloved
finger on a tablet, and a mis-tap in a stock system means a wrong quantity.

**Do.** Give every touch target at least 44 by 44 CSS pixels of hit area —
enlarging the hit area with padding is fine where the visual element must stay
small. Leave at least 8 px between adjacent targets. Where a destructive action
sits next to a frequent one, separate them further or move the destructive action
behind a confirmation.

Then check the real screen: set the viewport to the device size recorded in
`STACK.md` and confirm nothing important requires horizontal scrolling or sits
under a virtual keyboard. If the device is used in portrait, check portrait.

Also confirm the interface works at 200% zoom and at the system's large-text
setting, which operators in poor light often turn on.

**Files.** Component styles and layout.

**Verify.** Screenshot every screen at the target device size, and again at 200%
zoom. Measure the smallest interactive target and record it.

**Commit.** `fix: size touch targets for gloved use`

---

## Task 7.6 — Respect motion and contrast preferences

**Why.** The transitions from Phase 5 cause discomfort for some users, and the
system high-contrast setting should be honoured rather than overridden.

**Do.** Under `prefers-reduced-motion: reduce`, reduce transition durations to
near zero rather than removing transitions, so that no logic depends on a
transition event that never fires. Disable anything that moves on its own —
shimmer, auto-scroll, parallax. Keep instantaneous state changes; the information
must survive.

Under `prefers-contrast: more`, select the high-contrast theme from Phase 6.

**Files.** Stylesheets and the theme selection logic.

**Verify.** With reduced motion forced in devtools, walk every screen: nothing
animates, nothing is stuck part-way, every dialog still opens and closes. Record
the pass.

**Commit.** `fix: honour reduced-motion and contrast preferences`

---

## Exit criteria

- [ ] Every token pairing meets its contrast threshold in all three themes, with
      measured ratios recorded below.
- [ ] Focus is visible at every stop and follows visual order.
- [ ] Focus is managed after every dialog, deletion, and submission.
- [ ] Every interactive element is reachable by keyboard.
- [ ] The three most frequent workflows are completable without a mouse, recorded.
- [ ] A discoverable shortcut list exists.
- [ ] Status and error messages are announced.
- [ ] Headings, landmarks, labels, and table semantics are correct.
- [ ] No touch target smaller than 44 px; smallest measured value recorded.
- [ ] The interface works at the target device size and at 200% zoom.
- [ ] Reduced-motion and high-contrast preferences are honoured.
- [ ] Automated accessibility issues are zero, or each is justified in writing.

## Contrast measurements

| Foreground token | Background token | Theme | Ratio | Threshold | Pass |
| --- | --- | --- | --- | --- | --- |
| | | | | | |

## Results

| Measurement | Value |
| --- | --- |
| Smallest interactive target | |
| Keyboard-only workflows completed | |
| Remaining automated accessibility issues | |
