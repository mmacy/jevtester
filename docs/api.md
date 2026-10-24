# jevtester API

The jevtester API serves the web UI and gives scripts the same operations as the CLI. It runs at `http://127.0.0.1:8640`, and every route is under `/api`. Start it with `uv run jevtester serve`.

[`openapi.json`](openapi.json) is the full contract, generated from the pydantic models in [`src/jevtester/schemas.py`](../src/jevtester/schemas.py). This page covers what the schema can't say: the conventions, the rules behind some fields, and the event stream.

## Status of the routes

Every route returns a fixture from [`tests/fixtures/api/`](../tests/fixtures/api/) until the build step that makes its data real. The request models are already enforced, so an invalid body gets a real 422. Each step that makes a route live is announced with its commit.

| Routes | Live in |
|---|---|
| `decide`, `targets` | Live for every target except Claude |
| `suites`, `question-sets`, `runs`, run events, `cancel` | Live. Wording checks (`checks`) are empty until step 6. |
| `metrics`, `confusion`, `calibration`, `changes`, `compare`, `cases`, `report`, suite `check` | Live |
| `policies`, `sweep` | Live |
| `probes` | Live |

## Conventions

- Every response field is always present. An unknown value is `null`, never a missing key.
- Times are ISO 8601 in UTC, like `2026-10-24T14:02:00Z`.
- A version is the full SHA-256 hash of the content. Show the first 12 characters.
- Lists keep a meaningful order: targets in the order requested, questions and options in the question set's order, and runs newest first.
- The browser never sees a credential. Requests name targets, and the server holds the tokens.
- While the UI is in development, the API allows requests from the Vite dev server at `http://127.0.0.1:5173`.
- Outside `/api`, `jevtester serve` answers with the built UI: a built file if one exists, a 404 for a missing file under `/assets/`, and `index.html` for any other path, so the UI's own routes load on reload.

## Errors

Every 4xx and 5xx response has this body:

```json
{
  "error": {
    "code": "invalid_request",
    "message": "List should have at least 2 items after validation, not 1",
    "field": "questions.intent.choice.criteria",
    "details": [
      {"field": "questions.intent.choice.criteria", "message": "List should have at least 2 items after validation, not 1"}
    ]
  }
}
```

| `code` | Status | Means |
|---|---|---|
| `invalid_request` | 422 | The body, query, or a YAML document is invalid. `details` lists every error, and `field` is the first one's path. |
| `not_found` | 404 | No such route, suite, question set, version, run, case, or policy. |
| `conflict` | 409 | The change clashes with what exists, like a case id the suite already has. |
| `not_ready` | 409 | The operation needs a target that isn't ready. |
| `internal` | 500 | A bug. The message says what failed. |

A field path joins the location with dots. For a question, the path includes the question type, as in `questions.intent.choice.criteria`.

A target that fails during `decide` or a run isn't an HTTP error. Its result has `ok: false` and an `error`, and the other targets' results still arrive.

## Endpoints

| Method and path | Body | Returns |
|---|---|---|
| `GET /api/targets` | | `TargetList` |
| `POST /api/targets/check` | | `TargetList`, after running every health check |
| `POST /api/decide` | `DecideBody` | `DecideResponse` |
| `GET /api/suites` | | `SuiteList` |
| `GET /api/suites/{name}` | | `SuiteDetail` |
| `GET /api/suites/{name}/check` | | `SuiteCheck` |
| `POST /api/suites/{name}/cases` | `Case` | 201, `CaseCreated` |
| `GET /api/question-sets` | | `QuestionSetList` |
| `GET /api/question-sets/{name}` | | `QuestionSetDetail` |
| `PUT /api/question-sets/{name}` | `QuestionSetBody` | `QuestionSetDetail` |
| `GET /api/question-sets/{name}/versions` | | `QuestionSetVersions` |
| `GET /api/question-sets/{name}/versions/{version}` | | `QuestionSet` |
| `GET /api/question-sets/{name}/diff?from=&to=` | | `QuestionSetDiff` |
| `POST /api/runs` | `RunCreate` | 202, `RunCreated` |
| `GET /api/runs` | | `RunList` |
| `GET /api/runs/{id}` | | `RunSummary` |
| `GET /api/runs/{id}/events` | | Server-sent events |
| `POST /api/runs/{id}/cancel` | | `RunSummary` |
| `GET /api/runs/{id}/metrics` | | `RunMetrics` |
| `GET /api/runs/{id}/confusion?question=&target=` | | `ConfusionMatrix` |
| `GET /api/runs/{id}/calibration?question=&target=&bins=` | | `Calibration` |
| `GET /api/runs/{id}/changes?baseline=` | | `RunChanges` |
| `GET /api/runs/{id}/compare?baseline=&max_drop=` | | `RunComparison` |
| `GET /api/runs/{id}/cases/{case_id}` | | `RunCase` |
| `GET /api/runs/{id}/report` | | `RunReport` |
| `GET /api/runs/{id}/probes` | | `ProbeReport` |
| `POST /api/probes` | `ProbeCreate` | 202, `RunCreated` |
| `GET /api/policies` | | `PolicyList` |
| `GET /api/policies/{name}` | | `PolicyDetail` |
| `PUT /api/policies/{name}` | `PolicyBody` | `PolicyDetail` |
| `POST /api/policies/{name}/sweep` | `SweepBody` | `SweepResult` |

Each CLI command has a route that does the same thing, and its `--format json` output is that route's response:

| Command | Route |
|---|---|
| `jevtester decide` | `POST /api/decide` |
| `jevtester targets list` | `GET /api/targets` |
| `jevtester targets check` | `POST /api/targets/check` |
| `jevtester run <suite>` | `POST /api/runs`, then `GET /api/runs/{id}/events` |
| `jevtester compare <run> <baseline>` | `GET /api/runs/{id}/compare` |
| `jevtester report <run>` | `GET /api/runs/{id}/report` |
| `jevtester probe <suite>` | `POST /api/probes`, then `GET /api/runs/{id}/probes` |
| `jevtester case add <suite>` | `POST /api/suites/{name}/cases` |
| `jevtester suite check <suite>` | `GET /api/suites/{name}/check` |
| `jevtester policy sweep <policy>` | `POST /api/policies/{name}/sweep` |

`jevtester case add --from-decide decide.json --expect-from <target>` promotes a `jevtester decide --format json` result to a case, with that target's answers as the expected ones.

## Targets

A target's `status` follows from its last health check:

| `status` | When |
|---|---|
| `unchecked` | No health check has run since the server started. The server doesn't run one until asked. |
| `down` | The last check gave a `reason`, like `clef-flash isn't pulled`. `detail` says what to do. |
| `warning` | The target is ready, and `warnings` isn't empty. |
| `ready` | The target is ready, with no warnings. |

Each runtime has its own health check:

| Runtime | Ready when |
|---|---|
| Foundry | A token can be read from the `az` sign-in. `credential` says when it refreshes. |
| Ollama | Ollama answers, is 0.35.1 or later, and has the model pulled. `detail` gives the version. |
| MLX | The MLX server answers and has the target's model loaded. The server serves one model, so at most one MLX target is ready at a time. |
| Workers AI | A token can be read from `CLOUDFLARE_API_TOKEN` or the Wrangler sign-in, and the account's Workers AI catalog lists the model. |

The MLX server answers with whatever model it has loaded, whatever the request names. So a `decide` on an MLX target checks the loaded model first, and returns `not_ready` if it's another model.

A target's `warnings` come from its config, not from the check:

- `state_may_truncate` when `capabilities.truncates_state` is true, as on Workers AI.
- `truncation_on` when the target's config sets `truncate = true`, so the MLX server cuts the input at its context window without an error. The MLX targets in `jevtester.toml` set it to `false`.

`default_targets` lists the targets a request goes to when it names none, in the config's order.

`local` is true for targets on this machine (Ollama and MLX), which cost nothing. `capabilities` has every field for every target, and `null` means the limit is unknown, so preflight doesn't check it.

## Decide

`POST /api/decide` sends one request to each target in `targets`, or to the config's default targets when `targets` is empty. The targets run at the same time, and the response arrives when the last one finishes. To fill a grid as each target answers, send one `decide` per target.

The response echoes the request, so a client can label every row from the response alone. `question_set_version` is the hash a question set with these questions would have, which ties a quick test to a saved question set version.

An unknown target name, or a name given twice, is a 422 with the field `targets.<index>`. A target that isn't ready, or a request that fails its preflight check, returns that target's result with `ok: false` and the error code `not_ready` or `preflight`, before anything is sent.

## Results

Each target's result is a `TargetResult`:

```json
{
  "target": "decision-1@foundry",
  "ok": true,
  "latency_ms": 1550.0,
  "usage": {"input_tokens": 185, "output_tokens": 3},
  "cost_usd": null,
  "warnings": [],
  "error": null,
  "answers": {
    "intent": {"type": "choice", "choice": "parley", "probabilities": {"parley": 0.9996, "evade": 0.0002, "fight": 0.0001, "wait": 0.0001}, "unknown_probabilities": {}, "confidence": 0.9995, "server_confidence": 0.9995},
    "bribe": {"type": "noul", "probability": 0.9988, "confidence": 0.9977, "server_confidence": null},
    "reaction": {"type": "score", "score": 2.21, "level": 2, "probabilities": [0.033, 0.191, 0.458, 0.169, 0.149], "legend": ["Attack at once", "Hostile, may attack", "Uncertain, hold and posture", "Indifferent, may let them pass", "Friendly, accept the offer"], "confidence": null, "server_confidence": 0.323}
  },
  "request_body": {"model": "decision-1", "state": "...", "questions": {}},
  "raw": {}
}
```

- `answers` follows the request's question order. A choice's `probabilities` follow its option order, and a score's `probabilities` and `legend` are lists, lowest level first.
- `confidence` is computed by jevtester: `(p_max - 1/n) / (1 - 1/n)` for a choice and `|2p - 1|` for a noul. It's `null` for a score, where the server's value in `server_confidence` is the one to show.
- A score's `level` is its most probable level, and the lower level wins a tie. Evaluation compares `level` with the expected level, so outline `level` as the score's answer. Mean absolute error uses `score`.
- A noul's answer is yes when `probability` is 0.5 or more.
- A probability the server didn't send is left out of a choice's `probabilities`, and is `null` in a score's `probabilities`. Either way the result has a `missing_probability` warning.
- `unknown_probabilities` holds probabilities for options the question doesn't have, with an `unknown_option` warning.
- `cost_usd` is `null` when the target's price is unknown, as for Foundry now.
- `request_body` is the exact body sent, or `null` when nothing was sent. `raw` is the server's response body, unchanged. For Workers AI, `raw` is the whole Cloudflare envelope.

Warning codes: `missing_answer`, `invalid_answer`, `unknown_option`, `missing_probability`, `unexpected_answer`, `strict_parse_failed`, `truncation_on`, and `state_may_truncate`. A warning about one question names it in `question`.

Error codes: `not_ready`, `preflight`, `auth`, `rate_limited`, `bad_request`, `request_too_large`, `server_error`, `timeout`, `connection`, `invalid_response`, and `cancelled`. `status` is the HTTP status when the server sent one.

## Suites and question sets

Suites are YAML files in `suites/`, like `suites/parley.yaml`, and question sets are in `suites/question-sets/`. A name uses lowercase letters, digits, `-`, and `_`, and anything else is a 422. `POST /api/suites/{name}/cases` adds the case to the end of the suite's file, and `PUT /api/question-sets/{name}` replaces the question set's file. Either change shows up in `git diff`.

A question set version is the hash of its questions in order. jevtester records each version the first time it sees one: when a suite or question set is read, when one is saved, or when a run uses one. `first_seen` is that time. A version can be named by its first 8 or more characters, wherever a route takes a version.

## Runs

`POST /api/runs` returns 202 and the run's id as soon as the run is queued. Follow it with the event stream, or poll `GET /api/runs/{id}`.

`RunCounts` counts jobs, where a job is one case on one target for one repeat (and one variant, in a probe run). `done` is `sent + cached + failed + skipped`, so `done / jobs` is the progress. `targets` breaks the counts down by target, with `skip_reason` for a target whose jobs were skipped.

A run's `status` moves from `queued` to `running`, then ends as `finished`, `cancelled`, or `failed`. Cancelling a run that has ended returns it unchanged.

Before it sends anything, a run checks the health of each of its targets. A target that's down has all its jobs skipped, with the reason. Each job is cached by its target, its request, and its repeat, so a rerun of an unchanged suite costs nothing. `no_cache: true` sends every request again. A run that was running when the server stopped is marked `failed` when the server starts again.

### Run events

`GET /api/runs/{id}/events` streams server-sent events. Each event's `event` field names its type, `id` numbers it from 0, and `data` is one line of JSON whose `type` matches `event`:

```text
event: progress
id: 0
data: {"type":"progress","run_id":"0002","status":"running","counts":{...}}

event: result
id: 2
data: {"type":"result","run_id":"0002","case_id":"goblin-bribe","target":"decision-1@foundry","repeat":0,"variant":null,"cached":false,"result":{...},"counts":{...}}
```

| `event` | Sent when | Carries |
|---|---|---|
| `progress` | First on every connection, and when the status changes | `status`, `counts` |
| `result` | A job finishes | The case, target, repeat, variant, whether it came from the cache, the `TargetResult`, and `counts` |
| `target_skipped` | A target's jobs are skipped | `target`, `reason`, `counts` |
| `finished` | The run finishes | `counts`, `summary` |
| `cancelled` | The run is cancelled | `counts`, `summary` |
| `error` | The run fails | `error`, `counts`, `summary` |

Every event carries `counts`, so a client can draw progress from any one event. A `result` event's `TargetResult` has `request_body` and `raw` set to `null`, to keep the stream small. `GET /api/runs/{id}/cases/{case_id}` returns them.

The stream ends after `finished`, `cancelled`, or `error`. A client that reconnects gets a fresh `progress` event and then the events that follow, so it needs no history. A run that has already ended sends `progress` and its final event. A browser's `EventSource` reconnects when the server closes the stream, so close it on the final event.

## Evaluation

The metrics, the confusion matrix, the calibration table, the changes, and a run's cases all score each answer the same way:

- A noul's answer is yes when the probability of yes is 0.5 or more.
- A choice's answer is its `choice`.
- A score's answer is its `level`. `accuracy` counts exact levels. `within_tolerance` allows each case's `tolerance` in levels, and so do the `correct` marks, the changes, and the regression check. `mae` uses `score`.
- An answer matches when it equals the expected answer or one of the `acceptable` ones. A missing answer is wrong. A question the case expects nothing for isn't scored.

A run keeps a copy of the cases it ran, so editing the suite afterward doesn't change how the run is scored. Only original cases count, not probe variants.

`abstention_rate` counts how often a choice question's abstention option was chosen. jevtester finds that option by its name: `abstain`, `cannot_tell`, `cant_tell`, `unclear`, `unknown`, or `unsure`. Without one, the rate is `null`, and the wording checks report `no_abstention`.

Calibration uses targets that return probabilities. For a noul, the prediction is the probability of yes. For a choice, it's the probability of the chosen option, against whether the choice was right. `ece` is the count-weighted mean gap between each bin's mean prediction and its observed rate, over 10 equal bins unless `bins` says otherwise.

`changes` compares the first repeat of each case on the targets both runs ran. `mcnemar_p` is McNemar's exact two-sided test on the fixed and broken pairs. `compare` adds both runs' metrics and the regressions: each target and question whose accuracy (`within_tolerance`, for a score) dropped by more than `max_drop`, which defaults to the config's `defaults.max_drop` of 0.05. `jevtester compare` exits with 1 when there's a regression.

The wording checks are heuristics, each a prompt to look at a question: `multiple_dimensions` (more than one question mark), `degree_words` (criteria like "very" or "somewhat"), `bare_number_levels` (score levels that are only numbers), `no_abstention`, and `duplicate_options`.

## Policies

A policy turns a result's answers into an action, like `parley_succeeds`. It's YAML in `suites/policies/`, named by a suite's `policy` field. `suites/policies/parley.yaml` is the example. A policy has these parts:

- `thresholds`: named numbers, so a sweep can move them, and `per_target` values for any target whose probabilities run differently.
- `bands`: for each question, `act` and `confirm` levels for its confidence. At `act` or above the policy decides. Between `confirm` and `act` it decides, and the decision's `band` is `confirm`. Below `confirm`, or with no answer, it escalates.
- `composites`: weighted sums. A noul adds its probability of yes, a score its `score` divided by its top level, and a choice the probability of its choice.
- `rules`: checked in order, and the first whose `when` conditions all hold gives the action. A condition is an option name or a list of them for a choice, `true` or `false` for a noul, or `{at_least, at_most}` for a noul's probability, a score's `score`, or a composite. A bound is a number or a threshold's name.
- `default`: the action when no rule matches. `escalate` is the action a band gives.
- `costs`: optional, as `costs[expected][chosen]`. A wrong action that isn't listed costs 1.

Conditions are data, not expressions, so a policy can't run code. The plan's Python hook for game code isn't built: a hook named in a file the API can write would need an allowlist in `jevtester.toml` first.

A run keeps its suite's policy as it was when the run started, and `policy_version` is its hash. `TargetMetrics.decision` measures that policy's actions against each case's `expected_action`: `accuracy` over every such case, `decided_share` for the cases decided without a band escalation, `error_rate` among those, and `cost` when the policy has costs. A failed result counts as an escalation. Each `CaseResult.decision` gives the action, the band, the rule that matched, and the composites.

`PUT /api/policies/{name}` saves the YAML text as sent, comments included, after it validates. An invalid policy is a 422 with every error in `details`, and nothing is saved. `POST /api/policies/{name}/sweep` uses the policy as it is now, against a finished run's results, so a threshold can be tuned without running the suite again. Each swept value replaces the threshold for the sweep's target, whether the policy sets a shared value or a `per_target` one, and `current` is the target's value now. A sweep has at most 1,000 points.

A YAML syntax error is a 422 whose `details` entry has the `line` it's on, from 1.

## Probes

A probe changes something about a case that shouldn't change the answers, and counts how often they change anyway. `POST /api/probes` starts a run with `kind: "probe"`: each case as written, plus each probe's variants of it. Its events stream like any run's, and a `result` event's `variant` names the variant, like `option_order:2`. `GET /api/runs/{id}/probes` reports it.

| Probe | Variants per case | Applies when |
|---|---|---|
| `option_order` | 3, each a different order of every choice question's options | The questions include a choice |
| `key_order` | 1, with every JSON object's keys reversed | The state has a JSON object with more than one key |
| `bare_levels` | 1, with each score level's description replaced by its number | The questions include a score |
| `pad_state` | 1, with neutral text added until the request fills about 90% of the target's context window | The target's context window is known |

An instance changed when any answer's value (as Evaluation describes) differs from the original's. A failed request isn't counted. The metrics of a probe run count only the original cases. `jevtester probe` runs `option_order`, `key_order`, and `bare_levels` unless `--variant` says otherwise, since `pad_state` sends large requests. Paraphrasing needs Claude and isn't built.

## Fixtures

[`tests/fixtures/api/`](../tests/fixtures/api/) has one fixture for each route, named by method and path: `get_runs_{id}.json` answers `GET /api/runs/{id}`, and `get_runs_{id}_events.sse` is the event stream. A name with a dot after the route part is a variant: `post_decide.partial.json` is a decide with one target down, and `post_decide.422.json` is an error with that status. The fixtures' [README](../tests/fixtures/api/README.md) lists them.

## Changing the contract

The backend session changes the contract in this order:

1. Change the models in `src/jevtester/schemas.py`, `spec/`, or `normalize/`.
2. Regenerate the OpenAPI document: `uv run python -m jevtester.api openapi docs/openapi.json`.
3. Change the fixtures in `tests/api_fixtures.py`, and regenerate them: `uv run python tests/api_fixtures.py`.
4. Update this page, and message the frontend session with the commit and the endpoints affected.

`uv run pytest` fails if `docs/openapi.json` or a fixture is out of date.
