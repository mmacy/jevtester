# jevtester

A local web app and CLI for testing decision models like Microsoft-Decision-1 and Cloudflare's Clef. It compares the models, the questions you write for them, and the decisions your code makes from their answers. For the design, see [the plan](docs/plan.md).

## Requirements

- Python 3.14 and [uv](https://docs.astral.sh/uv/).
- Node 24 or later, to build the web UI.
- At least one target you can reach:
  - Microsoft-Decision-1 on your own Azure AI Foundry resource, with the Azure CLI signed in (`az login`).
  - Clef on Cloudflare Workers AI in your own Cloudflare account, with Wrangler signed in (`npx wrangler login`) or `CLOUDFLARE_API_TOKEN` set.
  - Clef-flash on a local Ollama or MLX server.

## Set up

1. Install the Python dependencies:

   ```sh
   uv sync
   ```

2. Copy the shared config to a local one. Git ignores `jevtester.local.toml`, and jevtester reads it instead of `jevtester.toml` when it exists.

   ```sh
   cp jevtester.toml jevtester.local.toml
   ```

3. In `jevtester.local.toml`, set your own resources:

   - For Foundry, replace `example-resource` in the `decision-1@foundry` target's `base_url` with your Foundry resource name. The target's `model` is your deployment name.
   - For Workers AI, uncomment `account_id` under `[cloudflare]` and set your Cloudflare account ID.
   - Set `targets` under `[defaults]` to the targets you use.

4. Build the web UI:

   ```sh
   cd web
   npm install
   npm run build
   ```

   The build writes to `src/jevtester/static/`, which git ignores.

To use a different config file, pass `--config <path>` or set `JEVTESTER_CONFIG`.

## Run it

```sh
uv run jevtester targets check
uv run jevtester decide --state "Six goblins block the stairs." --question "Are the goblins hostile?"
uv run jevtester run suites/parley.yaml
uv run jevtester serve
```

`jevtester serve` starts the API and the web UI at <http://127.0.0.1:8640>.

## Test it

```sh
uv run ruff format --check
uv run ruff check
uv run pyright
uv run pytest
```

`uv run pytest` skips the tests that call real targets. To run them, use `uv run pytest -m live` from the repository root. They read your `jevtester.local.toml`. The web UI's checks are in [`web/README.md`](web/README.md).

## Docs

- [The plan](docs/plan.md): what jevtester does and how it's built.
- [The API](docs/api.md): the routes, the result format, run events, evaluation, policies, and probes. [`docs/openapi.json`](docs/openapi.json) is the full schema.
- [The UI plan](docs/ui-plan.md): the web UI's views.

## License

This repository is licensed under [CC BY-NC-SA 4.0](LICENSE).
