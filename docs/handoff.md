# jevtester handoff

Two Claude Code sessions build jevtester at the same time: one builds the backend, and one builds the frontend. They message each other while they work. [The plan](plan.md) is the specification for both. Read it first, then the section here for your role.

## State on 2026-10-24

- `main` contains the plan, these handoff notes, and four UI mockups. There's no code yet, and the repository has no remote.
- The user chose the heat matrix UI direction: [`mockups/3-matrix.html`](../mockups/3-matrix.html).
- Two hosted targets are verified with real calls:
  - `decision-1@foundry`: Microsoft-Decision-1 on Azure Foundry, through the TypeSafe SDK with `compression=False`.
  - `clef-flash@workers-ai`: Clef-flash on Workers AI, with a token from the Wrangler sign-in.
- The `decision-1` deployment runs at capacity 100 (100 requests and 100,000 tokens per minute).
- Ollama 0.40.11 is installed. The `clef-flash` pull was stopped before it finished.
- The MLX environment is ready at `~/models/clef-mlx/.venv`. The model downloads were stopped part of the way through: `clef-flash-4bit` has 3.7 GB, and `clef-flash-8bit` and `clef-8bit` haven't started.
- The Claude provider and the assist features are deferred.

The local downloads were stopped because the machine is on a phone hotspot. Don't restart them without asking the user. To resume them later:

```sh
ollama pull clef-flash
for r in clef-flash-4bit clef-flash-8bit clef-8bit; do
  uvx --from huggingface_hub hf download mlx-community/$r --local-dir ~/models/clef-mlx/$r
done
```

After a download finishes, delete any `__pycache__` directory in the model repository before you run `clef_mlx.py`. The plan explains why.

## Who does what

| | Backend session | Frontend session |
|---|---|---|
| Builds | The library, the CLI, and the HTTP API: steps 1 through 9 of the plan's [build order](plan.md#build-order) | The web UI, from the matrix mockup |
| Changes | `src/jevtester/`, `tests/`, `pyproject.toml`, `jevtester.toml`, `suites/`, `docs/api.md`, `docs/openapi.json`, `tests/fixtures/api/` | `web/` |
| Doesn't change | `web/` | Everything outside `web/`. Ask the backend session instead. |

`docs/plan.md` and this file belong to the user. Either session may propose a change to them in a message to the user. Neither session edits them without the user's approval.

## Git

Each session works on a separate branch, in a separate worktree next to the main checkout. Create the worktrees from `main`:

```sh
git -C ~/repos/jevtester worktree add ../jevtester-backend -b backend main
git -C ~/repos/jevtester worktree add ../jevtester-frontend -b frontend main
```

Work only in your worktree. The main checkout at `~/repos/jevtester` stays on `main`.

When a step passes its gate, merge your branch into `main` from the main checkout, then tell the other session the commit hash. To pick up the other session's work, merge `main` into your branch. If the user adds a GitHub remote, switch to pull requests and follow the user's pull request rules.

## The API contract

The backend session owns the contract. Write it before you implement it, so the frontend session can build against it from the start:

1. Write the API's pydantic request and response models and a FastAPI app whose routes return fixtures.
2. Export the OpenAPI document to `docs/openapi.json`, and write `docs/api.md`, which lists the endpoints and the event format.
3. Save one fixture for each response in `tests/fixtures/api/`. Use real responses where a target is available. The two verified responses in the plan are the first fixtures.
4. Merge into `main` and message the frontend session.

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

Build the UI from [`mockups/3-matrix.html`](../mockups/3-matrix.html) and the plan's [What the UI must show](plan.md#what-the-ui-must-show).

1. Before you build views, write `docs/ui-plan.md` in your worktree: the views, the components, each component's states (loading, empty, error, and a target that isn't ready), and the API calls each view makes. Send it to the user for review. Scaffolding and design tokens can go ahead while you wait.
2. Use the stack osr-editor uses (`~/repos/osr-suite/osr-editor/frontend`): React, TypeScript, Vite, Tailwind CSS, vitest, Playwright, prettier, and eslint. Generate API types from `docs/openapi.json` with `openapi-typescript`, and don't edit the generated file.
3. Take the colors, spacing, and type scale from the mockup's CSS variables.
4. Serve the Noto fonts from the app with the `@fontsource` packages, not from Google Fonts. The app runs locally, sometimes on a slow connection.
5. Build against the fixtures in `tests/fixtures/api/` until each endpoint is live. In development, Vite proxies `/api` to `http://127.0.0.1:8640`.
6. Build into `src/jevtester/static/`. That's the only place outside `web/` the frontend session writes to, and git ignores it.
7. Run the gates before every merge: `npx prettier --check .`, `npx eslint .`, `npx tsc -b`, `npx vitest run`, and `npx playwright test`, from `web/`.

UI text follows two rules from the user:

- Use sentence case for every label, button, card, tab, and panel.
- Write each string as a label or a fact the person acts on. Don't add sentences that explain the UI, like "Nothing you typed is lost." A legend or an axis label explains what a color means.

## Messages between the sessions

Use the `ListAgents` tool to find the other session, and `SendMessage` to write to it. Send a message when:

- The backend changes the contract or makes an endpoint live. Include the commit hash and the endpoints affected.
- The frontend needs a field or an endpoint the contract doesn't have. Say which view needs it and why.
- Either session finds a bug in the other's work. Include the request, the response, and what you expected.
- Either session merges into `main`.

Keep each message to what changed, where (a file or a commit), and what you need. Don't change the other session's files. Ask instead.

Questions about scope, cost, or anything the plan doesn't settle go to the user, not to the other session.
