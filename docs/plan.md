# jevtester plan

jevtester is a local web app and companion command-line tool (CLI) for testing *decision models*: models that read a state and a set of typed questions and return a probability for every allowed answer, instead of generating text. It tests three things at once: the models, the questions you write for them (the prompts), and the decisions your code makes from their answers.

Two Claude Code sessions build jevtester in parallel. A backend session builds the core library, the CLI, and the HTTP API, and a frontend session builds the web UI against the API contract. [The handoff notes](handoff.md) describe how they split the work.

Two terms are used throughout:

- An *answer* is what a model returns for one question: a probability, a chosen option, or a score.
- A *decision* is the action your code takes from one or more answers, like "parley succeeds" or "escalate to the referee".

## What the app must do

- Run a test from two inputs, a state and a question, with every other field defaulted. A question with no options becomes a yes/no question.
- Scale the same test up to a full comparison: many cases, several question set versions, several models, repeats, robustness probes, and a decision policy. Let a person promote a quick test to a saved case without entering anything again.
- Support all three question types (`noul`, `choice`, and `score`) on every target that accepts them.
- Compare local and hosted models side by side on the same requests.
- Measure answer quality, calibration, latency, and cost, and measure decision quality separately from answer quality.
- Give agents and scripts the same capabilities as the UI through the CLI, with JSON output.
- Run on `127.0.0.1` only. Keep API keys and tokens on the server, never in the browser.

## Decision models and the System One API

Every decision model jevtester targets accepts the same request format, called the *System One API*. A request has a `model`, a `state` (text or JSON), and up to 64 `questions` keyed by an id you choose. Each answer comes back under its question's id. According to TypeSafe's docs, the id isn't sent to the model, so put everything the model needs in `instructions`.

```json
{
  "model": "decision-1",
  "state": {
    "party": "Three adventurers, torches lit",
    "monsters": "Six goblins, weapons drawn, 40 feet away",
    "player_says": "We come in peace. Take this sack of silver and let us pass to the stairs."
  },
  "questions": {
    "intent": {
      "type": "choice",
      "instructions": "What is the player trying to do?",
      "criteria": {
        "parley": "Talk, bargain, bribe, or negotiate",
        "evade": "Run away or avoid the monsters",
        "fight": "Attack the monsters",
        "wait": "Hold position and watch"
      }
    },
    "bribe": {
      "type": "noul",
      "instructions": "Does the player offer the monsters something of value?"
    },
    "reaction": {
      "type": "score",
      "instructions": "How are goblins likely to react to this offer?",
      "criteria": [
        "Attack at once",
        "Hostile, may attack",
        "Uncertain, hold and posture",
        "Indifferent, may let them pass",
        "Friendly, accept the offer"
      ]
    }
  }
}
```

Microsoft-Decision-1 returns this response to that request, in about 1.5 seconds. It's the first test fixture.

```json
{
  "model": "microsoft-decision-1",
  "answers": {
    "bribe": {"noul": 0.9988304895647238, "type": "noul"},
    "intent": {
      "choice": "parley",
      "confidence": 0.9994862537938526,
      "probabilities": {
        "evade": 0.0001794909415287629,
        "fight": 6.603102726493733e-05,
        "parley": 0.9996146903453894,
        "wait": 0.00013978768581682428
      },
      "type": "choice"
    },
    "reaction": {
      "confidence": 0.32291261419799433,
      "legend": {
        "0": "Attack at once",
        "1": "Hostile, may attack",
        "2": "Uncertain, hold and posture",
        "3": "Indifferent, may let them pass",
        "4": "Friendly, accept the offer"
      },
      "probabilities": {
        "0": 0.03320131848053559,
        "1": 0.1910603961750086,
        "2": 0.4583300913583954,
        "3": 0.16861020783103078,
        "4": 0.14879798615502957
      },
      "score": 2.20874314700501,
      "type": "score"
    }
  },
  "usage": {"input_tokens": 185, "output_tokens": 3}
}
```

The three question types:

- **`noul`** - a yes/no question. The answer is the probability of yes. Some servers accept optional `criteria` with `true` and `false` descriptions.
- **`choice`** - pick one option from a map of option names to descriptions. The answer has the chosen option, a probability for each option, and a `confidence`.
- **`score`** - place the state on an ordered list of levels, lowest first. The answer has `score` (the probability-weighted level index, so it can fall between levels), a probability for each level, a `legend`, and a `confidence`.

`confidence` describes how concentrated the probabilities are, not whether the answer is correct. TypeSafe documents the formula for a choice as `(p_max - 1/n) / (1 - 1/n)`, and for a noul as `|2p - 1|`. Compute those two yourself so jevtester compares every target on the same measure. For a score, store the server's value, because the TypeSafe docs describe the score formula only in words.

The vendors give this guidance for writing questions. The app's question checks should test for it:

- Ask about one dimension per question. Combine dimensions in code, with weights.
- Describe concrete situations in criteria, not degrees like "moderately severe". Score levels that are only numbers (`"0"`, `"1"`, `"2"`) perform poorly, because the model sees the descriptions and not the level numbers.
- Make choice options mutually exclusive. Offer an abstention option like "cannot tell" when a forced choice would be wrong.
- Answers can change with the wording and order of options. Ollama documents that ties go to the first-listed option.
- Probabilities differ between models, so tune thresholds separately for each model.

## Environment

| Item | Requirement |
|---|---|
| Tools | Python 3.14, uv, and Node 24 or later. |
| Ollama | Clef-flash needs Ollama 0.35.1 or later. |
| Azure | A Foundry resource with a deployment of Microsoft-Decision-1, and an Azure CLI sign-in. |
| Cloudflare | A Wrangler sign-in with the `ai (write)` scope. |
| Anthropic | Out of scope: jevtester builds without Claude. |
| TypeSafe | Out of scope: TypeSafe's hosted decision model, Jev, needs an OpenRouter key. |

## Targets

A *target* is one model on one runtime, with its settings. The plan supports these targets:

| Target | Runtime | Endpoint | Client | Needs |
|---|---|---|---|---|
| Microsoft-Decision-1 | Azure Foundry | `https://<your Foundry resource>.services.ai.azure.com/providers/microsoft/v1/systemone`, `"model": "decision-1"` | TypeSafe SDK | An Azure CLI sign-in |
| Clef-flash | Ollama, local | `http://localhost:11434/v1/systemone` | TypeSafe SDK | Ollama 0.35.1 or later and a model pull (11-12 GB) |
| Clef-flash, 4-bit or 8-bit | MLX, local | `http://127.0.0.1:8000/v1/systemone` from `python clef_mlx.py serve` | TypeSafe SDK | A model download |
| Clef (27B), 8-bit | MLX, local | Same server, a different model | TypeSafe SDK | A model download (peak memory about 31-33 GB) |
| Clef, Clef-flash, Clef-omni | Cloudflare Workers AI | `https://api.cloudflare.com/client/v4/accounts/<account>/ai/run/@cf/cloudflare/<model>`, with `"model": "<model>"` in the body | jevtester's adapter | A Wrangler sign-in |
| Claude | Anthropic API | Messages API | `anthropic` SDK | An API key |

### TypeSafe SDK

Use `typesafe-sdk` (Python, MIT license, version 0.7.x) for every target that serves `/v1/systemone`. It has sync and async clients, the `Noul`, `Choice`, `Score`, and `Box` question classes, typed answers, error classes, and retries. It appends `/v1/systemone` to `base_url`, sends `api_key` as `Authorization: Bearer`, and puts the raw HTTP response on `response.raw_http_response`.

Four behaviors affect jevtester:

- **Compression.** On Python 3.14 the SDK compresses request bodies of 1 KB or more with zstd by default. Foundry rejects those requests with `400 ... Request body could not be parsed as JSON`. Always construct the client with `compression=False`.
- **Strict parsing.** The response models validate strictly. If a server returns a slightly different answer format, parsing fails. Fall back to parsing `raw_http_response` and record the failure.
- **Images.** The SDK sends images as named `assets` referenced from the state. Clef on Workers AI expects an `images` array. Send image requests to Clef servers as direct HTTP until you've confirmed what each server accepts.
- **Version.** The SDK is at 0.x. Wrap it in one module, so a breaking release means changing only one file.

A call to Foundry:

```python
from azure.identity import AzureCliCredential
from typesafe_sdk import Choice, TypeSafeClient

token = AzureCliCredential().get_token("https://cognitiveservices.azure.com/.default").token
with TypeSafeClient(
    api_key=token,
    base_url="https://example-resource.services.ai.azure.com/providers/microsoft",
    compression=False,
) as client:
    response = client.system_one(
        state="The goblins draw their weapons.",
        questions={"intent": Choice(instructions="What do the goblins do?", criteria={"attack": "Charge the party", "parley": "Shout a demand"})},
        model="decision-1",
    )
print(response.choices["intent"].choice)
```

### Target notes

- **Foundry.** The Foundry resource used here has API keys disabled, so authenticate with Entra ID. Request a token for the scope `https://cognitiveservices.azure.com/.default` through `azure-identity`, and refresh it before it expires (tokens last about an hour). The request's `model` is the deployment name. The response's `model` is the underlying model name, `microsoft-decision-1`. Microsoft-Decision-1 is in preview, and its catalog entry shows inference retiring on 2027-02-04. It's built on Qwen3.5-9B, the same base model as Clef-flash.
- **Ollama.** Ollama's library page lists 1-64 questions per request and 2-26 options or levels, and Pydantic AI's docs list a 64 KiB request limit. Decision models aren't available in the Ollama CLI or its client libraries, only over HTTP.
- **MLX.** Use `mlx-community/clef-flash-4bit`, `clef-flash-8bit`, or `clef-8bit`, with the `clef_mlx.py` loader included in the model repository on Hugging Face. The loader is confirmed for `clef-8bit`, so check that the flash builds include it too. Install its dependencies with `pip install "mlx-vlm>=0.7.4,<0.8" huggingface_hub`. Generic MLX tools and LM Studio load the backbone and produce meaningless text. The server binds to `127.0.0.1`, has no authentication, and handles one request at a time. By default it truncates input at 16,384 tokens without telling you. Start it with `--no-truncate`, or send `"truncate": false` in a request body, and a long input returns HTTP 413 instead. `--max-length` changes the token limit. The server adds `latency_ms` to `usage`. The loader is custom Python code. The reviewed `clef-flash-4bit` copy imports only the standard library, MLX, mlx-vlm or mlx-lm, Pillow, and `huggingface_hub`, and it fetches `http(s)` image URLs sent in requests. The repository also contains a compiled `__pycache__/clef_mlx.cpython-312.pyc`. Delete it so Python runs the reviewed source.
- **GGUF builds.** Community GGUF quantizations of Clef don't include the decision head (the part that scores options), so llama.cpp and LM Studio generate text instead of answers. Don't add them as targets.
- **Workers AI.** The request body is the System One body. The response wraps the System One response in a Cloudflare envelope (`{"result": {...}, "success": true, "errors": [], "messages": []}`). Unwrap `result` and validate it with the SDK's `SystemOneResponse` model so the answer types match every other target. Clef-flash rounds probabilities to four decimal places and reports `output_tokens` as 0. For authentication, run `npx wrangler auth token --json` and read its `token` field. The token is short-lived, so get a new one when a request returns 401. Let `CLOUDFLARE_API_TOKEN`, when it's set, take the place of the Wrangler token. The Clef-flash model page lists a 24,576-token context window and says the server truncates `state` to fit, while the launch changelog says 64K. Images go in an `images` array: at most 4, PNG, JPEG, or WebP, 4 MiB each, 8 MiB in total. Input costs $0.038 per million tokens for Clef-flash, and output is free.
- **Claude.** Claude isn't a decision model, and the Messages API returns no token probabilities. Use it as a text-reasoning baseline: send each question with structured outputs constrained to the allowed options, and record the answer with no probabilities. On current models, the API returns a 400 for sampling parameters, so don't try to estimate a distribution by sampling repeatedly. Exclude Claude targets from calibration metrics. Use `claude-opus-5-5` unless the user names another model.

## Architecture

```text
jevtester/
  src/jevtester/
    spec/        Question, QuestionSet, Case, Suite, Policy, Target models
    providers/   DecisionProvider protocol and the SystemOne, WorkersAI, and Claude providers
    normalize/   canonical answers and recomputed confidence
    preflight/   per-target limit checks and token estimates
    runner/      job expansion, concurrency, caching, repeats
    evaluate/    scorers, metrics, comparisons, probes
    policy/      decision rules, threshold sweeps, error costs
    assist/      Claude-generated cases, labels, critiques, and paraphrases
    states/      state builders for RPG data
    store/       SQLite runs and file-based suites
    service.py   the operations the CLI and the API both call
    cli.py       the companion CLI
    api.py       the FastAPI app
  suites/        suites and question sets as YAML, in git
  tests/
```

The CLI and the API are thin layers over `service.py`. Put every operation there first, so the UI, the CLI, and agents can all do the same things.

Use Python 3.14 with uv, pydantic v2, FastAPI, SQLite, `typesafe-sdk`, `httpx2` (already a dependency of the SDK) for the Workers AI adapter, `azure-identity`, and `anthropic`. The gates (the checks that must pass) are `ruff format --check`, `ruff check`, `pyright`, and `pytest`.

### Data model

One data model covers the quick test and the full comparison. Every field except the state and one question has a default from the config.

```python
class NoulQuestion(BaseModel):
    type: Literal["noul"] = "noul"
    instructions: str
    criteria: dict[Literal["true", "false"], str] | None = None


class ChoiceQuestion(BaseModel):
    type: Literal["choice"] = "choice"
    instructions: str
    criteria: dict[str, str]


class ScoreQuestion(BaseModel):
    type: Literal["score"] = "score"
    instructions: str
    criteria: list[str]


Question = Annotated[NoulQuestion | ChoiceQuestion | ScoreQuestion, Field(discriminator="type")]


class QuestionSet(BaseModel):
    name: str
    questions: dict[str, Question]
    # The content hash identifies a version. Runs record it.


class Expectation(BaseModel):
    answer: bool | str | int | None = None    # noul, choice, or score level
    acceptable: list[str | int] | None = None  # other answers that count as correct
    tolerance: int = 0                         # score levels of slack


class Case(BaseModel):
    id: str
    state: str | dict | list
    images: list[str] = []                     # file paths
    expected: dict[str, Expectation] = {}      # keyed by question id
    expected_action: str | None = None         # for policy tests
    tags: list[str] = []
    provenance: str = "human"                  # "human", or "claude-draft" until approved


class Target(BaseModel):
    name: str                                  # for example "decision-1@foundry"
    provider: Literal["systemone", "workers-ai", "claude"]
    model: str
    base_url: str | None = None
    settings: dict = {}
```

A `Suite` lists cases, a question set, an optional policy, and default targets. A `Run` records the suite, the question set hash, the policy hash, the targets, and one `Result` per case, target, and repeat. Each result contains the exact request and response bodies, the canonical answers, latency, token usage, cost, truncation warnings, and any error.

### Providers

```python
class DecisionProvider(Protocol):
    capabilities: Capabilities

    async def decide(self, request: DecisionRequest, *, timeout: float) -> RawResult: ...

    async def health_check(self) -> str | None:
        """Return None when the target is ready, otherwise the reason it isn't."""
```

`Capabilities` records whether the target returns probabilities, whether it accepts images, its context window, its question, option, and level limits, its concurrency limit, and its cost per million input tokens. Preflight and the runner read it.

- **SystemOne** - a `TypeSafeClient` for each base URL, with `compression=False`. It covers Foundry, Ollama, MLX, and any later System One server. For Foundry, it gets a fresh Entra token before the current one expires.
- **WorkersAI** - an `httpx2` call to `/ai/run/@cf/cloudflare/<model>` with a bearer token from the Wrangler sign-in, or from `CLOUDFLARE_API_TOKEN` when it's set. It unwraps the envelope and validates the result with `SystemOneResponse`.
- **Claude** - one Messages API call per request, with a structured-output schema that has one enum property per question: the option names for a choice, `true` or `false` for a noul, and the level indexes for a score. It returns answers with `probabilities` set to `None`.

Follow the pattern of `NarrativeProvider` in [osr-web](https://github.com/mmacy/osr-web)'s `server/llm.py`: a protocol, stateless implementations, and a health check that reports why a target is unavailable.

### Normalizer

Map every response to one canonical answer per question. Recompute choice and noul confidence with the formulas above, and store the server's value next to it. Store the raw response too. Flag any answer whose chosen option isn't one of the question's options.

### Preflight

Check each request against the target's capabilities before sending it:

- The number of questions, and the number of options or levels in each question.
- Image count, format, and size.
- An estimated token count against the context window.

Report silent truncation as a warning on the result: Workers AI truncates `state` to fit, and the MLX server truncates at 16,384 tokens unless you turn truncation off. Reject requests that would fail, before they cost anything.

### Runner

- Expand a run into jobs, one for each combination of case, question set version, target, and repeat.
- Respect each target's concurrency limit and rate limit. The MLX server handles one request at a time, and the Foundry deployment's rate limit depends on its capacity.
- Cache results by a hash of the target and the request body, so a rerun of an unchanged job costs nothing. Add a flag that bypasses the cache.
- Retry with backoff on 429 and 5xx responses.
- Report progress as events that the CLI prints and the API streams over server-sent events (SSE).
- Support cancellation.

### Evaluation

Score each answer against its expectation, then aggregate:

- **Choice** - accuracy, macro-F1 (F1 averaged across options, so rare options count equally), and a confusion matrix.
- **Score** - mean absolute error in levels, and accuracy within the tolerance.
- **Noul** - accuracy at a threshold, Brier score, log loss, and AUROC (how well the probability ranks true cases above false ones).
- **Calibration** - a reliability table and expected calibration error, for targets that return probabilities.
- **Abstention** - how often the target chose the abstention option, reported separately from accuracy.
- **Consistency** - for repeats, whether the same request returns the same answers and probabilities.
- **Latency and cost** - p50 and p95 latency, and cost per 1,000 requests.

Comparisons:

- **Question set A/B** - run two question set versions on the same cases and list each case whose answer changed, with McNemar's test for the paired difference.
- **Target comparison** - the same metrics for each target, plus the cases where targets disagree.
- **Regression check** - compare a run with a saved baseline run and fail when a metric drops by more than a configured amount.

### Probes

A probe generates variants of each case and measures how often the answer changes:

- Shuffle the order of choice options.
- Reorder the keys of a JSON state.
- Replace score level descriptions with bare numbers.
- Pad the state toward the target's context window.
- Paraphrase the instructions (with Claude, when an API key is set).

### Decision policy

A policy turns answers into a decision. Write it in YAML:

- Confidence bands for each question: act, confirm, or escalate.
- Composite scores: weighted sums of normalized answers.
- Rules that choose an action from answers and composite scores.

Cases can include an `expected_action`. The evaluator reports decision accuracy, the share of cases the policy decided without escalating, and the error rate among those. A threshold sweep plots the share decided and the error rate as a threshold moves. A cost matrix weights each kind of error (for example, a wrong "parley succeeds" costs more than an unneeded escalation). Store thresholds per target, since probabilities differ between models. A Python hook lets a policy call real game code later.

### Assist

When `ANTHROPIC_API_KEY` is set, Claude can:

- Generate cases, including edge cases and cases near a decision boundary.
- Draft expected answers.
- Check question wording against the guidance in [Decision models and the System One API](#decision-models-and-the-system-one-api).
- Write paraphrases for probes.
- Suggest why two targets disagree on a case, since decision models return no reasoning.

Save everything Claude produces with `provenance: "claude-draft"`. Evaluation ignores it until a person approves it.

### State builders

A state builder turns RPG data into a state. Start with templates for an encounter (party, monsters, distance, stance, recent events, and the player's words). Read states as JSON first. Later, add an optional extra that imports osrlib to build states from osr-web save files and osrlib session views, so jevtester still works without osrlib.

### Storage and config

- Suites, question sets, and policies are YAML files under `suites/`, reviewed in git.
- Runs and results go in `.jevtester/runs.sqlite`, which git ignores.
- Targets and defaults go in `jevtester.toml`. Credentials come from the signed-in CLIs: `az` through `azure-identity` for Foundry, and Wrangler for Workers AI. `CLOUDFLARE_API_TOKEN` and `ANTHROPIC_API_KEY` in the environment override or add to them. The Cloudflare account ID goes in `jevtester.toml`.

## Companion CLI

The CLI makes every capability available to scripts, continuous integration, and agents. Every command accepts `--format json` and writes JSON to stdout, and writes progress and warnings to stderr.

| Command | What it does |
|---|---|
| `jevtester decide` | Sends one state and one or more questions to one or more targets and prints the answers. |
| `jevtester targets list` | Lists configured targets and their capabilities. |
| `jevtester targets check` | Runs each target's health check and reports why any target is unavailable. |
| `jevtester run <suite>` | Runs a suite and prints the run id and metrics. |
| `jevtester compare <run> <run>` | Compares two runs: metrics, changed answers, and McNemar's test. |
| `jevtester report <run>` | Writes a report as Markdown or JSON. |
| `jevtester probe <suite>` | Runs probes and reports how often answers change. |
| `jevtester case add` | Saves a case to a suite, including one promoted from a `decide` call. |
| `jevtester suite check` | Validates a suite and runs the question-wording checks. |
| `jevtester serve` | Starts the API and the web UI on `127.0.0.1`. |

`decide` takes its inputs from flags, a file, or stdin:

```sh
# A yes/no question on the default target
uv run jevtester decide --state "Six goblins block the stairs." --question "Are the goblins hostile?"

# A choice question on two targets
uv run jevtester decide --state @encounter.json \
  --question "What is the player trying to do?" \
  --option parley="Talk, bargain, or bribe" --option fight="Attack" --option evade="Run away" \
  --target decision-1@foundry --target clef-flash@ollama --format json

# A full request from a file
uv run jevtester decide --request request.json --targets all
```

Exit codes:

- `0` - success.
- `1` - a run finished, and a regression check or an expectation failed.
- `2` - the command line or a suite is invalid.
- `3` - every target failed, or the only target failed.

### Agents

Anthropic has no decision model, but an agent can still get decisions: `claude -p` runs Claude Code headless, and Claude calls `jevtester decide` and acts on the JSON. For example, a referee script can ask Claude to run an encounter and let Claude call the CLI:

```sh
claude -p --allowedTools "Bash(uv run jevtester decide:*)" \
  "The player says: 'Take this silver and let us pass.' Use jevtester decide with target decision-1@foundry to judge the goblins' reaction on the B/X reaction bands, then narrate the result."
```

Keep the JSON output stable and documented, since agents and scripts parse it. Later, a Claude Code skill can document the CLI for agents.

## First suites: RPG referee decisions

[osrlib](https://github.com/mmacy/osrlib-python) is a deterministic rules engine and the authority on game state. A decision model fits where the B/X rules leave a call to a human referee. Your code turns the model's answer into an ordinary referee command, and the engine applies it, so replays and the event stream still work.

| Type | Question | Where it applies |
|---|---|---|
| Choice | What is the player trying to do during an encounter: `Parley`, `Evade`, `Wait`, `TurnUndead`, or `EngageBattle`? | The encounter commands in osrlib-python's `src/osrlib/crawl/encounter.py` |
| Choice | What tactic does a monster group use after its stance changes? | Encounter and battle rounds |
| Noul | Does the player's parley offer something these monsters want? | The parley reaction roll |
| Noul | Did the player speak the gate's password, or something close to it? | Gate conditions in osrlib-python's `src/osrlib/crawl/gates.py` |
| Noul | Is the narrator's passage consistent with the event log? | osr-web's LLM narration (`server/narration.py` in osr-web) |
| Score | How do the monsters react to the parley, on the B/X reaction bands? | The 2d6 reaction bands in osrlib-python's `src/osrlib/crawl/encounter.py` |
| Score | How good is a narration passage, on a rubric? | osr-web's narration beats |

Start with the parley suite. The B/X reaction bands are an ordered scale, and each band describes behavior instead of a degree. The vendors recommend that for score levels. The request in [Decision models and the System One API](#decision-models-and-the-system-one-api) is the first case.

## What the UI must show

The UI must let a person:

- Run a quick test from a state and a question, then add options, change the type, and add targets without starting over.
- See each answer as probability bars for every option or level, with confidence, the score and legend, latency, tokens, cost, and any truncation warning.
- Compare targets side by side on the same request.
- Promote a quick test to a case and give it an expected answer.
- Edit question sets, see the version history, and diff two versions.
- Build a suite, pick targets, and start, follow, and cancel a run.
- Read run metrics, confusion matrices, calibration tables, and latency and cost summaries.
- Compare two runs and step through the cases whose answers changed.
- Run probes and see which cases change under which variant.
- Edit a policy, sweep a threshold, and see the trade-off between cases decided and errors.
- Review and approve Claude drafts before they count.
- See which targets are available and why any aren't.

Follow the user's rules for UI text:

- Use sentence case for every label, button, card, tab, and panel.
- Write each string as a label or a fact the person acts on. Cut words that explain the UI to the person, like "Nothing you typed is lost" or "Red cells are cases answered as the wrong option." A legend or an axis label covers what a color means.

The user chose the heat matrix direction in `mockups/3-matrix.html`: every view is a grid, with targets as columns, options and levels as rows, and cell color for probability. Build the UI plan from that mockup. The other three mockups in `mockups/` are the directions the user didn't choose.

## Build order

Each step ends with a command that shows the step works. Write the contracts (models and protocol signatures) and their tests before the implementation.

1. **Project setup.** Create the uv project, the package layout, `jevtester.toml`, and the gates. Done when `uv run ruff check`, `uv run pyright`, and `uv run pytest` pass.
2. **Contracts.** Write the spec models, `DecisionProvider`, `Capabilities`, and the canonical answer types. Test request serialization against the request above, and normalization against the Foundry response above. Done when those tests pass.
3. **Foundry provider and `decide`.** Implement the SystemOne provider with Entra tokens, and `jevtester decide` and `targets check`. Done when `uv run jevtester decide --target decision-1@foundry ...` returns the canonical JSON.
4. **Other providers.** Add Ollama, MLX, and Workers AI. Leave the Claude provider for later. Done when `targets check` reports each target ready or gives the reason it isn't.
5. **Suites, storage, and the runner.** Add YAML suites, SQLite runs, caching, concurrency limits, and progress events. Done when `jevtester run suites/parley.yaml` records a run, and a second run of the same suite uses the cache.
6. **Evaluation and comparisons.** Add the scorers, metrics, reports, `compare`, and the regression check. Done when `jevtester compare` lists changed answers between two question set versions.
7. **Policies.** Add YAML policies, decision accuracy, threshold sweeps, and the cost matrix. Done when a suite with expected actions reports decision accuracy.
8. **Probes.** Add every probe except paraphrasing, which needs Claude. Done when `jevtester probe` reports the option-order change rate.
9. **API.** Expose `service.py` through FastAPI on `127.0.0.1`, with SSE for run progress. Done when every CLI command has a matching endpoint and the API tests pass.
10. **UI.** The frontend session builds it in parallel with steps 2 through 9, as [the handoff notes](handoff.md#frontend-session) describe.

## Decisions

The user made these decisions:

- **Local models.** Support both Ollama and MLX, so runs can compare runtimes and quantization on the same model.
- **osrlib.** State builders read exported JSON first. Importing osrlib is a later, optional extra.
- **Evaluation library.** Build the evaluation code in jevtester instead of adopting pydantic-evals. jevtester's requests have several questions each and run across a matrix of targets, which a library built around evaluating one task function doesn't fit, and jevtester needs calibration and confusion-matrix metrics that pydantic-evals' docs don't show.
- **Cloudflare.** Authenticate Workers AI with the Wrangler sign-in instead of creating an API token.
- **UI direction.** The heat matrix mockup, `mockups/3-matrix.html`.
- **Claude.** Build without the Claude provider and the assist features. Design the provider protocol so a Claude provider can be added later without changes elsewhere.

## References

- [Deploy and use Microsoft-Decision-1 in Microsoft Foundry](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/use-foundry-models-microsoft-decision)
- [Clef-flash on Workers AI](https://developers.cloudflare.com/workers-ai/models/clef-flash/)
- [Introducing Clef (Cloudflare changelog)](https://developers.cloudflare.com/changelog/post/2026-10-01-clef-workers-ai/)
- [Clef-omni (Cloudflare changelog)](https://developers.cloudflare.com/changelog/post/2026-10-09-clef-omni-workers-ai/)
- [Cloudflare/clef-flash on Hugging Face](https://huggingface.co/Cloudflare/clef-flash)
- [mlx-community/clef-8bit](https://huggingface.co/mlx-community/clef-8bit)
- [Ollama clef-flash](https://ollama.com/library/clef-flash)
- [TypeSafe Python SDK](https://github.com/typesafe-ai/typesafe-sdk-python)
- [TypeSafe docs](https://docs.typesafe.ai): System One concepts, primitives, confidence, and patterns
- [Pydantic AI System One models](https://pydantic.dev/docs/ai/models/system-one/)
