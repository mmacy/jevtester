# API fixtures

One saved response for each route in [the API contract](../../../docs/api.md), for the UI's fixture mode and the contract tests. [`tests/api_fixtures.py`](../../api_fixtures.py) builds every file here from the API models. Don't edit them by hand. After a change, regenerate them:

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

The `goblin-bribe` results for `decision-1@foundry` and `clef-flash@workers-ai` are real responses to the plan's request. The Workers AI one shows Clef-flash's own confidence formula: its `server_confidence` for `intent` differs from jevtester's `confidence`. Every other answer, metric, and run is made up, but consistent across files: the `parley` suite has four cases and one Claude draft, run `0142` ran it on three targets with run `0141` as its baseline, `0143` is a probe run in progress, and `0144` was cancelled. Real responses replace the made-up ones as each target goes live.

The policy YAML is a placeholder. The policy format arrives in build step 7.
