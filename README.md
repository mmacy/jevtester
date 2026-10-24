# jevtester

A local web app and CLI for testing decision models like Microsoft-Decision-1 and Cloudflare's Clef. It compares the models, the questions you write for them, and the decisions your code makes from their answers. For the design, see [the plan](docs/plan.md).

## Run it

jevtester needs Python 3.14 and uv. Foundry targets use the `az` sign-in, and Workers AI targets use the Wrangler sign-in or `CLOUDFLARE_API_TOKEN`. `jevtester.toml` lists the targets.

```sh
uv sync
uv run jevtester targets check
uv run jevtester decide --state "Six goblins block the stairs." --question "Are the goblins hostile?"
uv run jevtester run suites/parley.yaml
uv run jevtester serve
```

`jevtester serve` starts the API and the web UI at <http://127.0.0.1:8640>. Build the UI first with `npm run build` in `web/`.

## Docs

- [The plan](docs/plan.md): what jevtester does and how it's built.
- [The API](docs/api.md): the routes, the result format, run events, evaluation, policies, and probes. [`docs/openapi.json`](docs/openapi.json) is the full schema.
- [The UI plan](docs/ui-plan.md): the web UI's views.
