# AGENTS.md

Guidance for agents working on jevtester, a local web app and CLI for testing decision models, the questions written for them, and the decisions built on their answers.

## Where the specification lives

- [`docs/plan.md`](docs/plan.md) is the specification: what the app does, the targets, the architecture, the CLI, the first RPG suites, what the UI must show, and the build order.
- [`docs/handoff.md`](docs/handoff.md) splits the work between the backend session (`JEVTESTER-BACKEND`) and the frontend session (`JEVTESTER-FRONTEND`). It gives each session's files, the API contract process, and when the sessions message each other.
- [`mockups/3-matrix.html`](mockups/3-matrix.html) is the UI design to build from.

`docs/plan.md` and `docs/handoff.md` belong to the user. Propose changes to them. Don't make changes without the user's approval.

## Working method

- Write contracts before code. Public signatures, pydantic models, and the API's OpenAPI document come first, and the implementation fills them in.
- Write a step's tests before its implementation. Every step in the plan's build order ends with a command that shows the step works.
- Don't call hosted targets in the test suite. Use the fixtures in `tests/fixtures/`, and put live checks behind a pytest marker (`-m live`).
- Refactor freely and update every call site. Don't keep aliases, shims, or deprecated code. Git history is the archive.

## Gates

Run every gate before you open a pull request.

Backend, from the repository root:

```sh
uv run ruff format --check
uv run ruff check
uv run pyright
uv run pytest
```

Frontend, from `web/`:

```sh
npx prettier --check .
npx eslint .
npx tsc -b
npx vitest run
npx playwright test
```

Fix a finding in the code. Don't add ignore lists, `noqa`, or `type: ignore`.

## Credentials

- Foundry uses the `az` sign-in through `azure-identity`. The `goldbox-resource` resource has API keys disabled.
- Workers AI uses the Wrangler sign-in: `npx wrangler auth token --json` returns a short-lived token in its `token` field.
- Never print, log, or commit a token or key. Read a credential in code and use it there.
- `.env` files are gitignored. jevtester doesn't need one yet.

## Local models

- Ollama runs at `http://localhost:11434`. Its `clef-flash` pull isn't finished.
- The MLX builds and their environment are in `~/models/clef-mlx`. The downloads aren't finished.
- Don't start or resume a model download without asking the user. The machine is sometimes on a phone hotspot.
- Delete `__pycache__` from a downloaded MLX model repository before you run `clef_mlx.py`, so Python runs the reviewed source.
- Stop a server you started by its process id, never by name. The user may be running a server too.

## UI text

- Use sentence case for every label, button, card, tab, and panel.
- Write each string as a label or a fact the person acts on. Don't add sentences that explain the UI, like "Nothing you typed is lost." A legend or an axis label explains what a color means.

## Repository

- `origin` is <https://github.com/mmacy/jevtester> (private). `main` takes pull requests.
- Cut every branch from `origin/main`. When a branch builds on another unmerged branch, set its pull request's base to that branch.
- Before you open a pull request, run `git log --oneline origin/main..HEAD` and confirm it lists only the branch's commits.
- Work in a worktree beside the main checkout (`git worktree add ../jevtester-<branch> -b <branch> origin/main`), not under `.claude/worktrees/`. The main checkout at `~/repos/jevtester` stays on `main`.
- Every pull request gets a review from the other session, posted as a pull request comment that names the reviewing session. Start each pull request description, review, and reply with the session's name, since both sessions use the user's GitHub account. [Pull request reviews](docs/handoff.md#pull-request-reviews) in the handoff gives the steps.
- You may merge your own pull request once the latest review says `Ready to merge` and the gates pass.
