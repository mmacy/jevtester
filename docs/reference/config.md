# Configuration reference

jevtester reads one TOML config file. It lists the *targets*, the decision models jevtester can send requests to, with their limits and prices, and sets the defaults that commands and API requests fall back on. A target is one model on one runtime, like `decision-1@foundry`.

The config contains no credentials. Foundry uses the `az` sign-in, and Workers AI uses the Wrangler sign-in or `CLOUDFLARE_API_TOKEN`. See [Credentials](#credentials).

For the steps to add a target or point jevtester at your own resources, see the [how-to guides](../how-to.md). For what targets and capabilities are for, see [Concepts](../concepts.md#targets).

## Where jevtester looks for the config

jevtester uses the first of these that applies:

1. The path in `--config PATH`, on any [CLI](cli.md) command. jevtester reads only that file.
2. The path in the `JEVTESTER_CONFIG` environment variable. jevtester reads only that file.
3. `jevtester.toml` in the working directory, with `jevtester.local.toml` there merged over it when that file exists. When only `jevtester.local.toml` exists, jevtester reads it alone.

The repository's `jevtester.toml` contains placeholders. To use your own Foundry resource or Cloudflare account, put your values in `jevtester.local.toml`, which git ignores. The tests keep reading `jevtester.toml`.

jevtester deep-merges the local file over the shared one:

- Where both files have a table, like `[defaults]` or `[targets."decision-1@foundry"]`, jevtester merges the tables key by key.
- Where both files have any other value, the local file's value wins. An array isn't merged: `defaults.targets` in the local file replaces the shared list.
- A table or key only in one file is kept.

So your local file needs only what you change, and a target added to `jevtester.toml` later appears in your config too. This local file sets a Foundry resource and a Cloudflare account, and leaves every other setting as `jevtester.toml` has it:

```toml
[cloudflare]
account_id = "<your Cloudflare account ID>"

[targets."decision-1@foundry"]
base_url = "https://<your resource>.services.ai.azure.com/providers/microsoft"
```

Paths in the config, `paths.suites` and `paths.store`, are relative to the config file's directory, not the working directory.

## Validation

jevtester validates the whole config when a command starts, and when `jevtester serve` starts. When it merges `jevtester.local.toml` over `jevtester.toml`, it validates the merged result. An invalid config stops the command with exit code 2 and one line per error. With `timeout_s = 0` and `repeats = 0` under `[defaults]` in `bad.toml`:

```console
$ jevtester --config bad.toml targets list
jevtester: The config is invalid:
defaults.timeout_s: Input should be greater than 0
defaults.repeats: Input should be greater than or equal to 1
```

The rules that apply to every table:

- A key the format doesn't have is an error, like `timeout` in place of `timeout_s`. The error reads `Extra inputs are not permitted`.
- A file that can't be read stops the command with `jevtester: Can't read <path>:` and the reason, like `No such file or directory`.
- A file that isn't valid TOML stops the command with `jevtester: <path> isn't valid TOML:` and the line and column of the error.
- A file that isn't UTF-8 text stops the command with `jevtester: <path> isn't UTF-8 text:` and the position of the first bad byte.

## Example

This is a shortened copy of the repository's `jevtester.toml`, with one target on each runtime:

```toml
[defaults]
targets = ["decision-1@foundry"]
timeout_s = 60.0
repeats = 1

[cloudflare]
# account_id = "<your Cloudflare account ID>"

[targets."decision-1@foundry"]
label = "Microsoft-Decision-1, Azure Foundry"
provider = "systemone"
runtime = "foundry"
model = "decision-1"
base_url = "https://example-resource.services.ai.azure.com/providers/microsoft"
auth = "azure-cli"

[targets."decision-1@foundry".capabilities]
probabilities = true
max_questions = 64
concurrency = 8
requests_per_minute = 100
tokens_per_minute = 100_000

[targets."clef-flash@ollama"]
label = "Clef-flash, Ollama"
provider = "systemone"
runtime = "ollama"
model = "clef-flash"
base_url = "http://localhost:11434"

[targets."clef-flash@ollama".capabilities]
probabilities = true
max_questions = 64
min_options = 2
max_options = 26
max_request_bytes = 65_536
concurrency = 1

[targets."clef-flash-4bit@mlx"]
label = "Clef-flash 4-bit, MLX"
provider = "systemone"
runtime = "mlx"
model = "clef-flash-4bit"
base_url = "http://127.0.0.1:8000"
truncate = false

[targets."clef-flash-4bit@mlx".capabilities]
probabilities = true
context_window = 16_384
concurrency = 1
concurrency_group = "mlx"

[targets."clef-flash@workers-ai"]
label = "Clef-flash, Workers AI"
provider = "workers-ai"
runtime = "workers-ai"
model = "clef-flash"

[targets."clef-flash@workers-ai".capabilities]
probabilities = true
images = true
max_images = 4
context_window = 24_576
truncates_state = true
concurrency = 4
input_cost_per_mtok_usd = 0.038
```

## `[defaults]`

Values that commands and API requests use when you don't set a value.

| Key | Type | Default | Description |
|---|---|---|---|
| `targets` | list of strings | `[]` | The targets a request or run goes to when you don't name any, in order. Each name must be a key in [`[targets]`](#targets). A suite's `targets` take precedence for a run. |
| `timeout_s` | float | `60.0` | Seconds to wait for each target's answer. Greater than 0. `jevtester decide --timeout` and the decide request's `timeout_s` override it. Runs always use it. |
| `repeats` | integer | `1` | Times a run sends each case to each target. At least 1. `jevtester run --repeats` and the run request's `repeats` override it. |
| `max_drop` | float | `0.05` | The largest drop in accuracy, or in within-tolerance accuracy for a score question, that [`jevtester compare`](cli.md#jevtester-compare) allows before it reports a regression and exits with 1. At least 0. `--max-drop` overrides it. |

A name in `targets` that isn't a configured target is an error:

```text
jevtester: The config is invalid:
input: Value error, defaults.targets names unknown targets: nope
```

## `[paths]`

Where jevtester keeps its files. Both paths are relative to the config file's directory.

| Key | Type | Default | Description |
|---|---|---|---|
| `suites` | string | `"suites"` | The suites directory. Question sets are in its `question-sets/` directory, and policies in its `policies/` directory. The [suite format reference](suite-format.md) describes the files. |
| `store` | string | `".jevtester/runs.sqlite"` | The SQLite database of runs, results, the result cache, and question set versions. jevtester creates it on first use. Deleting it deletes every run and the cache. |

## `[cloudflare]`

Account settings for Workers AI targets.

| Key | Type | Default | Description |
|---|---|---|---|
| `account_id` | string | none | Your Cloudflare account ID. Without it, Workers AI targets are down, and their health check reports `No Cloudflare account`. Set it in `jevtester.local.toml`, not in `jevtester.toml`. |

## `[targets]`

Each target is a table named `[targets."<name>"]`. The table key is the target's name, so don't repeat it inside the table. A name is any string, and the repository uses `<model>@<runtime>`, like `clef-flash@ollama`. You name targets by it in commands, requests, and suites. Every list of targets is in the file's order.

| Key | Type | Default | Description |
|---|---|---|---|
| `label` | string | required | The name people read, like `Clef-flash, Ollama`. The web UI shows it. |
| `provider` | string | required | The provider that sends the target its requests. See [Providers](#providers). |
| `model` | string | required | The model name sent in each request body. On Foundry, it's the deployment name. |
| `runtime` | string | none | The server the target runs on: `foundry`, `ollama`, `mlx`, or `workers-ai`. It picks the health check. See [Runtimes](#runtimes). |
| `base_url` | string | none | The API root of a System One server. Required when `provider` is `systemone`: without it, the config is invalid. The provider adds `/v1/systemone`. A host of `localhost`, `127.0.0.1`, or `::1` makes the target *local*, which the target list shows in its `local` field. It doesn't change the cost, which comes from `input_cost_per_mtok_usd`. |
| `auth` | string | none | How the provider gets a credential. The one method is `azure-cli`, for Foundry. Leave it out for a server without authentication, and for Workers AI, which uses the Wrangler sign-in. See [Credentials](#credentials). |
| `truncate` | boolean | none | The `truncate` field to send, for servers that accept it, like the MLX server. Leave it out to send nothing. `true` lets the server cut the input to fit its context window without an error, and gives the target a `truncation_on` warning. The MLX targets in `jevtester.toml` set it to `false`. |
| `capabilities` | table | see [Capabilities](#capabilities) | What the target accepts and returns. |

### Providers

| `provider` | Reaches | Needs |
|---|---|---|
| `systemone` | Any server that speaks the System One API: Foundry, Ollama, and the MLX server. | `base_url`. `auth = "azure-cli"` for Foundry. |
| `workers-ai` | Cloudflare Workers AI. | `cloudflare.account_id`, and a Cloudflare token. `base_url` and `auth` aren't used. |
| `claude` | Not built yet. A target with this provider is down, with the reason `The claude provider isn't built yet`, and never answers. | |

Any other value is an error, like `targets.x.provider: Input should be 'systemone', 'workers-ai' or 'claude'`.

### Runtimes

The runtime picks a target's health check, which [`jevtester targets check`](cli.md#jevtester-targets-check) runs. A health check sends no decision request.

| `runtime` | Ready when |
|---|---|
| `foundry` | `base_url` names your resource, not the placeholder `example-resource`. A token can be read from the `az` sign-in, and the endpoint answers a GET of `base_url`. The GET carries no token and reaches no model, so it costs nothing. Any HTTP response counts, so the check catches a placeholder or a resource name that doesn't exist, but not a wrong deployment name. |
| `ollama` | Ollama answers at `base_url`, is version 0.35.1 or later, and has the model pulled. |
| `mlx` | The MLX server answers at `base_url` and has the target's model loaded. A decide request checks the loaded model again before it sends, because the server answers with whatever model it loaded. |
| `workers-ai` | `cloudflare.account_id` is set, a token can be read, and the account's Workers AI catalog lists the model. |
| none | A `systemone` target with `auth` is ready when a token can be read. Without `auth`, it's ready when its server answers at `base_url`. |

A `workers-ai` target always gets the Workers AI check, whatever its `runtime`.

### Capabilities

`[targets."<name>".capabilities]` says what a target accepts and returns. Before jevtester sends a request, its *preflight* check compares the request with these limits. A request that breaks a limit isn't sent, and its result has the error code `preflight`. A limit left out is unknown, so preflight doesn't check it.

| Key | Type | Default | Description |
|---|---|---|---|
| `probabilities` | boolean | `true` | Whether the target returns a probability for every option. Calibration metrics leave out a target without them. |
| `question_types` | list of strings | `["noul", "choice", "score"]` | The question types the target accepts. Preflight rejects a request with any other type. |
| `max_questions` | integer | none | The most questions one request may have. |
| `min_options` | integer | none | The fewest options or levels a choice or score question may have. |
| `max_options` | integer | none | The most options or levels a choice or score question may have. |
| `max_request_bytes` | integer | none | The largest request body the target accepts, in bytes of JSON. |
| `context_window` | integer | none | The input limit in tokens. See [Context window](#context-window). The `pad_state` probe needs it. |
| `truncates_state` | boolean | `false` | Whether the server cuts the state to fit its context window without an error. `true` gives the target a `state_may_truncate` warning. |
| `images` | boolean | `false` | Whether the target accepts images. Preflight rejects a request with images when it's `false`. |
| `max_images` | integer | none | The most images one request may have. |
| `max_image_bytes` | integer | none | The largest image, in bytes. Preflight rejects a request with a larger image. |
| `max_total_image_bytes` | integer | none | The largest total size of a request's images, in bytes. Preflight rejects a request whose images add up to more. |
| `image_formats` | list of strings | `[]` | The image formats the target accepts: `png`, `jpeg`, or `webp`. Preflight rejects a request with an image in another format. Empty means any format. |
| `concurrency` | integer | `1` | How many requests a run may have in flight to the target at once. At least 1. |
| `concurrency_group` | string | none | Targets with the same group share one concurrency limit, like several models on one MLX server. The limit is the `concurrency` of whichever target in the group sends first, so give every target in a group the same `concurrency`. |
| `requests_per_minute` | integer | none | The most requests a run starts per minute on the target. A run spaces its requests to stay under it. |
| `tokens_per_minute` | integer | none | The most input tokens a run sends per minute to the target, by preflight's [token estimate](#context-window). A run spaces its requests to stay under it. |
| `input_cost_per_mtok_usd` | float | none | The cost of one million input tokens, in US dollars. Output tokens are free on every current target. Without it, each result's `cost_usd` is unknown. |

`concurrency`, `concurrency_group`, `requests_per_minute`, and `tokens_per_minute` apply to runs. A decide request sends one request to each target, so it doesn't use them.

#### Context window

Preflight estimates a request's tokens as the size of its JSON body in bytes, divided by 4. When the estimate is over `context_window`:

- A target with `truncates_state = true` or `truncate = true` gets the request, with a `state_may_truncate` warning on the result.
- Any other target gets the request when the estimate is at most 25% over the window. A request more than 25% over isn't sent.

#### Rate limits

A run waits before each request it sends to stay under `requests_per_minute` and `tokens_per_minute`. For `tokens_per_minute`, each request uses the same estimate as the context window check, and delays the next request to the target by its share of a minute. A request of 2,000 estimated tokens to a target with `tokens_per_minute = 100_000` delays the next one by 1.2 seconds. The estimate leaves out images.

#### Images

Preflight checks `max_image_bytes`, `max_total_image_bytes`, and `image_formats` by reading each image file at its path as given, relative to the directory you run jevtester from. It recognizes a format from the file's first bytes, not its name. A request with an image file that can't be read isn't sent, when the target sets any of these three limits.

## Credentials

The config never holds a credential. jevtester reads each one when it needs it, and never prints or logs it.

| Credential | Used by | Where jevtester gets it |
|---|---|---|
| Azure token | Targets with `auth = "azure-cli"`, like Foundry | The Azure CLI sign-in, through `azure-identity`. Run `az login` first. jevtester doesn't use Foundry API keys. |
| Cloudflare token | `workers-ai` targets | `CLOUDFLARE_API_TOKEN` when it's set and not empty. Otherwise the Wrangler sign-in, from `npx --no-install wrangler auth token --json`, read again every 10 minutes. Run `npx wrangler login` first. |

A target's `credential` in [`jevtester targets check`](cli.md#jevtester-targets-check) shows where its token came from, like `Azure CLI, refreshes in 41 min`. When a token can't be read, the health check marks the target down with `Can't get a token` and says what to run.

## Environment variables

| Variable | Effect |
|---|---|
| `JEVTESTER_CONFIG` | The config file to read when `--config` isn't given. See [Where jevtester looks for the config](#where-jevtester-looks-for-the-config). |
| `CLOUDFLARE_API_TOKEN` | The Cloudflare token for Workers AI targets. It takes precedence over the Wrangler sign-in. |
