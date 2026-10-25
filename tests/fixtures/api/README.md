# API fixtures

One saved response for each route in [the API contract](../../../docs/reference/http-api.md), for the UI's fixture mode and the contract tests. [`tests/api_fixtures.py`](../../api_fixtures.py) builds every file here from the API models. Don't edit them by hand. After a change, regenerate them:

```sh
uv run python tests/api_fixtures.py
```

## Names

A file name is the method and the path after `/api/`, joined with underscores, with each path parameter kept as `{name}`. `get_runs_{id}_events.sse` is a raw event stream. A dot after the route part marks a variant:

| Variant | Contains |
|---|---|
| `get_targets.unchecked.json` | Every target before the first health check |
| `post_decide.partial.json` | A decide on three targets, with `clef-flash@ollama` not ready |
| `*.404.json`, `*.409.json`, `*.422.json` | An error envelope with that HTTP status |

## What's real

The `goblin-bribe` results for `decision-1@foundry` and `clef-flash@workers-ai` are real responses to the plan's request. The Workers AI one shows Clef-flash's own confidence formula: its `server_confidence` for `intent` differs from jevtester's `confidence`. The other answers are made up, but consistent across files. Every run fixture comes from a real pass through the runner and the evaluation code with fake providers: the `parley` suite has four cases and one Claude draft, run `0001` asked an older question set version without the `wait` option, and run `0002` asked the plan's questions on three targets with `0001` as its baseline. Run `0003` is a real probe run whose fake targets are fragile to option order where evade and wait are close, and, on Workers AI, to bare-number score levels. Run `0004` is a cancelled run, stored as a summary. The fixtures ask the plan's questions, whatever `suites/question-sets/parley.yaml` has become.

The policy fixtures use `suites/policies/parley.yaml`.
