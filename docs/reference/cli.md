# CLI reference

`jevtester` is the command-line tool for testing decision models. It sends states and questions to targets, runs suites, scores the answers, and starts the HTTP API and web UI.

These terms appear throughout this page:

- A *target* is one decision model on one runtime, like `decision-1@foundry`. The [config file](config.md) lists the targets.
- A *state* is what the model reads: text, a JSON object, or a JSON array.
- A *suite* is a YAML file in `suites/` with *cases*: states, each with the answers and action it expects. The [suite format reference](suite-format.md) describes the files.
- A *run* sends every case in a suite to each target and scores the answers. A *job* is one case on one target for one repeat.

For step-by-step guides, see [Getting started](../getting-started.md) and the [how-to guides](../how-to.md). For what the metrics and policies mean, see [Concepts](../concepts.md).

## Synopsis

```text
jevtester [--config PATH] <command> [options]
jevtester --version
jevtester --help
```

The commands, in the order you usually meet them:

| Command | What it does |
|---|---|
| [`targets list`](#jevtester-targets-list) | Lists the configured targets, without a health check. |
| [`targets check`](#jevtester-targets-check) | Runs every target's health check. |
| [`decide`](#jevtester-decide) | Sends one state and its questions to targets and prints their answers. |
| [`case add`](#jevtester-case-add) | Saves a case to a suite, including one promoted from a `decide` result. |
| [`suite check`](#jevtester-suite-check) | Validates a suite and runs the question-wording checks. |
| [`run`](#jevtester-run) | Runs a suite and prints the run's id and counts. |
| [`report`](#jevtester-report) | Prints a run's report as Markdown or JSON. |
| [`compare`](#jevtester-compare) | Compares a run with a baseline run, and exits with 1 on a regression. |
| [`probe`](#jevtester-probe) | Runs probes on a suite and reports how often the answers change. |
| [`policy sweep`](#jevtester-policy-sweep) | Moves a policy threshold over a run's answers and prints the trade-off. |
| [`serve`](#jevtester-serve) | Starts the HTTP API and the web UI. |

A first session usually looks like this:

```sh
jevtester targets check
jevtester decide --state "Six goblins block the stairs. The player offers them silver." \
    --question "Does the player offer the monsters something of value?" --id bribe
jevtester run parley
jevtester report 0001
```

Run `jevtester <command> --help` for the same information in the terminal.

## Global options

These options go before the command name.

| Option | Description |
|---|---|
| `--config PATH` | The config file. Without it, jevtester uses `$JEVTESTER_CONFIG`, or else `jevtester.toml` in the working directory with `jevtester.local.toml` merged over it. The [configuration reference](config.md#where-jevtester-looks-for-the-config) gives the details. |
| `--version` | Prints `jevtester` and the version, like `jevtester 0.1.0`, and exits with 0. |
| `-h`, `--help` | Prints help and exits with 0. Every command and subcommand takes it. |

Running `jevtester` with no command prints the help and exits with 0.

## Output

Every command writes its result to stdout, and its progress and warnings to stderr. Most commands take `--format`:

- `text`, the default, is for people. Its layout can change between versions.
- `json` is for scripts. It's the same JSON the [HTTP API](http-api.md) returns for the matching route, indented by 2 spaces. Fields are never left out: an unknown value is `null`.

Each command's JSON output matches a route:

| Command | Same JSON as |
|---|---|
| `jevtester decide` | [`POST /api/decide`](http-api.md#ask-targets-one-request) |
| `jevtester targets list` | [`GET /api/targets`](http-api.md#list-targets) |
| `jevtester targets check` | [`POST /api/targets/check`](http-api.md#check-targets) |
| `jevtester run` | [`GET /api/runs/{id}`](http-api.md#get-a-run), once the run ends |
| `jevtester probe` | [`GET /api/runs/{id}/probes`](http-api.md#get-probe-results) |
| `jevtester compare` | [`GET /api/runs/{id}/compare`](http-api.md#compare-two-runs) |
| `jevtester report` | [`GET /api/runs/{id}/report`](http-api.md#get-a-run-report) |
| `jevtester suite check` | [`GET /api/suites/{name}/check`](http-api.md#check-a-suite) |
| `jevtester case add` | [`POST /api/suites/{name}/cases`](http-api.md#add-a-case) |
| `jevtester policy sweep` | [`POST /api/policies/{name}/sweep`](http-api.md#sweep-a-policy-threshold) |

## Exit codes

| Code | Meaning | What to do |
|---|---|---|
| 0 | Success. | |
| 1 | `jevtester compare` found a regression. Also an unhandled error, which prints a Python traceback, like a config that isn't valid TOML. | Look at the regressions it printed. For a traceback, see [Known issues](../handoff.md#known-issues). |
| 2 | The command line, an input, or the config is invalid, or a suite, run, policy, case, or target doesn't exist, or a case id is taken. `jevtester suite check` also returns 2 for an invalid suite. | Read the message on stderr, which starts with `jevtester:`. Fix the input before you run the command again. |
| 3 | `jevtester decide` got no answer from any target, or `jevtester run` had jobs and got no answer for any of them. | Run `jevtester targets check` to see which targets are down and why. |

An error message on stderr looks like this:

```console
$ jevtester run nope; echo $?
jevtester: No suite named nope
2
```

## Reading a state

`decide --state` and `case add --state` take a state in one of three forms:

- Plain text, used as a text state.
- `@PATH`, which reads the file. The state is the parsed JSON when the file is valid JSON, and the file's text otherwise.
- `-`, which reads stdin, parsed the same way as a file.

## Naming a suite

`run`, `probe`, `suite check`, and `case add` take the suite as its name, like `parley`, or as its file name, like `suites/parley.yaml`. A value that ends in `.yaml` or `.yml` is reduced to the file name without the extension. jevtester then reads the suite from the suites directory in the config (`suites/` by default), whatever directory the value names.

## jevtester targets list

Lists the configured targets with their status and a note.

```text
jevtester targets list [--format text|json]
```

Each line has the target's name, its status, and a note: why it's down, where its credential comes from, or a warning that applies to every request. The status is one of these:

- `unchecked`: no health check has run in this process.
- `ready`: the last health check passed.
- `warning`: the target is ready, and has a warning, like `Cuts the state to fit its 24,576-token window`.
- `down`: the last health check failed. The note says why.

This command doesn't run a health check, so every target shows `unchecked`. Use [`jevtester targets check`](#jevtester-targets-check) to check them.

| Option | Description |
|---|---|
| `--format text\|json` | `text` (the default) or `json`. The JSON is a `TargetList` with every target's capabilities. |

Example, with the `jevtester.toml` in the repository:

```console
$ jevtester targets list
decision-1@foundry     unchecked
clef-flash@ollama      unchecked
clef-flash-4bit@mlx    unchecked
clef-flash-8bit@mlx    unchecked
clef-8bit@mlx          unchecked
clef-flash@workers-ai  unchecked  Cuts the state to fit its 24,576-token window
clef@workers-ai        unchecked  Cuts the state to fit its 65,536-token window
clef-omni@workers-ai   unchecked  Cuts the state to fit its 65,536-token window
```

## jevtester targets check

Runs every target's health check at once and prints each target's status.

```text
jevtester targets check [--format text|json]
```

A health check sends no decision request. It checks that the target could take one:

| Runtime | Ready when |
|---|---|
| Foundry | `base_url` doesn't name the placeholder resource `example-resource`, a token can be read from the `az` sign-in, and the endpoint answers a GET of `base_url`, which reaches no model and costs nothing. The note says when the token refreshes. The check can't catch a wrong deployment name. |
| Ollama | Ollama answers, is version 0.35.1 or later, and has the model pulled. |
| MLX | The MLX server answers and has the target's model loaded. It serves one model, so at most one MLX target is ready at a time. |
| Workers AI | `cloudflare.account_id` is set, a token can be read from `CLOUDFLARE_API_TOKEN` or the Wrangler sign-in, and the account's Workers AI catalog lists the model. |

A check that takes longer than 15 seconds marks the target down. The command exits with 0 even when targets are down.

| Option | Description |
|---|---|
| `--format text\|json` | `text` (the default) or `json`. The JSON is a `TargetList` with each target's `reason`, `detail`, and `credential`. |

Example output, with Foundry signed in and Ollama missing the model:

```console
$ jevtester targets check
decision-1@foundry     ready      Azure CLI, refreshes in 41 min
clef-flash@ollama      down       clef-flash isn't pulled
clef-flash-4bit@mlx    down       The MLX server isn't running
clef-flash-8bit@mlx    down       The MLX server isn't running
clef-8bit@mlx          down       The MLX server isn't running
clef-flash@workers-ai  warning    Wrangler sign-in
clef@workers-ai        warning    Wrangler sign-in
clef-omni@workers-ai   warning    Wrangler sign-in
```

The [how-to guides](../how-to.md) cover fixing a target that's down.

## jevtester decide

Sends one state and its questions to one or more targets at once, and prints each target's answers, latency, tokens, and cost.

```text
jevtester decide --state STATE --question TEXT [--id ID] [--option NAME=DESCRIPTION]... [--level DESCRIPTION]... [options]
jevtester decide --request PATH [options]
```

Ask one question with `--state` and `--question`. It's a yes/no question (a *noul*) unless `--option` makes it a choice or `--level` makes it a score. To ask several questions at once, put the state and questions in a JSON file and pass `--request`.

The targets answer at the same time, and the command prints when the last one finishes. A target that fails prints `failed` with its error code, and the others still answer. To keep a result as a test case, save the JSON output and pass it to [`jevtester case add --from-decide`](#jevtester-case-add).

| Option | Description |
|---|---|
| `--state STATE` | The state, as text, `@PATH`, or `-`. See [Reading a state](#reading-a-state). Required unless you give `--request`. |
| `--question TEXT` | The question the model reads. Required unless you give `--request`. |
| `--id ID` | The id the answer comes back under. Defaults to `question`. |
| `--option NAME=DESCRIPTION` | A choice option. Repeat for each option. A choice needs two or more. Can't be used with `--level`. |
| `--level DESCRIPTION` | A score level, lowest first. Repeat for each level. A score needs two or more. Can't be used with `--option`. |
| `--request PATH` | A JSON file with `state`, `questions`, and optionally `images`, or `-` to read stdin. The [suite format reference](suite-format.md#questions) describes the questions. A `model` field is ignored, so a System One request body works too. `targets` and `timeout_s` in the file are ignored; use the options instead. Can't be used with `--state`, `--question`, `--option`, or `--level`. |
| `--target NAME` | A target to ask. Repeat for each. Defaults to the config's `defaults.targets`. |
| `--targets all` | Ask every configured target. Overrides `--target`. |
| `--timeout SECONDS` | Seconds to wait for each target. Defaults to the config's `defaults.timeout_s`, which is 60 unless the config sets it. |
| `--format text\|json` | `text` (the default) or `json`. |

The text output has one block per target: its name, latency, input and output tokens, and cost, then one line per answer, then any warnings. Each answer line depends on the question's type:

- A noul prints `yes` or `no` (yes when the probability of yes is 0.5 or more), the probability of yes, and the confidence.
- A choice prints the chosen option, the confidence, and each option's probability.
- A score prints the probability-weighted score, the most probable level and its description, and the server's confidence.

`cost unknown` means the target has no price in the config, or the server reported no token count. The [HTTP API reference](http-api.md#results) describes each JSON field.

Exits with 3 when no target answered, and with 2 for invalid input or an unknown target.

Examples:

```sh
# Ask the default targets a yes/no question about a text state
jevtester decide --id bribe \
    --state "Six goblins block the stairs. The player offers them silver." \
    --question "Does the player offer the monsters something of value?"

# Ask two targets a choice question about a JSON state in state.json
jevtester decide --state @state.json --id intent \
    --question "What is the player trying to do?" \
    --option "parley=Talk or bargain" --option "fight=Attack the monsters" \
    --target decision-1@foundry --target clef-flash@workers-ai

# Ask a score question, lowest level first
jevtester decide --state @state.json --id reaction \
    --question "How are the monsters likely to react?" \
    --level "Attack at once" --level "Uncertain" --level "Friendly"
```

With `goblin.json` holding the state and three questions from the `parley` suite's first case:

```json
{
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

the output looks like this:

```console
$ jevtester decide --request goblin.json --target decision-1@foundry --target clef-flash@workers-ai
decision-1@foundry  1,550 ms  185 in, 3 out  cost unknown
  intent: parley  confidence 0.9995  (parley 0.9996, evade 0.0002, fight 0.0001, wait 0.0001)
  bribe: yes  p(yes) 0.9988  confidence 0.9977
  reaction: 2.21  level 2: Uncertain, hold and posture  server confidence 0.3229
clef-flash@workers-ai  2,470 ms  452 in, 0 out  $0.0000172
  intent: parley  confidence 0.9741  (parley 0.9806, evade 0.0074, fight 0.0050, wait 0.0070)
  bribe: yes  p(yes) 0.9453  confidence 0.8906
  reaction: 1.81  level 1: Hostile, may attack  server confidence 0.0544
  warning state_may_truncate: Cuts the state to fit its 24,576-token window
```

A target that doesn't answer prints one line with its error code. Here the MLX server isn't running:

```console
$ jevtester decide --request goblin.json --target clef-flash-4bit@mlx; echo $?
clef-flash-4bit@mlx  failed  not_ready: The MLX server isn't running
3
```

`decide` runs no health check first, except on MLX targets, so an unchecked target is sent the request.

## jevtester case add

Adds a case to the end of a suite's file.

```text
jevtester case add SUITE --id ID (--state STATE | --from-decide PATH) [options]
```

Give the state with `--state`, or promote a `decide` result with `--from-decide`, which reads the output of `jevtester decide --format json` and takes its state. `--expect-from` then takes the expected answers from one target's answers in that output. `--expect` sets single answers, and replaces an answer that `--expect-from` set.

jevtester rewrites the suite file from its parsed contents, so comments in the file are lost. Run [`jevtester suite check`](#jevtester-suite-check) afterward to check the case against the question set.

| Argument or option | Description |
|---|---|
| `SUITE` | The suite. See [Naming a suite](#naming-a-suite). |
| `--id ID` | The case's id. Required. It must be new in the suite. |
| `--state STATE` | The state, as text, `@PATH`, or `-`. See [Reading a state](#reading-a-state). Give this or `--from-decide`, not both. |
| `--from-decide PATH` | A file of `jevtester decide --format json` output, or `-` to read stdin. |
| `--expect-from TARGET` | Expect the answers this target gave in `--from-decide`. Requires `--from-decide`. The target must have answered. |
| `--expect QUESTION=ANSWER` | An expected answer. Repeat for each question. The question's type sets the format: `true` or `false` (or `yes` or `no`) for a noul, an option name for a choice, or a level number from 0 for a score. The question must be in the suite's question set. |
| `--tolerance QUESTION=LEVELS` | Levels of slack for a score question, as a whole number. An answer within this many levels counts as correct. Repeat for each question. |
| `--expected-action ACTION` | The action the suite's policy should choose, like `parley_succeeds`. |
| `--tag TAG` | A tag for grouping cases. Repeat for each. |
| `--format text\|json` | `text` (the default) or `json`. |

Exits with 2 for invalid input, an unknown suite, or a case id the suite already has.

Examples:

```console
$ jevtester case add parley --id troll-toll \
    --state "A troll blocks the bridge and asks for a toll." \
    --expect intent=parley --expect bribe=true --expect reaction=2 \
    --tolerance reaction=1 --expected-action parley_succeeds --tag bribe
Added case troll-toll to suite parley (5 cases)
```

```sh
# Promote a decide result, keeping Foundry's answers except one
jevtester decide --request goblin.json --target decision-1@foundry --format json > decide.json
jevtester case add parley --id goblin-silver --from-decide decide.json \
    --expect-from decision-1@foundry --expect reaction=3
```

## jevtester suite check

Validates a suite and runs the question-wording checks on its question set.

```text
jevtester suite check SUITE [--format text|json]
```

The suite is valid when all of these hold:

- The suite, its question set, and its policy load.
- Every case's expectations name questions the question set asks, with values of the right type and in range.
- No case id is used twice.
- The policy reads only questions the question set asks.

The wording checks are heuristics. Each finding is a prompt to look at a question, and none makes the suite invalid. The [suite format reference](suite-format.md#wording-checks) lists them.

| Argument or option | Description |
|---|---|
| `SUITE` | The suite. See [Naming a suite](#naming-a-suite). |
| `--format text\|json` | `text` (the default) or `json`. |

Exits with 2 when the suite is invalid or doesn't exist.

Example:

```console
$ jevtester suite check parley
Suite parley is valid
```

A finding prints its code, the question, and the message, like this one for a choice with no abstention option:

```text
Suite door is valid
  no_abstention  approach: No option like cannot_tell
```

## jevtester run

Sends every case in a suite to each target, waits for the run to finish, and prints the run's id and job counts.

```text
jevtester run SUITE [--target NAME]... [--repeats N] [--question-set-version HASH] [--baseline RUN] [--no-cache] [--format text|json]
```

The run first checks each target's health, and skips every job of a target that's down. Each result is cached by its target, its request, and its repeat, so a rerun of an unchanged suite sends nothing. Each request waits up to the config's `defaults.timeout_s`. Cases with `provenance: claude-draft` aren't sent.

Progress goes to stderr: `Run <id> started`, then one line per job with its position, case, target, and `ok`, `failed`, or `cached`. Pass the run's id to [`jevtester report`](#jevtester-report), [`jevtester compare`](#jevtester-compare), or [`jevtester policy sweep`](#jevtester-policy-sweep).

| Argument or option | Description |
|---|---|
| `SUITE` | The suite. See [Naming a suite](#naming-a-suite). |
| `--target NAME` | A target to run. Repeat for each. Defaults to the suite's `targets`, or else the config's `defaults.targets`. |
| `--repeats N` | Times to send each case to each target, at least 1. Defaults to the config's `defaults.repeats`. Each repeat is cached apart, so repeats measure consistency. |
| `--question-set-version HASH` | An earlier question set version to run, as its hash or a prefix of 8 or more characters. Defaults to the version in the file now. |
| `--baseline RUN` | A run to compare with. It must exist. The run's report then lists the answers that changed from it. |
| `--no-cache` | Send every request, even when a cached result exists. |
| `--format text\|json` | `text` (the default) or `json`. The JSON is the run's final `RunSummary`. |

Exits with 3 when the run had jobs and none got an answer, and with 2 for an unknown suite, target, question set version, or baseline.

Example:

```console
$ jevtester run parley --target decision-1@foundry --target clef-flash@workers-ai
Run 0005 started
1/8  goblin-bribe  decision-1@foundry  cached
2/8  goblin-bribe  clef-flash@workers-ai  cached
...
8/8  gnoll-watch  clef-flash@workers-ai  cached
Run 0005 finished: 8 jobs, 0 sent, 8 from cache, 0 failed, 0 skipped, $0.000000
  decision-1@foundry  0 sent, 4 cached, 0 failed
  clef-flash@workers-ai  0 sent, 4 cached, 0 failed
```

The first line and the job lines are on stderr. The summary is on stdout. A target whose jobs were skipped shows `skipped:` and the reason.

## jevtester report

Prints a run's summary and its metrics for each target and question.

```text
jevtester report RUN [--format markdown|json]
```

The report has the run's settings and counts, a table of each target's results, latency, and cost, a table per question with its metrics, and the policy's decisions when the suite has a policy. When the run has a baseline, it also lists the answers that changed from it. [Concepts](../concepts.md#metrics) explains each metric.

| Argument or option | Description |
|---|---|
| `RUN` | The run's id, like `0002`. |
| `--format markdown\|json` | `markdown` (the default) or `json`. The JSON is a `RunReport`, with the same Markdown in its `markdown` field. |

Exits with 2 when the run doesn't exist.

Example, shortened:

```console
$ jevtester report 0002
# Run 0002: parley

- Status: finished
- Question set: `parley` version `95e251b70a75`
- Cases: 4, repeats: 1
- Jobs: 12, sent 6, from cache 2, failed 0, skipped 4
- Cost: $0.000014
- Baseline: run 0001

## Targets

| Target | Results | Errors | Skipped | p50 latency (ms) | p95 latency (ms) | Cost per 1,000 |
|---|---|---|---|---|---|---|
| decision-1@foundry | 4 | 0 | 0 | 1519 | 1596 |  |
| clef-flash@workers-ai | 4 | 0 | 0 | 2430 | 2533 | $0.009443 |
| clef-flash@ollama | 0 | 0 | 4 |  |  |  |

## intent

| Target | n | Accuracy | Macro-F1 | MAE | Within tolerance | Brier | Log loss | AUROC | ECE |
|---|---|---|---|---|---|---|---|---|---|
| decision-1@foundry | 4 | 1.000 | 1.000 |  |  |  |  |  | 0.054 |
| clef-flash@workers-ai | 4 | 0.750 | 0.667 |  |  |  |  |  | 0.189 |
| clef-flash@ollama | 0 | | | | | | | | |
...
```

## jevtester compare

Compares a run with a baseline run.

```text
jevtester compare RUN BASELINE [--max-drop SHARE] [--format text|json]
```

The output lists each answer that changed on the targets both runs ran, using each case's first repeat:

- `fixed`: the answer went from wrong to right.
- `broken`: the answer went from right to wrong.
- `changed`: the answer changed and stayed right or stayed wrong, like a score that moved within its tolerance.

Then each target's counts and McNemar's exact two-sided p-value, a test of whether the fixed and broken counts differ by more than chance. Last, each *regression*: a target and question whose accuracy dropped by more than `--max-drop`. For a score question, the metric is within-tolerance accuracy.

| Argument or option | Description |
|---|---|
| `RUN` | The id of the run to check. |
| `BASELINE` | The id of the run to compare it with. |
| `--max-drop SHARE` | The largest allowed drop, as a share like `0.05`. Defaults to the config's `defaults.max_drop`, which is 0.05 unless the config sets it. |
| `--format text\|json` | `text` (the default) or `json`. |

Exits with 1 when there's a regression, so a script or CI job can fail on it, and with 2 when either run doesn't exist.

Example:

```console
$ jevtester compare 0001 0002; echo $?
Run 0001 against baseline 0002
  broken   gnoll-watch  decision-1@foundry  intent: wait -> evade (expected wait)
  fixed    kobold-retreat  clef-flash@workers-ai  intent: wait -> evade (expected evade)
  broken   gnoll-watch  clef-flash@workers-ai  intent: wait -> evade (expected wait)
decision-1@foundry: 0 fixed, 1 broken, 0 changed, McNemar p 1.000
clef-flash@workers-ai: 1 fixed, 1 broken, 0 changed, McNemar p 1.000
Regression: decision-1@foundry intent accuracy 1.000 -> 0.750 (allowed drop 0.05)
1
```

## jevtester probe

Runs each case as written and as each probe changes it, then prints how often each target's answers changed.

```text
jevtester probe SUITE [--variant PROBE]... [--target NAME]... [--no-cache] [--format text|json]
```

A *probe* changes something about a case that shouldn't change the answers. A changed answer points to a model, or a question, that reacts to wording instead of meaning.

| Probe | Variants per case | Applies when |
|---|---|---|
| `option_order` | 3, each a different order of every choice question's options | The questions include a choice. |
| `key_order` | 1, with every JSON object's keys reversed | The state has a JSON object with more than one key. |
| `bare_levels` | 1, with each score level's description replaced by its number | The questions include a score. |
| `pad_state` | 1, with neutral text added until the request fills about 90% of the target's context window | The target's `context_window` is known. |

A probe run sends each request once, whatever the config's repeats. An instance changed when any answer differs from the original case's answer. A failed request isn't counted. Progress goes to stderr, with each job's variant, like `option_order:2`.

| Argument or option | Description |
|---|---|
| `SUITE` | The suite. See [Naming a suite](#naming-a-suite). |
| `--variant PROBE` | A probe to run: `option_order`, `key_order`, `bare_levels`, or `pad_state`. Repeat for each. Defaults to `option_order`, `key_order`, and `bare_levels`. `pad_state` sends large requests, so it runs only when you name it. |
| `--target NAME` | A target to probe. Repeat for each. Defaults to the suite's `targets`, or else the config's `defaults.targets`. |
| `--no-cache` | Send every request, even when a cached result exists. |
| `--format text\|json` | `text` (the default) or `json`. |

Exits with 2 for an unknown suite or target.

Example, with stderr left out:

```console
$ jevtester probe parley --target decision-1@foundry
Run 0006
  decision-1@foundry  option_order  change rate 0.167 over 4 cases
  decision-1@foundry  key_order  change rate 0.000 over 4 cases
  decision-1@foundry  bare_levels  change rate 0.000 over 4 cases
  changed  kobold-retreat  decision-1@foundry  option_order: 2 of 3
```

## jevtester policy sweep

Measures one target's decisions in a run as one of the policy's thresholds moves.

```text
jevtester policy sweep POLICY --run RUN --target NAME --threshold NAME [--start VALUE] [--stop VALUE] [--step VALUE] [--format text|json]
```

A *policy* turns a result's answers into an action, and a *threshold* is a named number in it. For each value from `--start` to `--stop`, the sweep prints the share of cases the policy decided without escalating, the error rate among those, and the cost from the policy's cost matrix. The sweep uses the policy file as it is now, against the run's answers, so you can tune a threshold without running the suite again. Each value replaces the threshold for the target, whether the policy sets a shared value or a `per_target` one. The first line shows the target's value now.

| Argument or option | Description |
|---|---|
| `POLICY` | The policy's name, like `parley`. |
| `--run RUN` | The id of the run whose answers to use. Required. |
| `--target NAME` | A target the run ran. Required. |
| `--threshold NAME` | The name of the threshold to move. Required. |
| `--start VALUE` | The first value. Defaults to 0. |
| `--stop VALUE` | The last value. Defaults to 1. It's included when `--start` plus a whole number of steps reaches it. |
| `--step VALUE` | The gap between values, greater than 0. Defaults to 0.05. |
| `--format text\|json` | `text` (the default) or `json`. |

A sweep has at most 1,000 points. Exits with 2 for an unknown policy, run, or threshold, a target the run didn't run, or a range of more than 1,000 points.

Example:

```console
$ jevtester policy sweep parley --run 0002 --target decision-1@foundry \
    --threshold goodwill --start 0.3 --stop 0.7 --step 0.1
parley goodwill on decision-1@foundry, run 0002 (now 0.550)
value   decided  error rate  cost
0.3     1.000    0.000       0.000
0.4     1.000    0.000       0.000
0.5     1.000    0.000       0.000
0.6     1.000    0.000       0.000
0.7     1.000    0.000       0.000
```

## jevtester serve

Starts the HTTP API and the web UI.

```text
jevtester serve [--port PORT]
```

The server listens only on `127.0.0.1`, and runs until you stop it with Ctrl-C. Every API route is under `/api`, and the [HTTP API reference](http-api.md) describes them. The server also serves interactive API docs at `/docs`. It serves the web UI at `/`. Until the frontend is built, `/` returns a short page with the commands that build it. The [how-to guides](../how-to.md#build-the-web-ui) cover building it.

The server reads the config when it starts, so a config error exits before it listens, with 2 for most errors. The server keeps health check results and runs in progress in memory. When the server, or any other jevtester command, starts, it marks every run still recorded as queued or running as `failed`, even a run that another jevtester process is still running.

| Option | Description |
|---|---|
| `--port PORT` | The port to listen on. Defaults to 8640. |

Example:

```sh
jevtester serve --port 8650
```
