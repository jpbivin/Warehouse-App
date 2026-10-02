# Stack facts

Filled in by Phase 0, task 0.1. Copy this file to `docs/polish-plan/STACK.md` and
replace every `TODO`. Later phases read this file to decide which of their
branches applies, so an unanswered question here becomes a guess later.

Answer from the code, not from memory. Cite a file path for every answer.

## Application shape

| Question | Answer | Evidence (file path) |
| --- | --- | --- |
| Runtime / framework | TODO | TODO |
| UI layer | TODO | TODO |
| Language(s) and versions | TODO | TODO |
| Package manifest | TODO | TODO |
| Entry point | TODO | TODO |
| How it is started in development | TODO | TODO |
| How it is built / packaged for users | TODO | TODO |
| Automated tests present? | TODO | TODO |
| Lint / format tooling present? | TODO | TODO |
| Total source files, excluding dependencies | TODO | TODO |

Pick exactly one and delete the rest:

- [ ] Electron: renderer plus main process, `better-sqlite3` or `node:sqlite`
- [ ] Tauri: webview plus Rust, `rusqlite`
- [ ] Browser-only: `sql.js` or `wa-sqlite`, persisted to OPFS or IndexedDB
- [ ] Python desktop: Tkinter / PyQt / PySide, stdlib `sqlite3`
- [ ] .NET desktop: WPF / WinForms, `Microsoft.Data.Sqlite`
- [ ] Other: TODO

## Database access

| Question | Answer | Evidence |
| --- | --- | --- |
| SQLite driver and version | TODO | TODO |
| Database file location at runtime | TODO | TODO |
| Is the file on local disk, or a network share? | TODO | TODO |
| Number of places that open a connection | TODO | TODO |
| Is there a single data-access module, or is SQL scattered? | TODO | TODO |
| Are connections long-lived or opened per query? | TODO | TODO |
| Which thread or process executes queries? | TODO | TODO |
| Are query calls synchronous from the UI's point of view? | TODO | TODO |
| Are statements prepared once and reused, or rebuilt per call? | TODO | TODO |
| Is any SQL assembled by string concatenation of user input? | TODO | TODO |
| Is there a schema version or migration mechanism? | TODO | TODO |
| Is there any backup mechanism? | TODO | TODO |

## Pragmas the app sets today

Read the connection setup code. Record what is actually set, not what should be.
Unset means SQLite's default applies.

| Pragma | Value the app sets | Where |
| --- | --- | --- |
| `journal_mode` | TODO | TODO |
| `synchronous` | TODO | TODO |
| `foreign_keys` | TODO | TODO |
| `busy_timeout` | TODO | TODO |
| `cache_size` | TODO | TODO |
| `temp_store` | TODO | TODO |
| `mmap_size` | TODO | TODO |

## Screens and interactions

List every screen, and for each the data it loads. This becomes the target list
for Phases 2 through 5.

| Screen / view | Queries it runs | Rows rendered at realistic volume | Feels slow? |
| --- | --- | --- | --- |
| TODO | TODO | TODO | TODO |

## Data volume

Realistic volume, not current test data. Ask the user if unknown, and record the
assumption.

| Table | Rows today | Rows expected in 2 years |
| --- | --- | --- |
| TODO | TODO | TODO |

## Hardware the app runs on

Lag is relative to the machine. A plan tuned on a developer laptop can still be
slow on a warehouse terminal.

| Question | Answer |
| --- | --- |
| Typical device (model, CPU, RAM) | TODO |
| Display size and resolution | TODO |
| Touch, mouse, or both? | TODO |
| Barcode scanner? How does it deliver input? | TODO |
| Disk: SSD or spinning? | TODO |
| Operating system and version | TODO |

## Open questions for the user

Things that could not be answered from the code and that change the plan.

- TODO
