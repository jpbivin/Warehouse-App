# Phase 6 — Visual design system

**Goal.** Replace ad-hoc visual decisions with a small set of reusable ones. This
is the phase that addresses "polish the UI" directly.

**Risk.** Low functionally, high visually. Every commit changes appearance, so
take a screenshot of every screen before starting.

**Prerequisites.** Phase 4 complete, so restyling does not fight a rendering
problem.

## Why this works

An interface generated in one pass is usually *locally* reasonable and *globally*
inconsistent: three greys that are nearly the same, padding of 12, 14, and 16 px
on sibling cards, four button variants that differ by accident. Each instance is
defensible; the accumulation is what reads as unfinished. Consistency is most of
perceived quality, and it is cheap to impose once the values live in one place.

Do this in the order below. Tokens first, then the scales, then the components
that consume them. Restyling components before the tokens exist means doing it
twice.

## Guardrails

- Screenshot every screen before Task 6.1 and compare after each task. Reviewing a
  visual change without a before image is guesswork.
- Change values, not layout. Reorganising a screen is a design decision for the
  user, not a polish task.
- No new dependency. A design system here is a stylesheet of custom properties,
  not a component library.

---

## Task 6.1 — Extract design tokens

**Why.** One place to change, and the precondition for consistency, theming, and
the contrast fixes in Phase 7.

**Do.** Inventory the values actually in use:

```bash
rg -o '#[0-9a-fA-F]{3,8}\b' -- <style dir> | sort | uniq -c | sort -rn
rg -o '\b\d+px\b' -- <style dir> | sort | uniq -c | sort -rn
```

Expect clusters of near-duplicates. Collapse each cluster to one value and define
them as custom properties on `:root`:

- **Colour.** A neutral ramp of about seven steps from background to strongest
  text; one accent with hover, active, and subtle variants; and semantic colours
  for success, warning, danger, and info, each with a background pairing. Name
  them by role, not appearance — `--color-surface`, `--color-text-muted`,
  `--color-danger` — so a theme can redefine them. `--color-gray-200` used for
  text cannot be re-themed without a rename.
- **Spacing.** A single scale: 4, 8, 12, 16, 24, 32, 48, 64.
- **Radius.** Three values: small for inputs and buttons, medium for cards, full
  for pills.
- **Shadow.** Three levels, used to signal elevation only.
- **Border.** One width, one default colour, one focus colour.
- **Motion.** The durations and easings chosen in Task 5.5.
- **Z-index.** Named layers for dropdown, sticky header, modal, and toast, so
  stacking stops being guesswork.

Then replace the literals with the tokens, one stylesheet per commit.

**Files.** A new tokens stylesheet, then the existing stylesheets.

**Verify.** The searches above return no remaining colour literals or arbitrary
pixel values outside the tokens file. Screenshots are visually unchanged except
where a near-duplicate was collapsed — review each of those deliberately.

**Commit.** `style: extract design tokens`

---

## Task 6.2 — Put everything on the spacing scale

**Why.** Inconsistent spacing is the most visible symptom of an unfinished
interface, and the easiest to fix now that the scale exists. Related elements
closer together and unrelated ones further apart is also how a dense screen
becomes scannable.

**Do.** Replace every margin, padding, and gap with a token. Round to the nearest
step rather than adding a new one. Make the rhythm intentional: consistent gaps
within a group, a larger consistent gap between groups, and the same page padding
everywhere. Prefer `gap` on a flex or grid container over margins on children,
which avoids collapsing-margin surprises and keeps spacing in one place.

**Files.** Stylesheets, one area per commit.

**Verify.** No spacing value outside the scale remains. Compare screenshots: the
alignment of sibling elements should visibly improve.

**Commit.** `style: align spacing to the scale`

---

## Task 6.3 — Define the type scale, with tabular numerals

**Why.** Unrelated font sizes make a screen feel noisy and make hierarchy
ambiguous. And in an inventory app specifically, numbers matter: by default most
fonts render digits at differing widths, so a column of quantities does not line
up and cannot be compared or scanned down.

**Do.** Define a scale of five or six sizes with a line height for each — tighter
for headings, 1.5 or so for body text — and two or three weights. Map every
existing size onto it.

Then, for every column and field containing a number, set:

```css
font-variant-numeric: tabular-nums;
```

and right-align numeric table columns so digits of the same magnitude line up.
This single change does more for the legibility of a stock table than anything
else in the phase. Also set `font-feature-settings` or the equivalent for any
monospaced SKU or barcode display.

Check text contrast against the tokens while here; Phase 7 audits it properly, but
fixing the obvious cases now avoids revisiting.

**Files.** The tokens stylesheet and the text and table styles.

**Verify.** Screenshot a quantity column before and after: digits must align
vertically. Confirm no text uses a size outside the scale.

**Commit.** `style: define the type scale and use tabular numerals for quantities`

---

## Task 6.4 — Normalise the components

**Why.** Four button variants that differ by accident make the interface look
assembled rather than designed, and they make it unclear which action is primary.

**Do.** For each repeated element — button, input, select, card, badge, table,
modal, toast — settle on one implementation with explicit variants, and replace
every ad-hoc instance with it.

Each interactive component needs all of its states defined, not just the default:
rest, hover, active, focus-visible, disabled, and loading. Missing states are what
make an interface feel inert. Define exactly one primary button style and use it
for one action per screen.

For tables specifically, since this app is mostly tables: a sticky header so column
meaning survives scrolling, consistent column alignment (text left, numbers
right), a visible row hover, a distinct selected-row style, and a clear sort
indicator on the sorted column.

**Files.** One component per commit.

**Verify.** `rg` for the component's class or tag shows only the shared
implementation in use. Walk each state of each component and confirm it is
styled. Screenshots show consistent treatment across screens.

**Commit.** `style: normalise the <component> component`

---

## Task 6.5 — Design the empty, error, and partial states

**Why.** These are the states a generated app usually omits, and the ones a real
user hits on their first day, when every list is empty. A blank area with no
explanation is where an app feels broken rather than merely unfinished.

**Do.** For every view that shows data, design four states and make sure each is
reachable and tested:

- **Empty because nothing exists yet.** Say so, and offer the action that creates
  the first one. This is the first-run experience.
- **Empty because the filter or search matched nothing.** Distinguish it clearly
  from the above — the remedy is different — and offer to clear the filter. Echo
  the search term.
- **Error.** Say what failed in concrete terms, and offer a retry. "Could not read
  the stock table" is useful; "An error occurred" is not. Keep the technical detail
  available but not prominent.
- **Partial.** Some data loaded and some did not: show what there is and mark what
  is missing, rather than discarding everything.

Keep them visually quiet. An empty state should be calm and informative, not a
large illustration that gets in the way on the hundredth viewing.

**Files.** One view per commit.

**Verify.** Reach every state deliberately — empty the table, search for nonsense,
induce a read failure — and screenshot each. All four screenshots must be
committed or attached.

**Commit.** `feat: empty, error, and partial states for <view>`

---

## Task 6.6 — Add a dark theme and a high-contrast theme

**Why.** Specific to this app's setting. Warehouses are variously dim and brightly
lit; a fixed light theme is glaring in one and washed out in the other. Because the
tokens are in place, this is a matter of redefining values rather than restyling.

**Do.** Add theme variants that override the colour tokens only, selected by a
`data-theme` attribute on the root with a default following
`prefers-color-scheme`. Persist the user's choice.

For dark, do not simply invert. Pure black backgrounds with pure white text cause
halation and are tiring; use a very dark grey surface and a slightly off-white
text colour. Shadows read poorly on dark surfaces — convey elevation with a
lighter surface colour instead. Desaturate accents slightly, since saturated
colour on a dark background vibrates.

For high contrast, raise every pairing well past the minimum and add visible
borders to controls that rely on background colour alone to define their bounds.

**Files.** The tokens stylesheet and the theme switch.

**Verify.** Screenshot every screen in every theme. Check contrast on each theme
(Phase 7 does this systematically). Confirm nothing becomes invisible, especially
disabled controls, placeholder text, and focus rings.

**Commit.** `feat: dark and high-contrast themes`

---

## Exit criteria

- [ ] No colour literal or arbitrary pixel value outside the tokens file.
- [ ] Every spacing value is on the scale.
- [ ] Every font size is on the type scale.
- [ ] Numeric columns use tabular numerals and are right-aligned.
- [ ] One implementation per repeated component, with every state styled.
- [ ] Exactly one primary action per screen.
- [ ] Tables have sticky headers, consistent alignment, and sort indicators.
- [ ] Every data view has empty, filtered-empty, error, and partial states, all
      reached and screenshotted.
- [ ] Light, dark, and high-contrast themes exist and persist.
- [ ] Before and after screenshots of every screen are attached.

## Token inventory

Record the final values so later work matches them.

| Token group | Count | Notes |
| --- | --- | --- |
| Colour | | |
| Spacing | | |
| Radius | | |
| Shadow | | |
| Type size | | |
| Motion | | |
| Z-index | | |
