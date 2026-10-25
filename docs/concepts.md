# Concepts

jevtester asks decision models questions, measures their answers, and applies a policy to turn the answers into actions. For the steps to do something, see the [how-to guides](how-to.md). For every field and flag, see the reference pages, like the [CLI reference](reference/cli.md).

## Why jevtester exists

A decision model gives you numbers, not prose. Before you build on those numbers, you need to know three things:

- Whether the model answers your questions correctly.
- Whether your questions are worded well. Small wording changes can change the answers.
- Whether the decisions your code makes from the answers are good ones.

jevtester tests all three. You write test cases with the answers you expect, run them on one or more models, and read the metrics. You can change the wording, the model, or a threshold, run again, and see what changed.

## Decision models

A *decision model* reads a *state* and a set of typed *questions*. For each question, it returns a probability for every allowed answer. It doesn't write text.

A chat model, or large language model (LLM), is different. It generates text, and your code has to parse that text to get an answer. A decision model returns a fixed shape: a probability, a chosen option with a probability for each option, or a position on a scale. Your code can compare the numbers with a threshold.

Decision models also return no reasoning. You learn what the model thinks from the probabilities alone.

jevtester supports these decision models:

| Model | Where it runs | jevtester target |
|---|---|---|
| Microsoft-Decision-1 | Your Azure AI Foundry resource | `decision-1@foundry` |
| Clef-flash | Cloudflare Workers AI, a local Ollama server, or a local MLX server | `clef-flash@workers-ai`, `clef-flash@ollama`, `clef-flash-4bit@mlx`, `clef-flash-8bit@mlx` |
| Clef | Cloudflare Workers AI, or a local MLX server | `clef@workers-ai`, `clef-8bit@mlx` |
| Clef-omni | Cloudflare Workers AI | `clef-omni@workers-ai` |

### Targets

A *target* is one model on one runtime, with its settings. Its name has the form `model@runtime`, like `clef-flash@ollama`. The same model on two runtimes is two targets, so you can compare a hosted copy with a local one, or two quantizations of one model.

Each target lists its *capabilities* in the config: whether it returns probabilities, its context window, its limits on questions and options, how many requests it takes at once, and its price per million input tokens. jevtester uses them to check each request before it sends it. The [configuration reference](reference/config.md) lists every capability.

### The System One API

Every target accepts the same request format, which the vendors call the *System One API*. A request has a `model`, a `state`, and up to 64 `questions`, each keyed by an id you choose. Each answer comes back under its question's id.

```json
{
  "model": "decision-1",
  "state": "Six goblins block the stairs.",
  "questions": {
    "hostile": {"type": "noul", "instructions": "Are the goblins hostile?"}
  }
}
```

The model doesn't see the question's id. Put everything the model needs in `instructions`.

## Questions

There are three question types.

| Type | Asks | Answer |
|---|---|---|
| `noul` | A yes/no question. | The probability of yes. |
| `choice` | Which one option fits, from a map of option names to descriptions. | The chosen option and a probability for each option. |
| `score` | Where the state falls on an ordered list of levels, lowest first. | A probability for each level, and a `score`: the probability-weighted level index. |

A score can fall between levels. For example, a score of 2.2 on a five-level scale is a little above level 2. jevtester also records the most probable level, and uses that level when it compares the answer with a case's expected level.

### Criteria

A question's *criteria* are its options or levels:

- A `choice` has a map of option names to descriptions, with at least two options.
- A `score` has a list of level descriptions, lowest first, with at least two levels. Level 0 is the first description.
- A `noul` can have optional `true` and `false` descriptions. Not every server accepts them.

The model reads the descriptions, not the option names or level numbers. So a level described only as `"2"` gives the model nothing to go on.

### Wording guidance

The vendors give this guidance for writing questions:

- Ask about one thing per question. Combine several answers in code instead.
- Describe concrete situations in criteria, not degrees like "moderately severe".
- Make choice options mutually exclusive.
- Offer an option to abstain, like `cannot_tell`, when a forced choice would be wrong.
- Expect answers to change with the wording and the order of the options.
- Tune thresholds separately for each model, because probabilities differ between models.

`jevtester suite check` tests a question set against this guidance. It reports these findings:

| Code | Finding |
|---|---|
| `multiple_dimensions` | The instructions contain more than one question mark. |
| `degree_words` | The criteria use degree words like "very", "somewhat", or "moderately". |
| `bare_number_levels` | Some score levels are only numbers. |
| `no_abstention` | A choice has no abstention option. |
| `duplicate_options` | Two options or levels have the same description. |

The checks are rules of thumb. A finding is a reason to look at the wording, not proof that it's wrong.

### Question sets and versions

A *question set* is a named group of questions, saved as a YAML file. jevtester identifies each version of a question set by a hash of its questions. The hash covers the questions in order, so reordering the options makes a new version.

jevtester records each version the first time it reads it. Every run records the version it asked. So you can rerun an older version, and you can compare two versions question by question.

## State

The *state* is what the model reads. It can be text, a JSON object, or a JSON array. A JSON object helps you keep facts separate:

```yaml
state:
  party: Three adventurers, torches lit
  monsters: Six goblins, weapons drawn, 40 feet away
  player_says: We come in peace. Take this sack of silver and let us pass to the stairs.
```

Each target has a context window, which limits how much input it reads. Some servers cut a long state to fit, without an error. jevtester estimates each request's size and warns you when that can happen. For a target that doesn't cut the state, jevtester refuses to send a request that is far over the window. Refusing it before sending costs nothing.

## Cases and suites

A *case* is one state with the answers you expect. Each expectation is keyed by a question's id and has:

- `answer`: `true` or `false` for a noul, an option name for a choice, or a level number for a score.
- `acceptable`: other answers that also count as correct.
- `tolerance`: for a score, how many levels away from `answer` still count as correct.

A case can also give an `expected_action`, which tests a policy.

A *suite* is a list of cases, the question set they're asked, an optional policy, and default targets. jevtester includes one suite, `suites/parley.yaml`. It asks what a player in a tabletop role-playing game is trying to do when they meet monsters, whether they offer a bribe, and how the monsters react.

## Probabilities and confidence

A decision model returns a probability for every answer. *Confidence* describes how concentrated those probabilities are. It doesn't tell you whether the answer is correct.

jevtester computes confidence itself for nouls and choices, so every target is measured the same way:

- For a noul, confidence is `|2p - 1|`, where `p` is the probability of yes. A coin flip (0.5) has confidence 0. A certain answer, either way, has confidence 1.
- For a choice with `n` options, confidence is `(p_max - 1/n) / (1 - 1/n)`, where `p_max` is the highest probability. It's 0 when every option is equally likely, and 1 when one option has all the probability.

For a score, jevtester uses the server's confidence, because the vendors don't publish the formula. jevtester also stores the server's confidence for any answer that has one, so you can see where a server's formula differs from jevtester's.

### Calibration

A model is *calibrated* when its probabilities match how often it's right. If a calibrated model says 0.8 on a hundred answers, about eighty of them are correct.

jevtester measures calibration with a *reliability table*. It sorts answers into ten equal-width probability bins and compares each bin's average probability with how often those answers were correct. The *expected calibration error* (ECE) is the average gap between the two, weighted by how many answers fall in each bin. Lower is better.

For a noul, the probability is the probability of yes, compared with whether the expected answer was yes. For a choice, it's the probability of the chosen option, compared with whether that choice was correct. Scores have no calibration table.

## Abstaining

Sometimes the state doesn't contain enough to answer. A forced choice then makes the model guess. An *abstention option* lets it say so instead.

jevtester treats a choice option as an abstention option when its name is one of `abstain`, `cannot_tell`, `cant_tell`, `unclear`, `unknown`, or `unsure`. The parley question set has `cannot_tell` for the player's intent.

When a choice has an abstention option, jevtester reports how often the target chose it, as the *abstention rate*. It reports this apart from accuracy. A policy can then escalate an abstention to a person.

## Metrics

jevtester scores each answer against the case's expectation, then computes metrics for each target and question. A metric that doesn't apply to a question type is left blank. Only successful results for cases with an expected answer for the question count, and `n` is the number of them. A failed request doesn't count. Consistency is the exception: it counts every successful result, with or without an expected answer.

| Metric | Question types | Means |
|---|---|---|
| Accuracy | All | The share of answers that match the expected answer or an acceptable one. For a score, the share whose most probable level is exactly the expected level. |
| Macro-F1 | Choice | The F1 score of each option, averaged so a rare option counts as much as a common one. F1 combines precision and recall. |
| Mean absolute error (MAE) | Score | The average distance in levels between the `score` and the expected level. |
| Within tolerance | Score | The share of answers whose most probable level is within the case's tolerance of the expected level, or is an acceptable level. |
| Brier score | Noul | The average of `(p - y)²`, where `p` is the probability of yes and `y` is 1 for an expected yes and 0 for a no. 0 is perfect. |
| Log loss | Noul | The average of `-log` of the probability given to the expected answer. It punishes confident wrong answers hard. Lower is better. |
| AUROC | Noul | The area under the ROC curve: how often the target gives a yes case a higher probability than a no case. 1 is perfect, and 0.5 is chance. Blank when every case expects the same answer. |
| ECE | Noul, choice | The expected calibration error, described in [Calibration](#calibration). Blank for a target that returns no probabilities. |
| Abstention rate | Choice | How often the target chose the abstention option. Blank when the question has none. |
| Consistency | All | The share of cases whose answer was the same in every repeat. Blank with one repeat. |

A noul answer counts as yes when the probability of yes is at least 0.5.

For each target, jevtester also reports:

- The number of results, errors, and skipped jobs. A target that fails its health check at the start of a run is skipped.
- The median (p50) and 95th percentile (p95) latency in milliseconds.
- The cost of the run, and the cost of 1,000 requests at the run's average cost per request. Cost comes from input tokens and the target's price in the config. A cached result costs nothing. When a target has no price, its cost is unknown.

### Comparing two runs

When you compare a run with a *baseline* run, jevtester lists each answer that changed, for the targets both runs ran. It compares the first repeat of each case. It labels each change:

- `fixed`: wrong in the baseline and right now.
- `broken`: right in the baseline and wrong now.
- `changed`: different, but neither or both were right, or the case expects nothing for that question.

For each target, it runs *McNemar's test* on the fixed and broken counts. The test gives a p-value: the chance of seeing a split at least this lopsided if the change made no difference. A small p-value suggests the change mattered. With few cases, the p-value stays high.

A *regression* is a target and question whose accuracy dropped by more than an allowed amount from the baseline. For a score, jevtester uses the within-tolerance accuracy. The allowed drop is `defaults.max_drop` in the config, 0.05 unless you set it. `jevtester compare` exits with code 1 when it finds a regression, so you can use it in continuous integration.

### Probes

A *probe* changes a case in a way that shouldn't change the answer, and measures how often the answer changes anyway. A high change rate points at a fragile question or model.

| Probe | Changes |
|---|---|
| `option_order` | Shuffles the order of each choice's options, three times per case. |
| `key_order` | Reverses the order of the keys in a JSON state. |
| `bare_levels` | Replaces each score level's description with its number. |
| `pad_state` | Pads the state with neutral text until the request fills about 90% of the target's context window. |

A probe makes no variant when it doesn't apply. For example, `bare_levels` needs a score question, and `pad_state` needs a target with a known context window. `jevtester probe` runs the first three by default. `pad_state` sends large requests, so you turn it on yourself.

## Policies

An *answer* is what a model returns for one question. A *decision* is the action your code takes from one or more answers, like "parley succeeds" or "escalate to the referee". A *policy* is a YAML file that describes how answers become a decision. jevtester applies it to each result, so you can measure decisions separately from answers.

A policy can't run code. Its conditions are data.

### Thresholds

*Thresholds* are named numbers. Bands and rules refer to them by name, so you can change one number in one place, and a sweep can move it.

Probabilities differ between models, so a threshold that works for one model may not work for another. A policy can set a threshold's value for one target under `per_target`.

### Bands

A *band* sets two confidence levels for a question, `act` and `confirm`:

- At or above `act`, the policy acts.
- At or above `confirm` but below `act`, the policy acts and marks the decision for confirmation.
- Below `confirm`, or with no answer, the policy escalates.

jevtester checks the bands before the rules. If any banded question escalates, the decision is the policy's `escalate` action.

### Composites

A *composite* is a weighted sum of answers, each scaled to the range 0 to 1:

- A noul adds its probability of yes.
- A score adds its `score` divided by its top level.
- A choice adds the probability of its chosen option.

The parley policy's `goodwill` composite adds half the chance of a bribe and half the monsters' reaction level.

### Rules

*Rules* choose the action. jevtester checks them in order, and the first rule whose conditions all hold gives the action. A condition can name:

- An option, or a list of options, for a choice.
- `true` or `false` for a noul.
- A range with `at_least` and `at_most` for a noul's probability, a score's `score`, a choice's probability, or a composite. Either end can be a number or a threshold's name.

When no rule matches, the decision is the policy's `default` action.

### Decision metrics

For each target, jevtester applies the policy to each case that has an `expected_action`, and reports:

- Decision accuracy: the share of cases whose action matches the expected action.
- The share decided: the share of cases the policy decided without a band escalation. A failed request counts as an escalation.
- The error rate when decided: the share of wrong actions among the cases it decided.
- The cost, when the policy has a cost matrix.

A *cost matrix* weights each kind of mistake. `costs[expected][chosen]` is the cost of choosing `chosen` when the case expected `expected`. A wrong action that isn't listed costs 1. For example, a wrong "parley succeeds" can cost more than an unneeded escalation.

### Sweeps

A *threshold sweep* replays one target's results from a finished run with one threshold set to each value in a range. It uses the policy as it is now, not the copy saved with the run. At each value, it reports the share decided, the error rate, and the cost. A higher threshold usually decides fewer cases with fewer errors. The sweep shows that trade-off, so you can pick a value without running the models again.
