# jevtester handoff

Two Claude Code sessions can build jevtester at the same time: one builds the backend, and one builds the frontend. They message each other while they work. [The plan](plan.md) is the specification for both. Read it first, then the section here for your role.

## Before you start

- Set your own Foundry resource and Cloudflare account in `jevtester.local.toml`, which jevtester merges over `jevtester.toml`. Git ignores it. See the [README](https://github.com/mmacy/jevtester/blob/main/README.md).
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

The backend session owns the contract: the API's pydantic models in `src/jevtester/schemas.py`, `docs/openapi.json`, the [HTTP API reference](reference/http-api.md), and the fixtures in `tests/fixtures/api/`. The frontend session builds against it.

Change the contract in this order:

1. Change the models.
2. Regenerate `docs/openapi.json` and the fixtures, and update the HTTP API reference. [Architecture](architecture.md) gives the commands.
3. Send the frontend session a message that says what changed.

## Backend session

- Serve the API on `127.0.0.1:8640`. `jevtester serve` also serves the built frontend from `src/jevtester/static/`, which git ignores.
- Allow requests from the Vite dev server origin (`http://127.0.0.1:5173`) while you develop.
- Run the gates before every merge: `uv run ruff format --check`, `uv run ruff check`, `uv run pyright`, and `uv run pytest`.
- Don't call hosted targets in the test suite. Use the fixtures. Put live checks behind a marker, like `pytest -m live`.

## Frontend session

Build the UI from [`mockups/3-matrix.html`](https://github.com/mmacy/jevtester/blob/main/mockups/3-matrix.html) and the plan's [What the UI must show](plan.md#what-the-ui-must-show).

1. Follow [the UI plan](ui-plan.md): the views, the components, each component's states (loading, empty, error, and a target that isn't ready), and the API calls each view makes. Propose changes to it to the user.
2. Use the stack [osr-editor](https://github.com/mmacy/osr-editor)'s frontend uses: React, TypeScript, Vite, Tailwind CSS, vitest, Playwright, prettier, and eslint. Generate API types from `docs/openapi.json` with `openapi-typescript`, and don't edit the generated file.
3. Take the colors, spacing, and type scale from the mockup's CSS variables.
4. Serve the Noto fonts from the app with the `@fontsource` packages, not from Google Fonts. The app runs locally, sometimes on a slow connection.
5. Build against the fixtures in `tests/fixtures/api/` in fixture mode. In development, Vite proxies `/api` to `http://127.0.0.1:8640`.
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

## Messages between the sessions

The sessions are named `JEVTESTER-BACKEND` and `JEVTESTER-FRONTEND`. Use the `ListAgents` tool to find the other session by that name, and `SendMessage` to write to it. Send a message when:

- The backend changes the contract. Include the commit hash and the endpoints affected.
- The frontend needs a field or an endpoint the contract doesn't have. Say which view needs it and why.
- Either session finds a bug in the other's work. Include the request, the response, and what you expected.
- Either session merges a pull request.

Keep each message to what changed, where (a file or a commit), and what you need. Don't change the other session's files. Ask instead.

Questions about scope, cost, or anything the plan doesn't settle go to the user, not to the other session.
