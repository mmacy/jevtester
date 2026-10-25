# HTTP API reference

The jevtester HTTP API gives the web UI and your scripts the same operations as the [`jevtester` command line](cli.md). Start it with `jevtester serve`. It listens on `http://127.0.0.1:8640` by default, and every route is under `/api`.

[`openapi.json`](../openapi.json) is the full OpenAPI 3.1 description, with a schema for every request and response. It's generated from the code, and a test fails when it's out of date. The running server also has interactive docs at `/docs`, like <http://127.0.0.1:8640/docs>. This page covers each route with its errors and an example, and the conventions that the schema can't express.

These terms appear throughout this page:

- A *target* is one decision model on one runtime, like `decision-1@foundry`. The [config file](config.md) lists the targets.
- A *state* is what the model reads: text, a JSON object, or a JSON array.
- A *suite* is a YAML file in `suites/` with *cases*: states, each with the answers and action it expects. A *question set* is a named set of questions, and a *policy* turns answers into an action. The [suite format reference](suite-format.md) describes all three.
- A *run* sends every case in a suite to each target and scores the answers. A *job* is one case on one target for one repeat.

[Concepts](../concepts.md) explains what the metrics and policies mean.

## Routes

| Method and path | What it does |
|---|---|
| [`GET /api/targets`](#list-targets) | List targets and their last health check. |
| [`POST /api/targets/check`](#check-targets) | Run every target's health check. |
| [`POST /api/decide`](#ask-targets-one-request) | Ask targets one request and get their answers. |
| [`GET /api/suites`](#list-suites) | List suites. |
| [`GET /api/suites/{name}`](#get-a-suite) | Get a suite with its cases and question set. |
| [`GET /api/suites/{name}/check`](#check-a-suite) | Validate a suite and run the wording checks. |
| [`POST /api/suites/{name}/cases`](#add-a-case) | Add a case to a suite. |
| [`GET /api/question-sets`](#list-question-sets) | List question sets. |
| [`GET /api/question-sets/{name}`](#get-a-question-set) | Get a question set's current version. |
| [`PUT /api/question-sets/{name}`](#save-a-question-set) | Save a question set as a new version. |
| [`GET /api/question-sets/{name}/versions`](#list-question-set-versions) | List a question set's versions. |
| [`GET /api/question-sets/{name}/versions/{version}`](#get-a-question-set-version) | Get one version of a question set. |
| [`GET /api/question-sets/{name}/diff`](#compare-question-set-versions) | Compare two versions of a question set. |
| [`POST /api/runs`](#start-a-run) | Start a run. |
| [`GET /api/runs`](#list-runs) | List runs. |
| [`GET /api/runs/{id}`](#get-a-run) | Get a run's status and counts. |
| [`GET /api/runs/{id}/events`](#stream-run-events) | Stream a run's progress. |
| [`POST /api/runs/{id}/cancel`](#cancel-a-run) | Cancel a run. |
| [`GET /api/runs/{id}/metrics`](#get-run-metrics) | Get a run's metrics. |
| [`GET /api/runs/{id}/confusion`](#get-a-confusion-matrix) | Get a confusion matrix for a choice question. |
| [`GET /api/runs/{id}/calibration`](#get-a-calibration-table) | Get a calibration table. |
| [`GET /api/runs/{id}/changes`](#get-changed-answers) | Get the answers that changed from a baseline run. |
| [`GET /api/runs/{id}/compare`](#compare-two-runs) | Compare a run with a baseline run. |
| [`GET /api/runs/{id}/cases/{case_id}`](#get-a-case-in-a-run) | Get one case with every target's full result. |
| [`GET /api/runs/{id}/report`](#get-a-run-report) | Get a run's report. |
| [`POST /api/probes`](#start-a-probe-run) | Start a probe run. |
| [`GET /api/runs/{id}/probes`](#get-probe-results) | Get a probe run's results. |
| [`GET /api/policies`](#list-policies) | List policies. |
| [`GET /api/policies/{name}`](#get-a-policy) | Get a policy. |
| [`PUT /api/policies/{name}`](#save-a-policy) | Save a policy. |
| [`POST /api/policies/{name}/sweep`](#sweep-a-policy-threshold) | Sweep a policy threshold over a run. |

A script usually checks the targets, starts a run, follows it, and reads its scores:

```sh
curl -s -X POST http://127.0.0.1:8640/api/targets/check > /dev/null
RUN_ID=$(curl -s -X POST http://127.0.0.1:8640/api/runs \
    -H 'Content-Type: application/json' -d '{"suite": "parley"}' | jq -r .id)
curl -sN "http://127.0.0.1:8640/api/runs/$RUN_ID/events"
curl -s "http://127.0.0.1:8640/api/runs/$RUN_ID/report" | jq -r .markdown
```

## Conventions

- The API has no authentication, because it listens only on this machine. Requests name targets, and the server reads the credentials, so a client never sees a token.
- Request and response bodies are JSON. A request body with a field the schema doesn't have is a 422.
- Every response field is always present. An unknown value is `null`, never a missing key.
- Times are ISO 8601 in UTC, like `2026-10-24T14:02:00Z`.
- A version is the full SHA-256 hash of the content. Show the first 12 characters. A route that takes a question set version also takes a prefix of 8 or more characters.
- Lists keep a meaningful order: targets in the order requested, questions and options in the question set's order, and runs newest first.
- Suite, question set, and policy names use lowercase letters, digits, `-`, and `_`, start with a letter or digit, and have at most 64 characters. Any other name is a 422.
- Run ids are four or more digits, like `0002`, counting up from `0001`.
- The API allows cross-origin requests only from the Vite dev server at `http://127.0.0.1:5173`, for UI development.
- Outside `/api`, the server answers with the built web UI: a built file if one exists, a 404 for a missing file under `/assets/`, and `index.html` for any other path. Until you build the UI with `npm run build` in `web/`, every one of those paths except `/assets/` returns a short HTML page with the commands that build it.

## Errors

Every 4xx response, and every 5xx response that jevtester raises itself, has this body, an `ApiError`:

```json
{
  "error": {
    "code": "invalid_request",
    "message": "Dictionary should have at least 2 items after validation, not 1",
    "field": "questions.intent.choice.criteria",
    "details": [
      {
        "field": "questions.intent.choice.criteria",
        "message": "Dictionary should have at least 2 items after validation, not 1",
        "line": null
      }
    ]
  }
}
```

| `code` | Status | Cause | What to do |
|---|---|---|---|
| `invalid_request` | 422 | The body, a parameter, a name, or a file the route reads is invalid. | Fix the input. A retry with the same input fails the same way. |
| `not_found` | 404 | No route, suite, question set, version, run, case, or policy has that name. A method the route doesn't take is a 405 with this code too. | Check the name or the method. |
| `conflict` | 409 | The change clashes with what exists, like a case id the suite already has. | Choose another id. |
| `not_ready` | 409 | The schema lists this code, but no route returns it. | |
| `internal` | 500 | A bug in jevtester. `message` says what failed. No route raises it on purpose, and an unexpected exception returns a plain-text `Internal Server Error` body instead of an `ApiError`. A failed run's `error` uses this code. | Report it. |

The fields of `error`:

- `message` says what went wrong, for a person. For a validation error, it's the first error's message.
- `field` is the dotted path of the first invalid field. For a question, the path includes the question's type, as in `questions.intent.choice.criteria`. It's `null` when the error isn't about one field.
- `details` lists every validation error. An error about one field lists that field here too, so a form can show every error the same way. Each detail's `line` is the line of a YAML document the error is on, from 1, when it's known.

A target that fails during a decide request or a run isn't an HTTP error. Its result has `ok: false` and an `error`, and the other targets' results still arrive. See [Results](#results).

## Results

Each target's answer to one request is a `TargetResult`. [`POST /api/decide`](#ask-targets-one-request) returns one per target, and runs store one per job.

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

The probabilities are rounded here, and `request_body` and `raw` are shortened.

- `ok` is `true` when the target answered. Some answers may still be missing, with a warning.
- `answers` is keyed by question id, in the request's question order. It's empty when `ok` is `false`. Each answer's `type` is `noul`, `choice`, or `score`, like its question's.
- A *noul* is a yes/no question. Its `probability` is the probability of yes, and its answer is yes when `probability` is 0.5 or more.
- A choice's `choice` is the option the server chose. Its `probabilities` follow the question's option order. A probability the server didn't send is left out, with a `missing_probability` warning. `unknown_probabilities` contains probabilities for options the question doesn't have, with an `unknown_option` warning.
- A score's `score` is the probability-weighted level index, so it can fall between levels. `level` is the most probable level, and the lower level wins a tie. It's `null` when the server sent no level probabilities. `probabilities` and `legend` are lists, lowest level first, and a missing probability is `null`, with a warning. Evaluation compares `level` with the expected level, and mean absolute error uses `score`.
- `confidence` is computed by jevtester: `(p_max - 1/n) / (1 - 1/n)` over a choice's `n` options, and `|2p - 1|` for a noul. It's always `null` for a score, so show `server_confidence` there. `server_confidence` is the server's value, when it sends one.
- `latency_ms` is the time from sending the request to receiving the response. `null` when it isn't known.
- `usage` has the token counts the server reported, each `null` when it reported none.
- `cost_usd` is `null` when the target has no price in the config or the server reported no input token count.
- `request_body` is the exact body sent, or `null` when nothing was sent. `raw` is the server's response body, unchanged, or `null` when no response arrived. For Workers AI, `raw` is the whole Cloudflare response.

`warnings` lists things a person should know. A warning doesn't stop the result from counting. Each has a `code`, a `message`, and a `question` when it's about one question. The codes are `missing_answer`, `invalid_answer`, `unknown_option`, `missing_probability`, `unexpected_answer`, `strict_parse_failed`, `truncation_on`, and `state_may_truncate`.

`error` says why a target returned no answers. Its `status` is the HTTP status when the server sent one. The codes:

| `code` | Cause | Retry? |
|---|---|---|
| `not_ready` | The target was down at its last health check, or its provider isn't built. Nothing was sent. | After you fix the target. |
| `preflight` | The request breaks one of the target's limits in the config, like `max_questions` or `context_window`, or has images, which no target takes yet. Nothing was sent. | Not with the same request. |
| `auth` | The credential failed, or the server returned 401 or 403. | After you sign in again. |
| `rate_limited` | The server returned 429. | Yes, later. |
| `bad_request` | The server rejected the request. | Not with the same request. |
| `request_too_large` | The server rejected the request's size. | Not with the same request. |
| `server_error` | The server returned a 5xx status. | Yes. |
| `timeout` | No answer within the timeout. | Yes, maybe with a longer timeout. |
| `connection` | The server couldn't be reached. | After the server is up. |
| `invalid_response` | The response wasn't a System One response jevtester could read. | Not usually. |
| `cancelled` | Reserved for a cancelled request. jevtester doesn't return it yet. | |

## Targets

A target is one decision model on one runtime, like `decision-1@foundry`. The config file lists them. List them with [`GET /api/targets`](#list-targets), and run their health checks with [`POST /api/targets/check`](#check-targets).

A target's `status` comes from its last health check:

| `status` | When |
|---|---|
| `unchecked` | No health check has run since the server started. The server doesn't run one until asked. |
| `down` | The last check gave a `reason`, like `clef-flash isn't pulled`. `detail` says what to do. |
| `warning` | The target is ready, and `warnings` isn't empty. |
| `ready` | The target is ready, with no warnings. |

A target's `warnings` come from its config, not from the check: `state_may_truncate` when `capabilities.truncates_state` is true, and `truncation_on` when the target sets `truncate = true`. `local` is true for a target whose `base_url` host is this machine, like Ollama and the MLX server. `capabilities` has every field for every target, and `null` means the limit is unknown. The [configuration reference](config.md#capabilities) describes each capability.

### List targets

`GET /api/targets`

Returns the configured targets with their capabilities and their last health check, as a `TargetList`. This call doesn't run a health check. The server keeps health check results in memory, so every target is `unchecked` after the server starts, until [`POST /api/targets/check`](#check-targets) or a run checks it.

The response's `targets` are in the config's order. `default_targets` lists the targets a request goes to when you don't name any, from the config's `defaults.targets`. `checked_at` is when [`POST /api/targets/check`](#check-targets) last ran, or `null`. A run's own health checks update each target's `checked_at`, but not this one.

```sh
curl -s http://127.0.0.1:8640/api/targets
```

Response, with one target and its capabilities shortened:

```json
{
  "targets": [
    {
      "name": "clef-flash@ollama",
      "label": "Clef-flash, Ollama",
      "provider": "systemone",
      "model": "clef-flash",
      "base_url": "http://localhost:11434",
      "local": true,
      "status": "down",
      "reason": "clef-flash isn't pulled",
      "detail": "Run ollama pull clef-flash",
      "credential": null,
      "warnings": [],
      "checked_at": "2026-10-24T14:10:00Z",
      "capabilities": {"probabilities": true, "max_questions": 64, "concurrency": 1, "...": "..."}
    }
  ],
  "default_targets": ["decision-1@foundry"],
  "checked_at": "2026-10-24T14:10:00Z"
}
```

### Check targets

`POST /api/targets/check`

Runs every target's health check at once, and returns the targets with the results, as a `TargetList`. The request has no body. A health check sends no decision request:

| Runtime | Ready when |
|---|---|
| Foundry | A token can be read from the `az` sign-in. `credential` says when it refreshes. The check never contacts `base_url`, so a target with a placeholder `base_url` still shows ready. |
| Ollama | Ollama answers, is version 0.35.1 or later, and has the model pulled. `detail` gives the version. |
| MLX | The MLX server answers and has the target's model loaded. The server serves one model, so at most one MLX target is ready at a time. |
| Workers AI | `cloudflare.account_id` is set, a token can be read from `CLOUDFLARE_API_TOKEN` or the Wrangler sign-in, and the account's Workers AI catalog lists the model. |

A check that takes longer than 15 seconds marks the target down. After a check, [`POST /api/decide`](#ask-targets-one-request) returns `not_ready` for a target that's down instead of sending to it.

The MLX server answers with whatever model it has loaded, whatever model the request asks for. So a decide request to an MLX target checks the loaded model first, and returns `not_ready` if it's another model.

```sh
curl -s -X POST http://127.0.0.1:8640/api/targets/check
```

The response has the same form as [`GET /api/targets`](#list-targets).

## Decide

### Ask targets one request

`POST /api/decide`

Sends one state and its questions to each chosen target at once, and returns one result per target, as a `DecideResponse`. Use it to try a question before you add it to a suite.

The request body, a `DecideBody`:

| Field | Description |
|---|---|
| `state` | Required. Text, a JSON object, or a JSON array. |
| `questions` | Required. At least one question, keyed by the id each answer comes back under. The [suite format reference](suite-format.md#questions) describes the question types. |
| `images` | Paths of image files sent with the state. Defaults to none. No target takes images yet, so every target returns a `preflight` error for a request with images. |
| `targets` | Target names. Empty, the default, means the config's `defaults.targets`. `["all"]` means every target. |
| `timeout_s` | Seconds to wait for each target, greater than 0. `null`, the default, uses the config's `defaults.timeout_s`. |

The response arrives when the last target finishes. To show each target's answers as they arrive, send one request per target. The response has these fields:

- `request` echoes the state and questions, so a client can label every result from the response alone.
- `question_set_version` is the hash a question set with these questions would have, which ties a quick test to a saved question set version.
- `asked_at` is when jevtester sent the request.
- `results` has one [`TargetResult`](#results) per target, in the order the targets were named.

A target that's down after its last health check, or a request that breaks the target's limits, gets a result with the error code `not_ready` or `preflight`, and nothing is sent to it. To keep a result as a test case, send its state and expected answers to [`POST /api/suites/{name}/cases`](#add-a-case).

Errors:

- 422 with the field `targets.<index>` for an unknown target name, or a name given twice.
- 422 for an invalid question, like a choice with fewer than 2 options.

With `goblin.json` holding the state and questions shown in the [`jevtester decide` example](cli.md#jevtester-decide), plus `"targets": ["decision-1@foundry", "clef-flash@ollama"]`:

```sh
curl -s -X POST http://127.0.0.1:8640/api/decide \
    -H 'Content-Type: application/json' -d @goblin.json
```

Response, with `request` and the first result's answers shortened. Ollama was down at its last health check, so nothing was sent to it:

```json
{
  "request": {"state": {"party": "Three adventurers, torches lit", "...": "..."}, "questions": {"...": "..."}, "images": []},
  "question_set_version": "95e251b70a75ea722a0c62ce89024a58c6bdb1a3ebde485db30bba925ffc0cb6",
  "asked_at": "2026-10-24T14:10:00Z",
  "results": [
    {
      "target": "decision-1@foundry",
      "ok": true,
      "latency_ms": 1550.0,
      "usage": {"input_tokens": 185, "output_tokens": 3},
      "cost_usd": null,
      "warnings": [],
      "error": null,
      "answers": {
        "intent": {"type": "choice", "choice": "parley", "...": "..."},
        "bribe": {"type": "noul", "probability": 0.9988304895647238, "confidence": 0.9976609791294475, "server_confidence": null},
        "reaction": {"type": "score", "score": 2.20874314700501, "level": 2, "...": "..."}
      },
      "request_body": {"...": "..."},
      "raw": {"...": "..."}
    },
    {
      "target": "clef-flash@ollama",
      "ok": false,
      "latency_ms": null,
      "usage": {"input_tokens": null, "output_tokens": null},
      "cost_usd": null,
      "warnings": [],
      "error": {"code": "not_ready", "message": "clef-flash isn't pulled", "status": null},
      "answers": {},
      "request_body": null,
      "raw": null
    }
  ]
}
```

An unknown target:

```console
$ curl -s -X POST http://127.0.0.1:8640/api/decide -H 'Content-Type: application/json' \
    -d '{"state": "s", "questions": {"q": {"type": "noul", "instructions": "?"}}, "targets": ["clef@nowhere"]}'
{"error":{"code":"invalid_request","message":"Unknown target: clef@nowhere","field":"targets.0","details":[{"field":"targets.0","message":"Unknown target: clef@nowhere","line":null}]}}
```

## Suites

A suite is a YAML file in `suites/` with cases, the question set they're asked, an optional policy, and default targets. A suite's name is its file name without `.yaml`. Read suites, check them, and add cases here, then run one with [`POST /api/runs`](#start-a-run). An invalid suite file returns 422 from any route that reads it, with a message that names the file. [`GET /api/suites/{name}/check`](#check-a-suite) is the exception: it returns 200 with `valid: false`.

### List suites

`GET /api/suites`

Returns every suite under `suites/`, by name, as a `SuiteList`. Each entry has the suite's question set and its current version (`null` when the question set doesn't exist), its policy, its default targets, `case_count` for the cases that count in evaluation, and `draft_count` for cases with `provenance: claude-draft`.

```console
$ curl -s http://127.0.0.1:8640/api/suites
{"suites":[{"name":"parley","question_set":"parley","question_set_version":"95e251b70a75ea722a0c62ce89024a58c6bdb1a3ebde485db30bba925ffc0cb6","policy":"parley","targets":["decision-1@foundry","clef-flash@workers-ai"],"case_count":4,"draft_count":1}]}
```

### Get a suite

`GET /api/suites/{name}`

Returns a suite with every case, and its question set's current version, as a `SuiteDetail`. Reading a suite records its question set's version, if jevtester hasn't seen it before.

Errors: 404 for a missing suite or question set, and 422 for an invalid name or file.

```sh
curl -s http://127.0.0.1:8640/api/suites/parley
```

### Check a suite

`GET /api/suites/{name}/check`

Validates a suite and runs the question-wording checks on its question set, and returns a `SuiteCheck`. The suite is valid when it, its question set, and its policy load, every case's expectations fit the questions, no case id is used twice, and the policy reads only questions the question set asks.

An invalid suite returns 200 with `valid: false` and its `errors`. `checks` lists the wording findings, which are prompts to look at a question and don't make the suite invalid. The [suite format reference](suite-format.md#wording-checks) lists the checks. A suite that doesn't exist returns 404.

```console
$ curl -s http://127.0.0.1:8640/api/suites/parley/check
{"suite":"parley","valid":true,"errors":[],"checks":[{"question":"intent","code":"no_abstention","message":"No option like cannot_tell"}]}
```

### Add a case

`POST /api/suites/{name}/cases`

Adds a case to the end of a suite's file, and returns 201 with a `CaseCreated`: the suite's name, the case as saved, and the suite's new case count. The body is a `Case`, which the [suite format reference](suite-format.md#cases) describes. Only `id` and `state` are required.

jevtester rewrites the file from its parsed contents, so the change shows up in `git diff` and comments in the file are lost. The route doesn't check the case against the question set, so check the suite afterward with [`GET /api/suites/{name}/check`](#check-a-suite).

Errors: 409 `conflict` with the field `id` for a case id the suite already has, and nothing is saved. 404 for a missing suite. 422 for an invalid case.

```console
$ curl -s -X POST http://127.0.0.1:8640/api/suites/parley/cases -H 'Content-Type: application/json' \
    -d '{"id": "troll-toll", "state": "A troll blocks the bridge and asks for a toll.", "expected": {"intent": {"answer": "parley"}, "reaction": {"answer": 2, "tolerance": 1}}, "expected_action": "parley_succeeds", "tags": ["bribe"]}'
{"suite":"parley","case":{"id":"troll-toll","state":"A troll blocks the bridge and asks for a toll.","images":[],"expected":{"intent":{"answer":"parley","acceptable":null,"tolerance":0},"reaction":{"answer":2,"acceptable":null,"tolerance":1}},"expected_action":"parley_succeeds","tags":["bribe"],"provenance":"human"},"case_count":5}
```

The same id again:

```json
{"error":{"code":"conflict","message":"The suite already has a case troll-toll","field":"id","details":[{"field":"id","message":"The suite already has a case troll-toll","line":null}]}}
```

## Question sets

A question set is a named set of questions in `suites/question-sets/`. A *version* is the SHA-256 hash of its questions in order, so any edit makes a new version, and the name isn't part of it. jevtester records each version the first time it sees one: when a suite or question set is read or saved, or when a run uses one. Earlier versions stay available for runs and comparisons after the file changes.

### List question sets

`GET /api/question-sets`

Returns every question set under `suites/question-sets/`, by name, as a `QuestionSetList`. Each entry has its current version, its question count, the suites that use it, and `updated_at`, when the current version was first seen.

```sh
curl -s http://127.0.0.1:8640/api/question-sets
```

### Get a question set

`GET /api/question-sets/{name}`

Returns a question set's current version, the suites that use it, and its wording checks, as a `QuestionSetDetail`. A missing question set returns 404.

```sh
curl -s http://127.0.0.1:8640/api/question-sets/parley
```

### Save a question set

`PUT /api/question-sets/{name}`

Replaces a question set's questions, which makes a new version, and returns the saved question set as a `QuestionSetDetail`. Creates the question set if it's new. The body is a `QuestionSetBody`: `questions`, at least one, keyed by id.

jevtester rewrites `suites/question-sets/<name>.yaml`, so the change shows up in `git diff` and comments in the file are lost. Saving the same questions again keeps the same version. Every suite whose `question_set` is this one asks the new version in its next run.

Errors: 422 for an invalid name or question.

```sh
curl -s -X PUT http://127.0.0.1:8640/api/question-sets/parley \
    -H 'Content-Type: application/json' \
    -d '{"questions": {"bribe": {"type": "noul", "instructions": "Does the player offer the monsters something of value?"}}}'
```

### List question set versions

`GET /api/question-sets/{name}/versions`

Returns every version of a question set that jevtester has seen, newest first, as a `QuestionSetVersions`. Each version has its hash, when it was first seen, its question count, how many runs used it, and whether it's the version in the file now. Pass a hash to [`GET /api/question-sets/{name}/versions/{version}`](#get-a-question-set-version), to [`GET /api/question-sets/{name}/diff`](#compare-question-set-versions), or as `question_set_version` in [`POST /api/runs`](#start-a-run).

A missing question set returns 404.

```console
$ curl -s http://127.0.0.1:8640/api/question-sets/parley/versions
{"name":"parley","versions":[{"version":"95e251b70a75ea722a0c62ce89024a58c6bdb1a3ebde485db30bba925ffc0cb6","first_seen":"2026-10-24T14:05:00Z","question_count":3,"run_count":4,"current":true},{"version":"2566eb4afe018185cb31f7b51fae00002a89c1a890b4d9f5b4ca4b65ffa235a3","first_seen":"2026-10-24T13:20:00Z","question_count":3,"run_count":1,"current":false}]}
```

### Get a question set version

`GET /api/question-sets/{name}/versions/{version}`

Returns one version of a question set, as a `QuestionSet` with its `name`, `questions`, and `version`. `version` in the path is the hash, or a prefix of it at least 8 characters long.

A version jevtester hasn't recorded, or a prefix that matches more than one version, returns 404.

```sh
curl -s http://127.0.0.1:8640/api/question-sets/parley/versions/2566eb4a
```

### Compare question set versions

`GET /api/question-sets/{name}/diff?from=<version>&to=<version>`

Compares two versions of a question set, question by question and option by option, and returns a `QuestionSetDiff`. Both query parameters are required, and each takes a hash or a prefix of 8 or more characters.

Each question in `questions` has a `status` of `added`, `removed`, `changed`, or `unchanged`, the question `before` and `after`, and `changed_fields`. `options` lists each option or level in the newer version's order, then removed ones, each with a status. An unchanged question's `options` is empty. `order_changed` is true when the options of a choice that both versions have are in a different order.

A version that doesn't exist returns 404.

```sh
curl -s 'http://127.0.0.1:8640/api/question-sets/parley/diff?from=2566eb4a&to=95e251b7'
```

Response, with one question and its `before` and `after` shortened:

```json
{
  "name": "parley",
  "from_version": "2566eb4afe018185cb31f7b51fae00002a89c1a890b4d9f5b4ca4b65ffa235a3",
  "to_version": "95e251b70a75ea722a0c62ce89024a58c6bdb1a3ebde485db30bba925ffc0cb6",
  "questions": [
    {
      "id": "intent",
      "status": "changed",
      "before": {"type": "choice", "...": "..."},
      "after": {"type": "choice", "...": "..."},
      "changed_fields": ["criteria"],
      "options": [
        {"key": "parley", "status": "unchanged", "before": "Talk, bargain, bribe, or negotiate", "after": "Talk, bargain, bribe, or negotiate"},
        {"key": "evade", "status": "unchanged", "before": "Run away or avoid the monsters", "after": "Run away or avoid the monsters"},
        {"key": "fight", "status": "unchanged", "before": "Attack the monsters", "after": "Attack the monsters"},
        {"key": "wait", "status": "added", "before": null, "after": "Hold position and watch"}
      ],
      "order_changed": false
    }
  ]
}
```

## Runs

A run sends every case in a suite to each target and scores the answers. Start one with [`POST /api/runs`](#start-a-run), follow it with [`GET /api/runs/{id}/events`](#stream-run-events), then read [`GET /api/runs/{id}/metrics`](#get-run-metrics), [`GET /api/runs/{id}/report`](#get-a-run-report), or [`GET /api/runs/{id}/compare`](#compare-two-runs).

A run's `status` moves from `queued` to `running`, then ends as `finished`, `cancelled`, or `failed`. Each time a jevtester process loads its config and run store, it marks every queued or running run `failed`, with the error `The server stopped during the run`. `jevtester serve` does this when it starts, and so does each CLI command that loads the config, like `jevtester run` or `jevtester report`. It happens even to a run that another process is still running.

A run's `counts` count jobs. A job is one case on one target for one repeat, or for one probe variant in a probe run. `done` is `sent + cached + failed + skipped`, so `done / jobs` is the progress. `sent` counts jobs that got an answer. `failed` counts jobs whose result has `ok: false`, including `preflight` and `not_ready` results where nothing was sent. `targets` breaks the counts down by target, with `skip_reason` for a target whose jobs were skipped.

A run keeps a copy of the cases it ran and of its suite's policy, so editing the suite afterward doesn't change how the run is scored.

### Start a run

`POST /api/runs`

Starts a run of a suite, and returns 202 with the run's id as soon as it's queued. The run continues in the background. Follow it with [`GET /api/runs/{id}/events`](#stream-run-events), or poll [`GET /api/runs/{id}`](#get-a-run).

The request body, a `RunCreate`:

| Field | Description |
|---|---|
| `suite` | Required. The suite's name. |
| `targets` | Target names. Empty, the default, means the suite's `targets`, or else the config's `defaults.targets`. |
| `question_set_version` | A question set version to run, as a hash or a prefix of 8 or more characters. `null`, the default, runs the current version. |
| `repeats` | Times to send each case to each target, at least 1. `null`, the default, uses the config's `defaults.repeats`. |
| `no_cache` | `true` sends every request, even when a cached result exists. Defaults to `false`. |
| `baseline` | A run to compare with. It must exist. The run's report then lists the answers that changed from it. Defaults to `null`. |

Before it sends anything, the run checks the health of each of its targets, and skips every job of a target that's down. Each job's result is cached by its target, its request, and its repeat, so a rerun of an unchanged suite sends nothing. Each request waits up to the config's `defaults.timeout_s`. Cases with `provenance: claude-draft` aren't sent.

Errors: 404 for a suite, question set version, or baseline run that doesn't exist. 422 for an unknown target or a name given twice.

```console
$ curl -s -X POST http://127.0.0.1:8640/api/runs -H 'Content-Type: application/json' \
    -d '{"suite": "parley", "targets": ["decision-1@foundry"], "baseline": "0001"}'
{"id":"0005"}
```

### List runs

`GET /api/runs`

Returns every run, suite runs and probe runs, newest first, as a `RunList` of `RunSummary` objects.

```sh
curl -s http://127.0.0.1:8640/api/runs
```

### Get a run

`GET /api/runs/{id}`

Returns a run's settings, status, and counts, as a `RunSummary`. Poll it to follow a run without the event stream. A run that doesn't exist returns 404.

`cost_usd` is the total cost of the requests the run sent. Cached results cost nothing. It's `null` until a result arrives from the cache or from a target whose price is known. `error` explains why the run failed when `status` is `failed`.

```console
$ curl -s http://127.0.0.1:8640/api/runs/0005
{"id":"0005","kind":"suite","suite":"parley","question_set":"parley","question_set_version":"95e251b70a75ea722a0c62ce89024a58c6bdb1a3ebde485db30bba925ffc0cb6","policy":"parley","policy_version":"bc95cc4f4030850fa5ba4383e3beabd1dd1a513e0b01e7d2ecd4c64d4009485e","targets":["decision-1@foundry"],"repeats":1,"variants":[],"no_cache":false,"baseline":"0001","status":"finished","case_count":4,"counts":{"jobs":4,"done":4,"sent":0,"cached":4,"failed":0,"skipped":0,"targets":[{"target":"decision-1@foundry","jobs":4,"sent":0,"cached":4,"failed":0,"skipped":0,"skip_reason":null}]},"cost_usd":0.0,"created_at":"2026-10-24T14:10:00Z","started_at":"2026-10-24T14:10:00Z","finished_at":"2026-10-24T14:10:00Z","error":null}
```

### Stream run events

`GET /api/runs/{id}/events`

Streams a run's progress as server-sent events (SSE), until the run ends. Each event's `event` field is its type, `id` numbers it from 0 on each connection, and `data` is one line of JSON whose `type` matches `event`:

| `event` | Sent when | Carries |
|---|---|---|
| `progress` | First on every connection, and when the run starts running | `status`, `counts` |
| `result` | A job finishes | `case_id`, `target`, `repeat` (from 0), `variant`, `cached`, the `result`, and `counts` |
| `target_skipped` | A target's jobs are skipped, because it was down when the run started | `target`, `reason`, `counts` |
| `finished` | The run finishes | `counts`, `summary` |
| `cancelled` | The run is cancelled | `counts`, `summary` |
| `error` | The run fails | `error`, `counts`, `summary` |

Every event has `run_id` and `counts`, so a client can draw progress from any one event. A `result` event's [`TargetResult`](#results) has `request_body` and `raw` set to `null`, to keep the stream small. [`GET /api/runs/{id}/cases/{case_id}`](#get-a-case-in-a-run) returns them. A `result` event's `variant` is the probe variant's id, like `option_order:2`, or is `null` for the original case.

The stream ends after `finished`, `cancelled`, or `error`. A client that reconnects gets a fresh `progress` event and then the events that follow, so it needs no history. A run that has already ended sends `progress` and its final event. A browser's `EventSource` reconnects when the server closes the stream, so close it on the final event. A run that doesn't exist returns a 404 JSON error before the stream starts.

```sh
curl -sN http://127.0.0.1:8640/api/runs/0005/events
```

For a run that has already ended, the stream is two events, with `counts` and `summary` shortened here:

```text
event: progress
data: {"type":"progress","run_id":"0005","status":"finished","counts":{"jobs":4,"done":4,"sent":0,"cached":4,"failed":0,"skipped":0,"targets":[...]}}
id: 0

event: finished
data: {"type":"finished","run_id":"0005","counts":{...},"summary":{"id":"0005","kind":"suite","status":"finished",...}}
id: 1
```

A `result` event during a run looks like this, shortened:

```text
event: result
data: {"type":"result","run_id":"0002","case_id":"goblin-bribe","target":"decision-1@foundry","repeat":0,"variant":null,"cached":false,"result":{"target":"decision-1@foundry","ok":true,...,"request_body":null,"raw":null},"counts":{...}}
id: 3
```

### Cancel a run

`POST /api/runs/{id}/cancel`

Cancels a queued or running run, waits for it to stop, and returns its `RunSummary`. Results that arrived before the cancel are kept. Cancelling a run that has ended returns it unchanged, so the call is safe to retry. The server can cancel only runs it started. A run that doesn't exist returns 404.

```sh
curl -s -X POST http://127.0.0.1:8640/api/runs/0005/cancel
```

### Get run metrics

`GET /api/runs/{id}/metrics`

Scores a run's answers for each target and question, and returns a `RunMetrics`. When the suite has a policy, each target also has `decision` metrics for the policy's actions. A metric that doesn't apply to a question's type is `null`, and so is every metric but `n` and `consistency` when no answer was scored. Only original cases count, not probe variants. A run that doesn't exist returns 404.

Each answer is scored the same way across the metrics, the confusion matrix, the calibration table, the changes, and a run's cases:

- A noul's answer is yes when the probability of yes is 0.5 or more.
- A choice's answer is its `choice`.
- A score's answer is its `level`. `accuracy` counts exact levels. `within_tolerance` allows each case's `tolerance` in levels, and so do the `correct` marks, the changes, and the regression check. `mae` uses `score`.
- An answer matches when it equals the expected answer or one of the `acceptable` ones. A missing answer is wrong. A result with `ok: false` isn't scored. A question the case expects nothing for isn't scored.

The fields of each question's metrics:

| Field | Applies to | Meaning |
|---|---|---|
| `n` | All | Answers scored against an expectation. |
| `accuracy` | All | The share of scored answers that match. |
| `macro_f1` | Choice | F1 averaged across options. |
| `mae` | Score | Mean absolute error between `score` and the expected level. |
| `within_tolerance` | Score | The share of answers whose `level` is within the case's tolerance. |
| `brier`, `log_loss` | Noul | Probability scores. Lower is better. |
| `auroc` | Noul | Area under the ROC curve. `null` when the cases are all yes or all no. |
| `ece` | Noul, choice | Expected calibration error. `null` for a target without probabilities. |
| `abstention_rate` | Choice | How often the target chose the question's abstention option, found by name: `abstain`, `cannot_tell`, `cant_tell`, `unclear`, `unknown`, or `unsure`. `null` when it has none. |
| `consistency` | All | The share of cases whose answer was the same in every repeat. `null` with one repeat. |

The `decision` metrics measure the policy's actions against each case's `expected_action`. `accuracy` is over every such case, `decided_share` is the share decided without a band escalation, `error_rate` is the error rate among those, and `cost` is the total from the policy's `costs`, or `null` without them. A failed result counts as an escalation.

```sh
curl -s http://127.0.0.1:8640/api/runs/0002/metrics
```

Response, with one target and one question:

```json
{
  "run_id": "0002",
  "questions": ["intent", "bribe", "reaction"],
  "targets": [
    {
      "target": "decision-1@foundry",
      "results": 4,
      "errors": 0,
      "skipped": 0,
      "probabilities": true,
      "latency_p50_ms": 1519.0,
      "latency_p95_ms": 1595.9,
      "cost_usd": null,
      "cost_per_1k_usd": null,
      "questions": [
        {
          "question": "intent",
          "type": "choice",
          "n": 4,
          "accuracy": 1.0,
          "macro_f1": 1.0,
          "mae": null,
          "within_tolerance": null,
          "brier": null,
          "log_loss": null,
          "auroc": null,
          "ece": 0.05359632741365261,
          "abstention_rate": null,
          "consistency": null
        }
      ],
      "decision": {"n": 4, "accuracy": 1.0, "decided_share": 1.0, "error_rate": 0.0, "cost": 0.0}
    }
  ]
}
```

### Get a confusion matrix

`GET /api/runs/{id}/confusion?question=<id>&target=<name>`

Counts expected options against answered options, for one choice question and one target, and returns a `ConfusionMatrix`. Both query parameters are required.

`options` labels the rows and columns: the question's options in order, then any unknown option the target answered. `counts[i][j]` is the number of answers, counting each repeat, that expected `options[i]` and got `options[j]`. `recall` has each option's recall, or `null` for an option no case expected.

Errors: 404 for a run that doesn't exist. 422 for a question the run didn't ask, a question that isn't a choice, or a target the run didn't run.

```console
$ curl -s 'http://127.0.0.1:8640/api/runs/0002/confusion?question=intent&target=clef-flash@workers-ai'
{"run_id":"0002","target":"clef-flash@workers-ai","question":"intent","options":["parley","evade","fight","wait"],"counts":[[1,0,0,0],[0,0,0,1],[0,0,1,0],[0,0,0,1]],"correct":3,"total":4,"recall":[1.0,0.0,1.0,1.0]}
```

### Get a calibration table

`GET /api/runs/{id}/calibration?question=<id>&target=<name>&bins=<n>`

Builds a reliability table for one noul or choice question and one target, and returns a `Calibration`. A reliability table compares the probabilities a target gave with how often it was right. For a noul, the prediction is the probability of yes. For a choice, it's the probability of the chosen option, against whether the choice was right.

| Parameter | Description |
|---|---|
| `question` | Required. A noul or choice question the run asked. |
| `target` | Required. A target the run ran. |
| `bins` | The number of equal-width bins from 0 to 1, from 1 to 100. Defaults to 10. |

`ece` is the count-weighted mean gap between each bin's mean prediction and its observed rate, or `null` when there are no predictions. An empty bin has `null` for `mean_predicted` and `observed_rate`.

Errors: 404 for a run that doesn't exist. 422 for a score question, a question the run didn't ask, a target the run didn't run, or `bins` outside 1 to 100.

```console
$ curl -s 'http://127.0.0.1:8640/api/runs/0002/calibration?question=bribe&target=decision-1@foundry&bins=4'
{"run_id":"0002","target":"decision-1@foundry","question":"bribe","bins":[{"lower":0.0,"upper":0.25,"count":3,"mean_predicted":0.008,"observed_rate":0.0},{"lower":0.25,"upper":0.5,"count":0,"mean_predicted":null,"observed_rate":null},{"lower":0.5,"upper":0.75,"count":0,"mean_predicted":null,"observed_rate":null},{"lower":0.75,"upper":1.0,"count":1,"mean_predicted":0.9988304895647238,"observed_rate":1.0}],"ece":0.006292377608819061,"n":4}
```

### Get changed answers

`GET /api/runs/{id}/changes?baseline=<id>`

Lists the answers that changed from a baseline run, on the targets both runs ran, and returns a `RunChanges`. The comparison uses the first repeat of each case. To get both runs' metrics and the regressions too, use [`GET /api/runs/{id}/compare`](#compare-two-runs).

Each change has a `status`:

- `fixed`: the answer went from wrong to right.
- `broken`: the answer went from right to wrong.
- `changed`: the answer changed and stayed right or stayed wrong, like a score that moved within its tolerance, or the case has no expectation.

`summary` has one row per target with the counts and `mcnemar_p`, McNemar's exact two-sided test on the fixed and broken answers. `mcnemar_p` is `null` when nothing was fixed or broken.

Errors: 404 when either run doesn't exist.

```sh
curl -s 'http://127.0.0.1:8640/api/runs/0002/changes?baseline=0001'
```

Response, with one change and one summary row:

```json
{
  "run_id": "0002",
  "baseline": "0001",
  "changes": [
    {
      "case_id": "gnoll-watch",
      "target": "decision-1@foundry",
      "question": "intent",
      "expected": "wait",
      "baseline_answer": "evade",
      "baseline_probability": 0.8703703703703703,
      "answer": "wait",
      "probability": 0.892,
      "status": "fixed"
    }
  ],
  "summary": [
    {"target": "decision-1@foundry", "fixed": 1, "broken": 0, "changed": 0, "mcnemar_p": 1.0}
  ]
}
```

### Compare two runs

`GET /api/runs/{id}/compare?baseline=<id>&max_drop=<share>`

Compares a run with a baseline, and returns a `RunComparison`: both runs' metrics, the changed answers as [`GET /api/runs/{id}/changes`](#get-changed-answers) returns them, and any regressions. A *regression* is a target and question whose accuracy, or within-tolerance accuracy for a score, dropped by more than `max_drop`. `jevtester compare` returns the same JSON, and exits with 1 when `regressions` isn't empty.

| Parameter | Description |
|---|---|
| `baseline` | Required. The baseline run's id. |
| `max_drop` | The largest allowed drop, 0 or more, as a share like `0.05`. Without it, the config's `defaults.max_drop` applies. The response's `max_drop` is the value used. |

Errors: 404 when either run doesn't exist. 422 for a negative `max_drop`.

```sh
curl -s 'http://127.0.0.1:8640/api/runs/0001/compare?baseline=0002'
```

The response's `regressions` from that call, with the metrics left out:

```json
[{"target": "decision-1@foundry", "question": "intent", "metric": "accuracy", "baseline": 1.0, "value": 0.75, "drop": 0.25}]
```

### Get a case in a run

`GET /api/runs/{id}/cases/{case_id}`

Returns one case as the run sent it, the questions the run asked, and every job's full result for the case, as a `RunCase`. Each result has `correct`, which shows whether each answer met the case's expectation (`null` without one), and `decision`, the policy's decision from those answers (`null` without a policy, or when the target failed). Unlike a `result` event, each result here has `request_body` and `raw`.

The `decision` has the `action`, the `band` (`act`, `confirm`, or `escalate`), whether the policy `escalated` because of a band, the index of the `rule` that matched, each composite's value, and a `reason` when it escalated or no rule matched.

Errors: 404 for a run that doesn't exist, or a case the run didn't send.

```sh
curl -s http://127.0.0.1:8640/api/runs/0002/cases/goblin-bribe
```

### Get a run report

`GET /api/runs/{id}/report`

Returns a run's summary and metrics, and the same report as Markdown in `markdown`, as a `RunReport`. When the run has a baseline, the Markdown also lists the answers that changed from it. `jevtester report` prints the same Markdown. A run that doesn't exist returns 404.

```sh
curl -s http://127.0.0.1:8640/api/runs/0002/report | jq -r .markdown > report.md
```

## Probes

A probe changes something about a case that shouldn't change the answers, like the order of a choice's options, and counts how often they change anyway. A probe run sends each case as written, plus each probe's variants of it.

| Probe | Variants per case | Applies when |
|---|---|---|
| `option_order` | 3, each a different order of every choice question's options | The questions include a choice. |
| `key_order` | 1, with every JSON object's keys reversed | The state has a JSON object with more than one key. |
| `bare_levels` | 1, with each score level's description replaced by its number | The questions include a score. |
| `pad_state` | 1, with neutral text added until the request fills about 90% of the target's context window | The target's `context_window` is known. |

### Start a probe run

`POST /api/probes`

Starts a probe run, and returns 202 with the run's id. The run has `kind: "probe"`, and streams events like any run from [`GET /api/runs/{id}/events`](#stream-run-events). When it ends, [`GET /api/runs/{id}/probes`](#get-probe-results) reports it. A probe run sends each request once, whatever the config's repeats.

The request body, a `ProbeCreate`:

| Field | Description |
|---|---|
| `suite` | Required. The suite's name. |
| `variants` | Required. At least one probe. A probe named twice runs once. |
| `targets` | Target names. Empty, the default, means the suite's `targets`, or else the config's. |
| `question_set_version` | A question set version to run. `null`, the default, runs the current version. |
| `no_cache` | `true` sends every request, even when a cached result exists. Defaults to `false`. |

Errors: 404 for a suite or question set version that doesn't exist. 422 for an unknown target or probe.

```console
$ curl -s -X POST http://127.0.0.1:8640/api/probes -H 'Content-Type: application/json' \
    -d '{"suite": "parley", "targets": ["decision-1@foundry"], "variants": ["option_order"]}'
{"id":"0006"}
```

### Get probe results

`GET /api/runs/{id}/probes`

Reports how often each case's answers changed under each probe, for a probe run, and returns a `ProbeReport`. An instance changed when any answer differs from the original case's answer on its first repeat. A failed request isn't counted.

`cells` has one cell for each case, target, and probe that has instances: the instances that got an answer, how many changed, and the change rate. `summary` has one row for each target and probe, with the change rate across every case. The metrics of a probe run count only the original cases.

Errors: 404 for a run that doesn't exist. 422 for a suite run.

```sh
curl -s http://127.0.0.1:8640/api/runs/0003/probes
```

Response, with two cells and two summary rows:

```json
{
  "run_id": "0003",
  "variants": ["option_order", "key_order", "bare_levels"],
  "cells": [
    {"case_id": "goblin-bribe", "target": "decision-1@foundry", "variant": "option_order", "instances": 3, "changed": 0, "change_rate": 0.0},
    {"case_id": "goblin-bribe", "target": "decision-1@foundry", "variant": "key_order", "instances": 1, "changed": 0, "change_rate": 0.0}
  ],
  "summary": [
    {"target": "decision-1@foundry", "variant": "option_order", "cases": 4, "change_rate": 0.16666666666666666},
    {"target": "clef-flash@workers-ai", "variant": "bare_levels", "cases": 4, "change_rate": 1.0}
  ]
}
```

## Policies

A policy is a YAML file in `suites/policies/` that turns a result's answers into an action, like `parley_succeeds` or `escalate`. A suite gives its policy's name in `policy`, and run metrics measure the policy's decisions. The [suite format reference](suite-format.md#policies) describes the format. A policy's version is the SHA-256 hash of the parsed policy, so its name, comments, and layout aren't part of it.

### List policies

`GET /api/policies`

Returns every policy under `suites/policies/`, by name, as a `PolicyList`. Each entry has its version, the actions it can choose in the order the file lists them, and the suites that use it. An invalid policy file returns 422.

```console
$ curl -s http://127.0.0.1:8640/api/policies
{"policies":[{"name":"parley","version":"bc95cc4f4030850fa5ba4383e3beabd1dd1a513e0b01e7d2ecd4c64d4009485e","actions":["battle","evade","wait","escalate","parley_succeeds","parley_fails"],"suites":["parley"]}]}
```

### Get a policy

`GET /api/policies/{name}`

Returns a policy's YAML text, its version, its actions, its thresholds with any per-target values, and the suites that use it, as a `PolicyDetail`. A missing policy returns 404.

```sh
curl -s http://127.0.0.1:8640/api/policies/parley
```

### Save a policy

`PUT /api/policies/{name}`

Validates a policy's YAML text and saves it as sent, comments included, and returns the saved `PolicyDetail`. Creates the policy if it's new. The body is a `PolicyBody`: `yaml`, the text. The policy's `name` in the YAML must match the name in the path.

An invalid policy returns 422 with every error in `details`, and nothing is saved. A YAML syntax error's detail has the `line` it's on, from 1.

```sh
curl -s -X PUT http://127.0.0.1:8640/api/policies/parley \
    -H 'Content-Type: application/json' \
    --data-binary "$(jq -n --rawfile yaml suites/policies/parley.yaml '{yaml: $yaml}')"
```

A syntax error:

```console
$ curl -s -X PUT http://127.0.0.1:8640/api/policies/parley -H 'Content-Type: application/json' \
    -d '{"yaml": "name: parley\nrules:\n  - action: battle\n    when: {intent: fight\n"}'
{"error":{"code":"invalid_request","message":"Line 5: expected ',' or '}', but got '<stream end>'","field":null,"details":[{"field":null,"message":"Line 5: expected ',' or '}', but got '<stream end>'","line":5}]}}
```

### Sweep a policy threshold

`POST /api/policies/{name}/sweep`

Measures one target's decisions in a run as one of the policy's thresholds moves from `start` to `stop`, and returns a `SweepResult`. The sweep uses the policy as it is now, against the run's answers, so you can tune a threshold without running the suite again. Each value replaces the threshold for the sweep's target, whether the policy sets a shared value or a `per_target` one. `current` is the target's value now.

The request body, a `SweepBody`:

| Field | Description |
|---|---|
| `run_id` | Required. The id of the run whose answers the sweep measures. |
| `target` | Required. A target the run ran. |
| `threshold` | Required. The name of the policy threshold to move. |
| `start` | The first value. Defaults to 0. |
| `stop` | The last value. Defaults to 1. It's included when `start` plus a whole number of steps reaches it. |
| `step` | The gap between values, greater than 0. Defaults to 0.05. |

Each point has the `value`, `decided_share` (the share of cases decided without escalating), `error_rate` (among the decided cases), and `cost` from the policy's cost matrix, or `null` when the policy has no `costs`.

Errors: 404 for a policy or run that doesn't exist. 422 for a threshold the policy doesn't have, a target the run didn't run, a `stop` below `start`, or a range of more than 1,000 points.

```console
$ curl -s -X POST http://127.0.0.1:8640/api/policies/parley/sweep -H 'Content-Type: application/json' \
    -d '{"run_id": "0002", "target": "decision-1@foundry", "threshold": "goodwill", "start": 0.3, "stop": 0.9, "step": 0.1}'
{"policy":"parley","run_id":"0002","target":"decision-1@foundry","threshold":"goodwill","current":0.55,"points":[{"value":0.3,"decided_share":1.0,"error_rate":0.0,"cost":0.0},{"value":0.4,"decided_share":1.0,"error_rate":0.0,"cost":0.0},{"value":0.5,"decided_share":1.0,"error_rate":0.0,"cost":0.0},{"value":0.6,"decided_share":1.0,"error_rate":0.0,"cost":0.0},{"value":0.7,"decided_share":1.0,"error_rate":0.0,"cost":0.0},{"value":0.8,"decided_share":1.0,"error_rate":0.25,"cost":2.0},{"value":0.9,"decided_share":1.0,"error_rate":0.25,"cost":2.0}]}
```

## Changing the contract

These steps are for contributors who change the API. The routes, their models, `docs/openapi.json`, and the fixtures in `tests/fixtures/api/` are the contract between the backend and the web UI. Change them in this order:

1. Change the models in `src/jevtester/schemas.py`, `spec/`, or `normalize/`, or the routes in `src/jevtester/api.py`. A field's docstring is its description in the OpenAPI document, and a route's docstring is its description.
2. Regenerate the OpenAPI document: `uv run python -m jevtester.api openapi docs/openapi.json`.
3. Regenerate the web UI's types: `npm run gen:api` in `web/`.
4. Change the fixtures in `tests/api_fixtures.py`, and regenerate them: `uv run python tests/api_fixtures.py`. `tests/fixtures/api/README.md` lists them.
5. Update this page.

`uv run pytest` fails if `docs/openapi.json` or a fixture is out of date.
