# jevtester handoff

Two Claude Code sessions can build jevtester at the same time: one builds the backend, and one builds the frontend. They message each other while they work. [The plan](plan.md) is the specification for both. Read it first, then the section here for your role.

## Before you start

- Copy `jevtester.toml` to `jevtester.local.toml` and set your own Foundry resource and Cloudflare account there. Git ignores the copy. See the [README](https://github.com/mmacy/jevtester/blob/main/README.md).
- The Claude provider and the assist features are deferred.
- Don't start a local model download (Ollama or MLX) without asking the user. After an MLX download finishes, delete any `__pycache__` directory in the model repository before you run `clef_mlx.py`. The plan explains why.

## Who does what

| | Backend session | Frontend session |
|---|---|---|
| Builds | The library, the CLI, and the HTTP API: steps 1 through 9 of the plan's [build order](plan.md#build-order) | The web UI, from the matrix mockup |
| Changes | `src/jevtester/`, `tests/`, `pyproject.toml`, `jevtester.toml`, `suites/`, `docs/reference/http-api.md`, `docs/openapi.json`, `tests/fixtures/api/` | `web/` |
| Doesn't change | `web/` | Everything outside `web/`. Ask the backend session instead. |

`docs/plan.md` and this file belong to the user. Either session may propose a change to them in a message to the user. Neither session edits them without the user's approval.

## Git

The repository is on GitHub at <https://github.com/mmacy/jevtester>, and `main` takes pull requests. [AGENTS.md](https://github.com/mmacy/jevtester/blob/main/AGENTS.md) has the pull request rules.

Each session works on a separate branch, in a separate worktree next to the main checkout. Cut each branch from `origin/main`:

```sh
git fetch origin
git worktree add ../jevtester-backend -b backend/<step> origin/main
git worktree add ../jevtester-frontend -b frontend/<step> origin/main
```

Run these from the main checkout. Work only in your worktree. The main checkout stays on `main`.

When a step passes its gates, open a pull request and ask the other session to review it. Merge it after the review, as [Pull request reviews](#pull-request-reviews) describes. To pick up the other session's work, fetch and merge `origin/main` into your branch.

## Pull request reviews

Every pull request gets a review from the other session before it merges. Both sessions use the user's GitHub account, so every pull request, review, and reply has to say which session wrote it. Otherwise the user's name on a comment looks like the user's review.

1. **Open the pull request.** Start its description with `Opened by JEVTESTER-BACKEND` or `Opened by JEVTESTER-FRONTEND`. Then send the other session a message with the pull request number and what to look at.
2. **Review it.** Post the review as a pull request comment with `gh pr comment <number> --body-file <file>`. Don't use `gh pr review`: GitHub doesn't let an account approve or request changes on its own pull request. Start the comment with `Review from JEVTESTER-FRONTEND (Claude Code session)` or `Review from JEVTESTER-BACKEND (Claude Code session)`. List each finding with its file and line, and mark each one as blocking or not. End with a verdict: `Ready to merge`, or `Changes needed`.
3. **Answer it.** The author fixes the blocking findings, pushes, and replies in a comment that starts with `Reply from JEVTESTER-BACKEND` or `Reply from JEVTESTER-FRONTEND`, saying what changed for each finding. The reviewer checks the new commits and posts a new verdict.
4. **Merge it.** The author merges once the latest review says `Ready to merge` and the gates pass, then messages the other session the pull request number.

What each session checks:

- **A backend pull request**, reviewed by the frontend session: the API models, `docs/openapi.json`, `docs/reference/http-api.md`, and the fixtures agree with each other, and the UI can get what it needs from them. Also check the code for bugs.
- **A frontend pull request**, reviewed by the backend session: the UI calls the API the way the contract says, handles errors and targets that aren't ready, and doesn't depend on a field the contract doesn't have. Also check the code for bugs.

Don't write `@` followed by a GitHub username in a pull request or a comment, since GitHub notifies that account. A pull request that changes `docs/plan.md` or `docs/handoff.md` also needs the user's approval before it merges.


## The API contract

The backend session owns the contract. Write it before you implement it, so the frontend session can build against it from the start:

1. Write the API's pydantic request and response models and a FastAPI app whose routes return fixtures.
2. Export the OpenAPI document to `docs/openapi.json`, and write the [HTTP API reference](reference/http-api.md) (`docs/reference/http-api.md`), which lists the endpoints and the event format.
3. Save one fixture for each response in `tests/fixtures/api/`. Use real responses where a target is available. The two verified responses in the plan are the first fixtures.
4. Open the pull request, and merge it after the frontend session's review.

After that, change the contract in the same order: models, `docs/openapi.json`, fixtures, then a message that says what changed.

### Starting endpoints

These follow the CLI commands in the plan. The backend session may change them, and announces each change.

| Method and path | Does |
|---|---|
| `GET /api/targets` | Lists targets, their capabilities, and their last health check. |
| `POST /api/targets/check` | Runs every health check and returns the results. |
| `POST /api/decide` | Sends one request to the chosen targets and returns one result per target. |
| `GET /api/suites`, `GET /api/suites/{name}` | Lists suites, or returns one suite with its cases. |
| `POST /api/suites/{name}/cases` | Adds a case, including one made from a `decide` result. |
| `GET /api/question-sets/{name}/versions` | Lists a question set's versions by hash. |
| `GET /api/question-sets/{name}/diff?from=&to=` | Compares two versions. |
| `POST /api/runs` | Starts a run of a suite on chosen targets and returns its id. |
| `GET /api/runs`, `GET /api/runs/{id}` | Lists runs, or returns one run's summary. |
| `GET /api/runs/{id}/events` | Streams run progress as server-sent events (SSE). |
| `POST /api/runs/{id}/cancel` | Cancels a run. |
| `GET /api/runs/{id}/metrics` | Returns metrics for each target. |
| `GET /api/runs/{id}/confusion?question=&target=` | Returns a confusion matrix. |
| `GET /api/runs/{id}/changes?baseline=` | Returns the cases whose answers changed from a baseline run. |
| `POST /api/probes` | Runs probes on a suite. |
| `GET /api/policies/{name}`, `PUT /api/policies/{name}` | Reads or saves a policy. |
| `POST /api/policies/{name}/sweep` | Sweeps a threshold and returns the trade-off points. |

### Result format

`POST /api/decide` and the run results use one result object per target. This is a starting point for the backend session's models:

```json
{
  "target": "decision-1@foundry",
  "ok": true,
  "latency_ms": 1550,
  "usage": {"input_tokens": 185, "output_tokens": 3},
  "cost_usd": 0.0000074,
  "warnings": [],
  "error": null,
  "answers": {
    "intent": {
      "type": "choice",
      "choice": "parley",
      "probabilities": {"parley": 0.9996, "evade": 0.0002, "fight": 0.0001, "wait": 0.0001},
      "confidence": 0.9995,
      "server_confidence": 0.9995
    },
    "bribe": {"type": "noul", "probability": 0.9988, "confidence": 0.9976},
    "reaction": {
      "type": "score",
      "score": 2.21,
      "probabilities": [0.033, 0.191, 0.458, 0.169, 0.149],
      "legend": ["Attack at once", "Hostile, may attack", "Uncertain, hold and posture", "Indifferent, may let them pass", "Friendly, accept the offer"],
      "confidence": null,
      "server_confidence": 0.323
    }
  },
  "raw": {}
}
```

- `confidence` is the value jevtester computes. It's `null` where the plan says to use the server's value.
- `warnings` contains objects with a `code` and a `message`, like `{"code": "truncation_on", "message": "Cuts state at 16,384 tokens"}`.
- A target that can't run returns `"ok": false`, an `error` with a `code` and a `message`, and no `answers`.
- `raw` is the server's response body, unchanged.

## Backend session

Follow the plan's build order, with one change: write the API contract (above) right after step 2, before steps 3 through 8. Then fill in the API routes as each step makes their data real.

- Serve the API on `127.0.0.1:8640`. `jevtester serve` also serves the built frontend from `src/jevtester/static/`, which git ignores.
- Allow requests from the Vite dev server origin (`http://127.0.0.1:5173`) while you develop.
- Run the gates before every merge: `uv run ruff format --check`, `uv run ruff check`, `uv run pyright`, and `uv run pytest`.
- Don't call hosted targets in the test suite. Use the fixtures. Put live checks behind a marker, like `pytest -m live`.

## Frontend session

Build the UI from [`mockups/3-matrix.html`](https://github.com/mmacy/jevtester/blob/main/mockups/3-matrix.html) and the plan's [What the UI must show](plan.md#what-the-ui-must-show).

1. Before you build views, write `docs/ui-plan.md` in your worktree: the views, the components, each component's states (loading, empty, error, and a target that isn't ready), and the API calls each view makes. Send it to the user for review. Scaffolding and design tokens can go ahead while you wait.
2. Use the stack [osr-editor](https://github.com/mmacy/osr-editor)'s frontend uses: React, TypeScript, Vite, Tailwind CSS, vitest, Playwright, prettier, and eslint. Generate API types from `docs/openapi.json` with `openapi-typescript`, and don't edit the generated file.
3. Take the colors, spacing, and type scale from the mockup's CSS variables.
4. Serve the Noto fonts from the app with the `@fontsource` packages, not from Google Fonts. The app runs locally, sometimes on a slow connection.
5. Build against the fixtures in `tests/fixtures/api/` until each endpoint is live. In development, Vite proxies `/api` to `http://127.0.0.1:8640`.
6. Build into `src/jevtester/static/`. That's the only place outside `web/` the frontend session writes to, and git ignores it.
7. Run the gates before every merge: `npx prettier --check .`, `npx eslint .`, `npx tsc -b`, `npx vitest run`, and `npx playwright test`, from `web/`.

UI text follows two rules from the user:

- Use sentence case for every label, button, card, tab, and panel.
- Write each string as a label or a fact the person acts on. Don't add sentences that explain the UI, like "Nothing you typed is lost." A legend or an axis label explains what a color means.

## Docs screenshots

The screenshots in `docs/images/` come from `web/screenshots/capture.spec.ts`. It runs the UI in fixture mode with the API fixtures, as the Playwright suite does, so it needs no backend, no target, and no network. Its CLI shots also need uv. To make them again after a UI or fixture change, run this from `web/`:

```sh
npm run screenshots
```

Then check the images and update [`docs/images/README.md`](images/README.md) if a screen changed what it shows.

## Known issues

These are confirmed in the code and not fixed yet:

- A `systemone` target without `base_url` makes every command, and `jevtester serve`, stop with a Python traceback. `SystemOneProvider` raises `ValueError` while the service builds its providers, and nothing catches it.
- A config file that isn't valid TOML stops the command with a `tomllib.TOMLDecodeError` traceback and exit code 1, not a message and exit code 2. The CLI catches only `OSError` and `ValidationError` when it loads the config.
- Every CLI command and every server start marks each run recorded as `queued` or `running` as `failed`, even a run that another jevtester process is still running.
- The CLI's suite argument drops its directory. `other/x.yaml` loads suite `x` from the config's suites directory.
- The `cancelled` result error code is in the contract, but nothing returns it.
- The Foundry health check only gets an `az` token. It never contacts `base_url`, so the target shows `ready` even with the placeholder `example-resource` URL.
- `jevtester case add` and `POST /api/suites/{name}/cases` rewrite the suite file, so they drop its YAML comments.
- `jevtester.local.toml` replaces `jevtester.toml` instead of merging with it. A target added to `jevtester.toml` is missing until you copy it to your local file.

## Messages between the sessions

The sessions are named `JEVTESTER-BACKEND` and `JEVTESTER-FRONTEND`. Use the `ListAgents` tool to find the other session by that name, and `SendMessage` to write to it. The user starts the backend session first, so the frontend session may find the contract already on `origin/main`. Send a message when:

- The backend changes the contract or makes an endpoint live. Include the commit hash and the endpoints affected.
- The frontend needs a field or an endpoint the contract doesn't have. Say which view needs it and why.
- Either session finds a bug in the other's work. Include the request, the response, and what you expected.
- Either session merges a pull request.

Keep each message to what changed, where (a file or a commit), and what you need. Don't change the other session's files. Ask instead.

Questions about scope, cost, or anything the plan doesn't settle go to the user, not to the other session.
