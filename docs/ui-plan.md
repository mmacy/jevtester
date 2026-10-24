# jevtester UI plan

This plan covers the web UI that the frontend session (`JEVTESTER-FRONTEND`) builds. It follows [the plan](plan.md#what-the-ui-must-show), the [handoff notes](handoff.md#frontend-session), and the heat matrix mockup in [`mockups/3-matrix.html`](../mockups/3-matrix.html). It lists the views, the components, each component's states, and the API calls each view makes.

Endpoint names come from the handoff's [starting endpoints](handoff.md#starting-endpoints). Where the UI needs something that list doesn't have, the endpoint is marked *requested*. The backend session has the list of requested changes, and this plan changes to match the contract it publishes.

## Principles

- Every view is a grid. Targets are columns. Options, levels, cases, metrics, or variants are rows. Cell color shows a probability or a relative score.
- One color ramp, from the mockup, means "more" everywhere: probability, a share of cases, or a metric's rank among the targets. A key next to each grid labels it.
- A chosen answer has a gold outline (`--pick`). A warning is amber (`--warn`). An error is red (`--err`).
- A target that can't run keeps its column. The column shows a hatched pattern and the reason, so the grid's shape doesn't change when a target goes down.
- UI text is labels and facts, in sentence case. No sentence explains the UI.

## Stack

The stack matches osr-editor's frontend:

- React 19, TypeScript, and Vite, in `web/`.
- Tailwind CSS 4, with the mockup's CSS variables as theme tokens.
- React Router for the views. Each view has a URL, so a run or a diff can be linked and reloaded.
- Zustand for state shared across views: the target list and the request being edited in Compare.
- API types generated from `docs/openapi.json` with `openapi-typescript` into `web/src/api/generated.ts`, which nobody edits. A thin typed client in `web/src/api/client.ts` wraps `fetch`.
- `@fontsource` packages for Noto Sans, Noto Sans Display, and Noto Sans Mono.
- vitest with Testing Library for components, and Playwright for the views.
- prettier and eslint with osr-editor's settings.

The build writes to `src/jevtester/static/`. In development, Vite proxies `/api` to `http://127.0.0.1:8640`.

### Fixture mode

Until an endpoint is live, the UI reads its fixture from `tests/fixtures/api/`. `npm run dev:fixtures` starts Vite with a middleware that answers each `/api` request from the fixture file named for its method and path, and replays an SSE fixture for run events. Playwright runs against fixture mode, so the frontend gates don't need the backend. A later Playwright project runs the same specs against `jevtester serve`.

## Design tokens

From the mockup's `:root`:

| Token | Value | Use |
|---|---|---|
| `--bg` | `#102029` | Page background |
| `--surface` | `#152a35` | Top bar, side panels, plain cells |
| `--raise` | `#1b3442` | Buttons, status chips |
| `--line` | `#234051` | Borders |
| `--line-soft` | `#1c3644` | Inner borders |
| `--text` | `#dbe8ef` | Body text |
| `--dim` | `#8ea7b6` | Labels, secondary text |
| `--faint` | `#5e7a8b` | Hints, disabled text |
| `--pick` | `#f3c979` | Chosen answer, focus ring, primary button |
| `--warn` | `#f0b45b` | Warnings |
| `--err` | `#ef7a6b` | Errors, broken cases |
| `--ok` | `#8fd3b0` | Ready, fixed cases |

The heat ramp has five stops: `rgb(24,47,59)` at 0, `rgb(31,74,94)` at 0.15, `rgb(47,127,147)` at 0.4, `rgb(99,183,184)` at 0.7, and `rgb(200,236,217)` at 1. Text on a cell switches to dark ink above 0.55.

Type: Noto Sans for body text at 14 px, Noto Sans Display condensed (62.5% to 85% width) for headings, target names, and big numbers, and Noto Sans Mono for ids, question ids, and code. Numbers use tabular figures.

The mockup is dark only. The UI ships dark only for now.

## Layout

A sticky top bar holds the jevtester mark, the view tabs, and the target health strip. Below it, each view fills the page.

Tabs: **Compare**, **Suites**, **Runs**, **Question sets**, **Policies**, **Probes**, and **Targets**. A tab for Claude drafts comes later, with the assist features.

The health strip shows one block per target, colored ready, warning, or down, with a count such as "4 of 5 targets ready". Selecting it opens Targets.

## Views

### Compare

Route: `/` and `/compare`. This is the mockup's first view, the quick test that grows into a full comparison.

Left panel, the request:

- **Quick test.** A state field and a question field, an **Ask** button, and a fact line for what will happen: "Yes or no, on decision-1@foundry".
- **Full request.** Grows from the quick test without losing anything. The state field switches between text and JSON, and shows a JSON parse error inline. Question cards hold an id, a type control (yes or no, choice, or score), the instructions, and the options or levels. Options and levels can be added, removed, and reordered. **Add question** adds a card. The target list has a checkbox for each target. A target that isn't ready has its checkbox turned off and its reason beside it. The button reads **Ask 3 targets**, with the count of checked targets.
- **Quick test** returns to the short form. It's offered only when the request still fits it: one yes-or-no question and one target.

Right panel, the answers matrix:

- One column per target, plus a **Spread** column (max minus min across the ready targets).
- The column header shows the target name, its runtime label, and a status chip: ready, a warning such as "Truncation on", or the error.
- For each question, a group row shows its id, instructions, and type. Below it:
  - Choice: one row per option, a **Confidence** row.
  - Yes or no: a **Yes** row with the probability, a **Confidence** row.
  - Score: one row per level, a **Score** row with a marker on a level axis, a **Confidence** row. A confidence below 0.1 shows in amber.
- A **Speed and cost** group: latency, input tokens, output tokens, and cost, with "local" beside a local target's cost.
- A target with `ok: false` keeps its column, hatched, with its error code and message in the header.
- Each answer warning, such as a truncation warning, shows in the target's header chip.
- The stage header shows when the request was asked and the heat key.

Actions below the matrix:

- **Save as case** opens the save case dialog.
- **Mark expected answers** puts the matrix in a mode where selecting a row sets the expected answer for that question. Score questions take a tolerance.
- **Copy as CLI command** copies the matching `jevtester decide` command.

API calls: `GET /api/targets`, `POST /api/decide`, `GET /api/suites` (for the dialog), `POST /api/suites/{name}/cases`.

### Save case dialog

Fields: the suite (a picker), the case id (filled in with the next free id), tags, and an expected answer for each question, filled in from the marked answers or else blank. If the suite's question set doesn't match the request's questions, the dialog says which question ids differ, and the person can save the state with no expected answers for those questions. **Save case** posts the case and shows a link to the suite.

API calls: `GET /api/suites`, `GET /api/suites/{name}`, `POST /api/suites/{name}/cases`.

### Suites

Routes: `/suites` and `/suites/:name`.

- The list shows each suite's name, question set and version, case count, policy, and default targets.
- A suite's page has a cases grid: one row per case, with its id, a one-line state summary, tags, and one column per question with the expected answer. Draft cases (`provenance: "claude-draft"`) show a "Draft" tag and aren't counted.
- **Start run** opens the run form: targets (checkboxes, not-ready targets turned off with the reason), question set version, repeats, and **Use cache** (on by default). Starting a run opens its run page.
- **Open in compare** loads a case into Compare.

API calls: `GET /api/suites`, `GET /api/suites/{name}`, `GET /api/targets`, `GET /api/question-sets/{name}/versions`, `POST /api/runs`.

### Runs

Routes: `/runs` and `/runs/:id`.

The list shows each run's id, suite, question set version, targets, status, case and job counts, cost, and start time. A running run shows its progress bar.

A run's page, from the mockup's second view:

- **Run bar.** The run id, facts (suite, question set version and baseline, cases, jobs, duration, cost), and a progress bar with segments for sent, from cache, skipped, and failed, each with a count and, for skipped, the target. **Cancel** while it runs. **Rerun without cache** when it has finished.
- **Metrics.** A heat grid with one row per target and one column per metric: accuracy, macro-F1, Brier score, calibration error, p50 latency, p95 latency, and cost per 1,000 requests. Each column is colored by rank among the targets, with lower values ranked higher for error, latency, and cost. A key says which. A skipped target shows its reason across the row. A note names the questions each metric covers.
- **Confusion matrix.** For a choice question and a target, picked with segmented buttons: expected options as rows, answered options as columns. Diagonal cells use the ramp, scaled by recall. Off-diagonal cells with a count are red. Beside it: the count correct and the option with the lowest recall.
- **Calibration.** A reliability table for a question and a target: one row per probability bin, with the mean predicted probability, the observed rate, and the count, and the expected calibration error. Targets that return no probabilities don't appear here.
- **Changed answers.** Picks a baseline run. A table lists each case whose answer changed: case id, state summary, question, the baseline answer and probability, this run's answer and probability, the expected answer, and **Fixed** or **Broken**. Below: counts fixed and broken, and McNemar's p-value. **Step through changes** opens the case stepper.

The page follows live progress over SSE while the run is running, and reconnects if the stream drops.

API calls: `GET /api/runs`, `GET /api/runs/{id}`, `GET /api/runs/{id}/events`, `POST /api/runs/{id}/cancel`, `GET /api/runs/{id}/metrics`, `GET /api/runs/{id}/confusion`, `GET /api/runs/{id}/changes`, `POST /api/runs` (rerun), and *requested* `GET /api/runs/{id}/calibration`.

### Case stepper

Route: `/runs/:id/changes/:case`. Shows one changed case: its state, and the answers matrix with the baseline and this run as columns for each target. **Previous** and **Next** move through the changed cases, and the arrow keys do too.

API calls: *requested* `GET /api/runs/{id}/cases/{case_id}`, for this run and the baseline.

### Question sets

Routes: `/question-sets`, `/question-sets/:name`, and `/question-sets/:name/diff?from=&to=`.

- The list shows each question set, its latest version hash, and the suites that use it.
- A question set's page lists its versions by hash and date. The editor holds the same question cards as Compare's full request. **Save version** saves a new version, and the version list shows its hash.
- The wording checks from `suite check` show beside each question: one dimension per question, concrete criteria, bare-number levels, and a missing abstention option.
- **Diff** picks two versions and shows each question side by side: added, removed, and changed questions, and changed options and levels, marked word by word.

API calls: *requested* `GET /api/question-sets`, `GET /api/question-sets/{name}/versions`, `GET /api/question-sets/{name}/diff`, *requested* `PUT /api/question-sets/{name}`.

### Policies

Routes: `/policies` and `/policies/:name`.

- The policy editor is a YAML text editor with a validation error list, and **Save**.
- **Sweep.** Pick a run, a question, a target, and a threshold range. The result is a line chart with the threshold on the x axis, and the share decided and the error rate on the y axis, with the current threshold marked. A table below lists each point. If the policy has a cost matrix, the chart adds total cost.
- Decision accuracy, the share decided, and the error rate among decided cases show for the selected run.

API calls: *requested* `GET /api/policies`, `GET /api/policies/{name}`, `PUT /api/policies/{name}`, `POST /api/policies/{name}/sweep`.

### Probes

Route: `/probes`.

- The form picks a suite, targets, and the variants: option order, JSON key order, bare-number levels, and state padding. Paraphrase is shown turned off, with "Needs Claude".
- The result grid has one row per case and one column per variant for each target. Cell color is the share of variants whose answer changed. A summary row gives the change rate for each variant and target.
- Selecting a cell shows the original and the variant answers side by side.

A probe starts a run, so the view follows its progress with the same run bar as the Runs view.

API calls: `GET /api/suites`, `GET /api/targets`, `POST /api/probes` (returns a run id), `GET /api/runs/{id}/events`, `POST /api/runs/{id}/cancel`.

### Targets

Route: `/targets`. From the mockup's third view.

A capability grid: one column per target, and rows for status, credentials, probabilities, images, context window, questions per request, options or levels, concurrency, and input cost per 1 million tokens. The status row is colored ready, warning, or down, and a down target's cell gives the reason and what to do, as the health check returns it. The header shows when the targets were last checked and how many are ready. **Check all targets** runs the health checks.

API calls: `GET /api/targets`, `POST /api/targets/check`.

## Components

Shared components, each with its own tests:

| Component | Does |
|---|---|
| `TopBar`, `TabNav`, `HealthStrip` | The sticky top bar, the tabs, and the target health blocks |
| `HeatCell`, `HeatKey`, `heat()` | A ramp-colored cell with a value and a bar, the ramp legend, and the ramp function |
| `TargetHeader` | A target's name, runtime label, and status chip |
| `AnswerMatrix` | The answers grid for one request across targets: Compare and the case stepper use it |
| `ScoreCell` | The score value with its marker on a level axis |
| `SpreadCell` | Max minus min across ready targets, amber at 0.05 or more |
| `NotReadyCell` | The hatched cell for a target that can't run |
| `QuestionCard`, `OptionList` | A question's id, type, instructions, and options or levels, editable |
| `TargetPicker` | Target checkboxes, with not-ready targets turned off and their reason |
| `RunBar`, `ProgressBar` | A run's facts and its segmented progress |
| `MetricsGrid` | The per-target metric heat grid |
| `ConfusionMatrix` | Expected by answered counts |
| `ReliabilityTable` | Calibration bins and expected calibration error |
| `ChangesTable` | Changed answers between two runs |
| `QuestionSetDiff` | Two versions side by side |
| `SweepChart` | Share decided and error rate against a threshold |
| `ProbeGrid` | Cases by variants |
| `CapabilityGrid` | The Targets view grid |
| `LoadingState`, `EmptyState`, `ErrorState` | The shared states below |

## States

Every view and every data component handles four states.

| State | What shows |
|---|---|
| Loading | The grid's frame with its headers and gray placeholder cells, so the layout doesn't jump. A request that takes more than 10 seconds shows the elapsed time. |
| Empty | A label and the action that fills it: "No runs" with **Start run** from a suite, "No cases" with **Open in compare**, "No changed answers". |
| Error | The error code and message from the API, and **Retry**. If the API can't be reached at all, a bar under the top bar reads "Can't reach the jevtester server at 127.0.0.1:8640" with **Retry**. |
| Target not ready | The target's column or row stays, hatched, with the reason from its last health check. Its checkbox is turned off in pickers. In a run, its jobs count as skipped, with the reason. |

Some views have more:

- Compare: a request that's waiting shows a spinner in each target's header, and each column fills in when its result arrives if the API returns results one by one. A preflight rejection shows on the target's column, with its code and message, before anything is sent.
- Runs: running, finished, cancelled, and failed. A dropped event stream shows "Reconnecting" in the run bar.
- Save case dialog and policy editor: a validation error from the API shows next to its field.

## API client and errors

- `web/src/api/client.ts` has one typed function per endpoint, built on the generated types. Each returns the parsed body or throws an `ApiError` with the HTTP status, `code`, `message`, and optional `field`.
- `web/src/api/events.ts` wraps `EventSource` for run events, with typed event handlers and reconnection.
- No credential ever reaches the browser. The UI sends target names, and the server holds the tokens.

## Tests

- vitest: the heat ramp, spread, confidence display, the CLI command builder, the question card editor, and each shared component in each of its states.
- Playwright, against fixture mode: a quick test grows into a full request without losing input, a target that isn't ready stays in the grid with its reason, a run page follows SSE progress to the end, cancel, a changed-answers step-through, the save case dialog, and the Targets grid.

## Build order

1. Scaffold `web/`: Vite, React, TypeScript, Tailwind, the design tokens, fonts, the gates, fixture mode, and the app shell with tabs.
2. Generate the API types once `docs/openapi.json` is on `main`. Write the client.
3. Targets view and the health strip.
4. Compare: the answers matrix first, then the quick test, the full request, and the save case dialog.
5. Suites and starting a run.
6. Runs: the run bar with SSE, metrics, confusion matrix, calibration, changed answers, and the case stepper.
7. Question sets: versions, diff, and the editor.
8. Policies and the sweep chart.
9. Probes.

Each step is one pull request, reviewed by the backend session, and ends with the frontend gates passing.

## Open questions

- The plan asks the UI to edit question sets, but the starting endpoints have no way to save one. This plan assumes `PUT /api/question-sets/{name}`.
- Claude drafts are deferred with the assist features. The Suites cases grid shows a "Draft" tag now, and review and approval come with that work.
- A light theme isn't planned. The mockup is dark only.
