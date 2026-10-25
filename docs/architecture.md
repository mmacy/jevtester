# Architecture

If you want to change jevtester, start here. If the terms are new to you, read [Concepts](concepts.md) first. [The plan](plan.md) is the specification, and [the handoff](handoff.md) describes how two agent sessions split the backend and frontend work.

## Overview

jevtester has three layers:

- A Python library in `src/jevtester/` that does the work: it reads suites, calls models, scores answers, and stores runs.
- Two thin front ends over that library: the CLI in `cli.py` and the HTTP API in `api.py`. Both call the operations in `service.py`, and both return the same models from `schemas.py`. So the CLI's JSON output and the API's responses are the same.
- A web UI in `web/`, which calls the HTTP API.

Every operation goes into `service.py` first, so the CLI, the API, the UI, and agents can all do the same things.

## Package layout

| Path | Job |
|---|---|
| `cli.py` | The `jevtester` command. It parses arguments, calls the service, and prints text or JSON. |
| `api.py` | The FastAPI app. Every route is under `/api` and calls the service. It also serves the built web UI outside `/api`. |
| `service.py` | The operations the CLI and the API share. It loads the config, builds the providers, and starts runs. |
| `schemas.py` | The pydantic models the API takes and returns. They're the API contract, and `docs/openapi.json` is generated from them. |
| `model.py` | The base class for every model. It rejects unknown fields, and its JSON schema marks every field as present in output. |
| `errors.py` | The service's errors. The API turns them into error responses, and the CLI turns them into exit code 2. |
| `credentials.py` | Token sources for Foundry (the `az` sign-in) and Workers AI (Wrangler or `CLOUDFLARE_API_TOKEN`). |
| `diff.py` | Compares two versions of a question set. |
| `spec/` | The input models: questions, question sets, the decision request, cases, suites, targets, capabilities, the config, and policies. |
| `providers/` | The `DecisionProvider` protocol and one provider for each kind of server. |
| `normalize/` | Maps any server's response to canonical answers, and computes confidence. |
| `preflight/` | Checks a request against a target's limits before it's sent, and estimates its tokens. |
| `runner/` | Sends one request (`jobs.py`), and runs a whole run's jobs with concurrency limits, caching, events, and cancellation (`run.py`). |
| `evaluate/` | Scores answers (`scoring.py`), computes metrics and run comparisons (`metrics.py`), makes probe variants (`probes.py`), checks wording and cases (`checks.py`), and writes the Markdown report (`report.py`). |
| `policy/` | Applies a policy to answers, measures decisions, and sweeps a threshold. |
| `store/` | Runs, results, the cache, and question set versions in SQLite (`runs.py`), and suites, question sets, and policies as YAML files (`files.py`). |
| `states/` | A placeholder for builders that turn game data into states. It has no code yet. |

The plan also describes an `assist/` package and a Claude provider. jevtester has neither. The config accepts `provider = "claude"`, and such a target reports `The claude provider isn't built yet`.

## The web UI

The web UI is in `web/`. It's built with React, TypeScript, Vite, Tailwind CSS, Zustand for state, and React Router. The design follows `mockups/3-matrix.html`: most views are grids, with targets as columns and cell color for probability.

| Path | Contains |
|---|---|
| `src/views/` | One view per tab: Compare, Suites, Runs, Question sets, Policies, Probes, and Targets. `src/nav.ts` lists them in tab order. |
| `src/components/` | Shared parts, like the answer matrix, heat cells, the run bar, and dialogs. |
| `src/api/` | The API client. `generated.ts` is generated from `docs/openapi.json`, `client.ts` wraps each route, and `events.ts` follows a run's server-sent events. |
| `src/lib/` | Logic without UI, like formatting, the metric tables, and building the CLI command for a request. |
| `src/store/` | Zustand stores for the targets and the compare view. |
| `fixture-server.ts` | A Vite plugin that answers `/api` from `tests/fixtures/api/`, so the UI runs without a backend. |

`npm run build` writes the UI to `src/jevtester/static/`, which git ignores. `jevtester serve` serves it. For any path outside `/api`, the server returns a built file if one exists, or else `index.html`, so a page in the UI, like `/runs/0002`, loads when you reload it. Without a build, it returns a short page with the commands that build the UI.

The UI never sees a credential. Its requests give target names, and the server keeps the tokens.

## How a run flows

A run starts from `jevtester run` or `POST /api/runs`. Both call `Service.start_run`.

1. **Expand.** The service loads the suite and its question set, and records the question set's version. It resolves the targets: the ones named, or else the suite's, or else the config's defaults. It makes one *job* for each case, target, and repeat. A probe run also makes a job for each probe variant.
2. **Save.** It saves the run's summary with status `queued`, a copy of the cases, and a copy of the policy. Metrics use these copies, so a later edit to the suite doesn't change an old run's scores.
3. **Start.** It starts the run as a background task and returns the run's id.
4. **Check.** The task runs every target's health check at once. It skips each target that's down, with the reason.
5. **Send.** For each job, the runner:
   - Computes a cache key from the target, its model and `truncate` setting, the request body, and the repeat number. Unless the run bypasses the cache, it uses a cached result when one exists.
   - Waits for a slot under the target's `concurrency` limit. Targets with the same `concurrency_group` share one limit. It also waits to stay under `requests_per_minute` and `tokens_per_minute`, when the target sets them.
   - Runs preflight. A request that would fail isn't sent, and gets a `preflight` error.
   - Calls the provider, with the run's timeout plus 5 seconds of grace.
   - Normalizes the response into canonical answers, and adds the warnings.
   - Caches the result if it succeeded, saves it, and publishes a `result` event.
6. **Finish.** The run ends with a `finished`, `cancelled`, or `error` event, and its final status is saved.

Events go to every subscriber. The CLI prints them to stderr. The API streams them as server-sent events from `GET /api/runs/{id}/events`. Each event contains the run's counts, so a client that reconnects needs no history.

A run lives in the process that started it, and the run store records that process as the run's owner. Each `RunStore` opened on a file holds an exclusive lock on `<database>.owners/<token>.lock`, and the operating system releases the lock when the process ends, even after a crash. Each time a `Service` is built, which happens on every CLI command and every server start, it marks a run recorded as `queued` or `running` as `failed` only when its owner's lock is free. A run that another live process is running stays as it is.

jevtester computes metrics when you ask for them, from the stored results. It doesn't store them. So a change to the metrics code applies to old runs too.

## Providers and runtimes

A *provider* connects jevtester to one kind of server. Each provider implements `DecisionProvider` in `providers/base.py`:

- `capabilities`: the target's capabilities.
- `decide(request, timeout=...)`: sends one request and returns a `RawResult`, with the exact request and response bodies, the latency, and an error if no answers came back.
- `health_check()`: returns a `Health`, whose `reason` is `None` when the target is ready.

A provider never raises for a failed request. It returns a `RawResult` with an `error`, so the runner records every failure the same way. `target_result` in `providers/base.py` then normalizes the raw result.

There are two providers:

| Provider | Module | Serves | How it calls the server |
|---|---|---|---|
| `systemone` | `providers/systemone.py` | Foundry, Ollama, and the MLX server | The TypeSafe SDK |
| `workers-ai` | `providers/workers_ai.py` | Workers AI | Direct HTTP with `httpx2` |

A target's `runtime` sets how its health check works:

| Runtime | Health check |
|---|---|
| `foundry` | Gets a token from the `az` sign-in. It doesn't contact the resource. |
| `ollama` | Checks that Ollama is running, is 0.35.1 or later, and has the model pulled. |
| `mlx` | Checks that the server is running and has the target's model loaded. The provider also checks this before each request, because the server answers with whatever model it loaded. |
| `workers-ai` | Gets a token, then searches the account's Workers AI catalog for the model. |
| None | Checks that something answers at the base URL. |

### The TypeSafe SDK

`providers/typesafe.py` is the only module that imports the TypeSafe SDK. The SDK is at version 0.x, so a breaking release should change only that file. The module:

- Turns off request compression, because Foundry rejects compressed request bodies.
- Uses the response body even when the SDK's strict parsing rejects it, and adds a `strict_parse_failed` warning. That way a server with a slightly different format still gives answers.
- Maps HTTP errors to jevtester's error codes, like `auth`, `rate_limited`, and `request_too_large`.

### Workers AI

Workers AI takes the System One request body unchanged. It wraps the response in a Cloudflare envelope, and the provider reads the `result` inside it. The provider gets a new token once after an HTTP 401. It retries a 429 or 5xx response after 0.5 seconds and again after 1 second, while the timeout allows.

Neither provider sends images yet. A request with images gets a `preflight` error.

### Normalizing answers

`normalize/` reads each response as plain JSON, not through the SDK's models. For each question, it produces a `NoulAnswer`, `ChoiceAnswer`, or `ScoreAnswer`. It recomputes confidence for nouls and choices, and records the server's value beside it. It warns about a missing answer, an option the question doesn't have, a missing probability, or an answer to a question that wasn't asked. It fails the result only when the response has no `answers` object.

## The store

`store/runs.py` keeps a SQLite database, by default at `.jevtester/runs.sqlite`. Git ignores it. Each row stores a pydantic model as JSON, so the schema changes with the models, without SQL migrations.

| Table | Contains |
|---|---|
| `runs` | Each run's summary: its settings, status, counts, and cost. |
| `results` | Each job's result, keyed by run, case, target, repeat, and probe variant. |
| `cache` | Successful results, keyed by the cache key. A failed request isn't cached. |
| `run_cases` | A copy of each run's cases. |
| `run_policies` | A copy of each run's policy. |
| `question_set_versions` | Each question set version jevtester has seen, and when it first saw it. |

Run ids are numbers with at least four digits, starting at `0001`.

`store/files.py` reads and writes the YAML files under `suites/`: suites at `suites/<name>.yaml`, question sets in `suites/question-sets/`, and policies in `suites/policies/`. A name uses only lowercase letters, digits, `-`, and `_`, so it's always a safe file name. Saving a question set rewrites its file. Adding a case to a suite appends the case's text and leaves the rest of the file, comments included, as it is. A suite argument in the CLI can also be a path to a suite file, and then its directory is the suites directory for that command. Saving a policy writes its text as you wrote it, with its comments.

## Design rules

`AGENTS.md` sets these rules for every change:

- **Contracts before code.** Write public signatures, pydantic models, and the OpenAPI document first. The implementation fills them in.
- **Tests before implementation.** Each build step ends with a command that shows it works.
- **No hosted calls in the test suite.** Use the fixtures in `tests/fixtures/`, and put live checks behind the `live` marker.
- **No compatibility code.** Refactor freely and update every call site. Don't keep aliases, shims, or deprecated code. Git history is the archive.
- **Fix findings in the code.** Don't add ignore lists, `noqa`, or `type: ignore`.
- **Never print, log, or commit a credential.** Read a credential in code and use it there. `jevtester.toml` contains placeholders, and real account details go in `jevtester.local.toml`.
- **Ask before a model download.** Downloads are many gigabytes.
- **Stop a server by its process id**, never by name. Someone else may be running one too.
- **UI text** uses sentence case. Each string is a label or a fact the person acts on, not an explanation of the UI.
- **`docs/plan.md` and `docs/handoff.md` belong to the user.** Propose changes to them instead of making them.

The code follows a few more rules:

- The CLI and the API stay thin. Logic goes in `service.py` or below it.
- Every API response field is always present. An unknown value is `null`, not a missing key.
- A policy is data, not code, so loading one can't run anything.

## Testing

### Gates

Run every gate before you open a pull request. CI runs the same gates on every pull request and every push to `main`, without secrets and without the live tests.

Backend, from the repository root:

```sh
uv run ruff format --check
uv run ruff check
uv run pyright
uv run pytest
```

Pyright runs in strict mode on `src/`.

Frontend, from `web/`:

```sh
npx prettier --check .
npx eslint .
npx tsc -b
npx vitest run
npx playwright test
```

The Playwright tests run against the UI in fixture mode on port 5174, so they need no backend. `npm run e2e:serve` builds the UI and tests it as `jevtester serve` serves it, against the real API on port 8645. It calls no model.

### Fixtures

| Path | Contains |
|---|---|
| `tests/fixtures/systemone/` | The plan's parley request, and real responses to it from Foundry and Workers AI. The normalizer tests use them. |
| `tests/fixtures/api/` | One saved response for each API route, for the UI's fixture mode and the contract tests. |
| `tests/fakes.py` | `FakeProvider`, which answers from a function instead of a server and records each request. |

Provider tests pass an `httpx2.MockTransport` to the provider in place of the network.

`tests/api_fixtures.py` builds every file in `tests/fixtures/api/` by running the real service with fake providers. Don't edit those files by hand. `tests/test_api_contract.py` fails when `docs/openapi.json` or a fixture is out of date. After a change to the API models, regenerate them:

```sh
uv run python -m jevtester.api openapi docs/openapi.json
uv run python tests/api_fixtures.py
cd web && npm run gen:api
```

The last command regenerates `web/src/api/generated.ts`.

### The live marker

Tests that call a real target have `@pytest.mark.live`. `pyproject.toml` adds `-m 'not live'` to every pytest run, so they're skipped unless you run `uv run pytest -m live`. They read `jevtester.local.toml`. [Run the live tests](how-to.md#run-the-live-tests) lists them.

## Add a provider

Add a provider when a new kind of server doesn't speak the System One API, or needs a different way to call it. A System One server that needs a different health check needs only a new runtime, in steps 1, 4, and 6.

1. In `spec/targets.py`, add the provider's name to `ProviderName`. For a new runtime, add it to `Runtime`.
2. If the server needs a credential, add a token source to `credentials.py` that implements `TokenSource`. It must never print or log the token.
3. In `providers/`, add a class that implements `DecisionProvider`:
   - `decide` builds the body with `request.system_one_body(target.model)`, sends it, and returns a `RawResult`. It returns an error instead of raising. It puts the System One response in `system_one`, so the normalizer can read it.
   - `health_check` returns a `Health` with the reason when the target isn't ready, and the credential's source when it is.
   - Take a `transport` argument, so tests can replace the network.
4. In `service.py`, build the provider in `build_providers`. For a new runtime of the `systemone` provider, add its check to `SystemOneProvider.health_check` instead.
5. Add the target to `jevtester.toml`, with its capabilities and placeholders for any account details.
6. Write tests with a mock transport and a recorded response in `tests/fixtures/`. Add a live test with `@pytest.mark.live`.
7. `ProviderName` and `Runtime` are part of the API models, so regenerate `docs/openapi.json`, the API fixtures, and `generated.ts`.
8. Document the target in [the how-to guides](how-to.md#set-up-a-target) and the configuration reference.

## Add a metric

1. In `schemas.py`, add a field to `QuestionMetrics` for a per-question metric, or to `TargetMetrics` for a per-target one. Its docstring says which question types it applies to.
2. In `evaluate/metrics.py`, compute it in `question_metrics` or `run_metrics`. Leave it `None` when it doesn't apply or there's nothing to score.
3. Test it in `tests/test_evaluate.py`, with values you can check by hand.
4. Add a column to the report in `evaluate/report.py`.
5. Regenerate `docs/openapi.json`, the API fixtures, and `generated.ts`.
6. Show it in the web UI. The metric columns for each question type are in `web/src/lib/run.ts`.
7. Explain it in [Concepts](concepts.md#metrics).
