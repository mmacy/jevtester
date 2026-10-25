# Suite format reference

jevtester keeps its test material as YAML files in the suites directory, `suites/` unless the [config](config.md#paths) sets another path. You review them in git like code.

There are three kinds of file:

| File | Holds |
|---|---|
| `suites/<name>.yaml` | A *suite*: cases, the question set they're asked, an optional policy, and default targets. A *case* is one state with the answers and action it expects. |
| `suites/question-sets/<name>.yaml` | A *question set*: the questions, keyed by id. |
| `suites/policies/<name>.yaml` | A *policy*: rules that turn a result's answers into an action. |

The repository's `parley` suite is the example on this page. Its files are `suites/parley.yaml`, `suites/question-sets/parley.yaml`, and `suites/policies/parley.yaml` in the repository.

For the steps to write a suite, see the [how-to guides](../how-to.md). For why questions are worded the way they are, see [Concepts](../concepts.md#questions).

## Rules for every file

- A name uses lowercase letters, digits, `-`, and `_`, starts with a letter or digit, and has at most 64 characters, so it's a safe file name.
- The `name` inside a file must match its file name without `.yaml`. A file whose `name` is another suite, question set, or policy is invalid.
- A key the format doesn't have is an error. This catches a misspelled key, like `expect` in place of `expected`.
- An invalid suite or question set is reported with its file name, the path of the first bad field, and what's wrong, like `parley.yaml: cases.0.expected.reaction.tolerance: Input should be greater than or equal to 0`. An invalid policy is reported with the field path and what's wrong, without the file name. A YAML syntax error in a policy gives its line number.

Check a suite, its question set, and its policy together with [`jevtester suite check`](cli.md#jevtester-suite-check).

When jevtester adds a case to a suite, through [`jevtester case add`](cli.md#jevtester-case-add) or the HTTP API, it appends the case's text after the last case and keeps the rest of the file, comments included. When it saves a question set through the HTTP API, it rewrites the file from its parsed contents, so comments are lost. It saves a policy as you wrote it, comments included.

## Question sets

A question set is a named set of questions. Every case in a suite is asked every question in the suite's question set.

```yaml
name: parley
questions:
  intent:
    type: choice
    instructions: What is the player trying to do?
    criteria:
      parley: Talk, bargain, bribe, or negotiate
      evade: Run away or avoid the monsters
      fight: Attack the monsters
      wait: Hold position and watch
      cannot_tell: The player's words and actions don't show what they're trying to do
  bribe:
    type: noul
    instructions: Does the player offer the monsters something of value?
  reaction:
    type: score
    instructions: How are the monsters likely to react to what the player says and does?
    criteria:
    - Attack at once
    - Hostile, may attack
    - Uncertain, hold and posture
    - Indifferent, may let them pass
    - Friendly, accept the offer
```

| Key | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | The question set's name. It must match the file name. |
| `questions` | map | yes | The questions, at least one. Each key is the question's id, which its answer comes back under. The model never sees the id. The questions are sent in the file's order. |

### Versions

A question set's *version* is the SHA-256 hash of its questions in order. Any change to a question, or to their order, makes a new version. The name, comments, and layout aren't part of it. jevtester records each version the first time it sees one, so a run can use an earlier version with [`jevtester run --question-set-version`](cli.md#jevtester-run), and two versions can be compared. A file may have a `version` key, and jevtester ignores it and computes the hash.

### Questions

Every question has a `type` and `instructions`. What `criteria` holds depends on the type.

| Key | Type | Required | Description |
|---|---|---|---|
| `type` | string | yes | `noul`, `choice`, or `score`. |
| `instructions` | string | yes | The question the model reads. |
| `criteria` | depends on `type` | for `choice` and `score` | The options, the levels, or descriptions of yes and no. |

#### `noul`

A yes/no question. Its answer is the probability of yes, and evaluation reads the answer as yes when that probability is 0.5 or more. ("Noul" is the System One API's name for this type.)

`criteria` is optional. It's a map with up to two keys, `"true"` and `"false"`, each a description of what counts as that answer. Quote the keys, because YAML reads a bare `true` as a boolean, which isn't a valid key. Not every server accepts these descriptions.

```yaml
bribe:
  type: noul
  instructions: Does the player offer the monsters something of value?
  criteria:
    "true": The player offers coins, items, or a service
    "false": The player offers nothing, or only words
```

#### `choice`

A question that picks one option. `criteria` maps each option's name to its description, with at least two options. The options are sent in the file's order. The answer is the chosen option's name, with a probability for each option.

Include an option for "can't tell", so the model has a correct answer when the state doesn't show which option applies. jevtester finds that option by its name: `abstain`, `cannot_tell`, `cant_tell`, `unclear`, `unknown`, or `unsure`. It reports how often a target chose it as `abstention_rate`.

#### `score`

A question that places the state on an ordered list of levels. `criteria` is a list of level descriptions, lowest first, with at least two. Level `i` is `criteria[i]`, counting from 0. The answer has a probability for each level, the most probable `level`, and a `score`, the probability-weighted level index, which can fall between levels.

Describe each level as a situation, not a degree. "Hostile, may attack" scores better than "Very hostile".

### Wording checks

[`jevtester suite check`](cli.md#jevtester-suite-check) runs these checks on every question. They're heuristics. Each finding is a prompt to look at a question, and none makes a suite invalid.

| Code | Finds |
|---|---|
| `multiple_dimensions` | Instructions with more than one question mark, which may ask two things at once. |
| `degree_words` | Criteria with words that describe a degree instead of a situation, like "very" or "somewhat". |
| `bare_number_levels` | Score levels that are only numbers, like `1` to `5`. |
| `no_abstention` | A choice question with no abstention option. |
| `duplicate_options` | Two options or levels with the same description. |

## Suites

A suite names its question set and policy, and lists its cases.

```yaml
name: parley
question_set: parley
policy: parley
targets:
- decision-1@foundry
- clef-flash@workers-ai
cases:
- id: goblin-bribe
  state:
    party: Three adventurers, torches lit
    monsters: Six goblins, weapons drawn, 40 feet away
    player_says: We come in peace. Take this sack of silver and let us pass to the stairs.
  expected:
    intent:
      answer: parley
    bribe:
      answer: true
    reaction:
      answer: 3
      tolerance: 1
  expected_action: parley_succeeds
  tags:
  - bribe
```

The repository's suite has three more cases in the same form.

| Key | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | The suite's name. It must match the file name. |
| `question_set` | string | yes | The name of the question set every case is asked. |
| `policy` | string | no | The name of the policy that turns answers into actions. Without it, runs have no decision metrics. |
| `targets` | list of strings | no | The targets a run uses when you don't name any. Without it, runs use the config's `defaults.targets`. |
| `cases` | list | no | The cases, in the order a run sends them. |

### Cases

| Key | Type | Required | Description |
|---|---|---|---|
| `id` | string | yes | The case's id. It must be unique in the suite and not empty. |
| `state` | text, map, or list | yes | What the model reads: text, a JSON object, or a JSON array, written in YAML. |
| `expected` | map | no | The answer the case expects to each question, keyed by question id. A question with no entry isn't scored for this case. See [Expectations](#expectations). |
| `expected_action` | string | no | The action the suite's policy should choose. Decision metrics count only cases that have one. |
| `tags` | list of strings | no | Labels for grouping cases. |
| `images` | list of strings | no | Paths of image files sent with the state. No target sends images yet, so a case with images fails on every target. |
| `provenance` | string | no | Who wrote the case: `human`, the default, or `claude-draft`. Runs and evaluation skip `claude-draft` cases until a person changes them to `human`. |

### Expectations

| Key | Type | Default | Description |
|---|---|---|---|
| `answer` | boolean, string, or integer | none | `true` or `false` for a noul, an option name for a choice, or a level index from 0 for a score. Without it, the question isn't scored for this case. |
| `acceptable` | list | none | Other answers that count as correct: option names for a choice, or level indexes for a score. For a score, within-tolerance accuracy uses it, and plain accuracy doesn't. |
| `tolerance` | integer | `0` | For a score: an answer within this many levels of `answer` counts as correct. At least 0. Within-tolerance accuracy uses it, and plain accuracy doesn't. |

An answer is correct when it equals `answer` or one of `acceptable`, or for a score, when it's within `tolerance` levels. A missing answer is wrong.

`jevtester suite check` reports an expectation that names a question the question set doesn't ask, an option the choice doesn't have, a level out of range, or a value of the wrong type, like a number for a noul. It also reports a case id that's used twice. Loading the suite doesn't check case ids, so run `suite check` after you edit a suite by hand.

## Policies

A policy turns one result's answers into an action, like `parley_succeeds`, `battle`, or `escalate`. A run applies the suite's policy to every result, and measures its actions against each case's `expected_action`. The conditions in a policy are data, not expressions, so a policy can't run code.

```yaml
# Turns the parley questions into a referee action for the encounter.
name: parley

thresholds:
  # Intent confidence at or above act decides; below confirm escalates to the referee.
  act: 0.8
  confirm: 0.5
  # How well the monsters must take the offer for a parley to succeed, from 0 to 1.
  goodwill: 0.55

per_target:
  clef-flash@workers-ai:
    goodwill: 0.5

bands:
  intent: {act: act, confirm: confirm}

composites:
  # The chance of a bribe and the reaction level, each from 0 to 1.
  goodwill:
    bribe: 0.5
    reaction: 0.5

rules:
  - action: battle
    when: {intent: fight}
  - action: evade
    when: {intent: evade}
  - action: wait
    when: {intent: wait}
  - action: escalate
    when: {intent: cannot_tell}
  - action: parley_succeeds
    when: {intent: parley, goodwill: {at_least: goodwill}}
  - action: parley_fails
    when: {intent: parley}

# The cost of each wrong action, as costs[expected][chosen]. Any other wrong action costs 1.
costs:
  parley_succeeds:
    battle: 5
    parley_fails: 2
  battle:
    parley_succeeds: 5
```

| Key | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | The policy's name. It must match the file name. |
| `thresholds` | map of numbers | `{}` | Named numbers that bands and ranges refer to by name, so [`jevtester policy sweep`](cli.md#jevtester-policy-sweep) can move them. |
| `per_target` | map | `{}` | Threshold values for single targets, keyed by target name, for targets whose probabilities run differently. Each value replaces the shared one for that target. Each key inside must be a threshold in `thresholds`. |
| `bands` | map | `{}` | Confidence bands, keyed by question id. See [Bands](#bands). |
| `composites` | map | `{}` | Weighted sums of answers, keyed by name. See [Composites](#composites). |
| `rules` | list | required | The rules, at least one, checked in order. See [Rules](#rules). |
| `default` | string | `escalate` | The action when no rule matches. |
| `escalate` | string | `escalate` | The action a band chooses when a question's confidence is too low. |
| `costs` | map | none | The cost of choosing an action when the case expected another, as `costs[expected][chosen]`. A wrong choice that isn't listed costs 1. Without `costs`, the decision metrics have no cost. |

A policy's version is the SHA-256 hash of the parsed policy. The name, comments, and layout aren't part of it. A run saves a copy of the policy as it was when the run started, and the run's decision metrics use that copy. A [threshold sweep](cli.md#jevtester-policy-sweep) uses the policy as it is now.

### Bands

A band sets two confidence levels for one question, `act` and `confirm`. Each is a number or the name of a threshold. jevtester checks the bands before the rules:

- A question with no answer, or with confidence below `confirm`, escalates: the action is `escalate`, and no rule is checked.
- Confidence from `confirm` up to `act` decides, and marks the decision's band as `confirm`, for a person to confirm.
- Confidence at `act` or above decides, with the band `act`.

The decision's band is the lowest band among the banded questions. The confidence is jevtester's for a choice or a noul, and the server's for a score. A score whose server sends no confidence escalates.

### Composites

A composite is a weighted sum of answers, which a rule can test with a range. Each composite maps question ids to weights. Each answer adds its weight times a value from 0 to 1:

- A noul adds its probability of yes.
- A score adds its `score` divided by its top level index.
- A choice adds the probability of its chosen option.

A composite is unknown when an answer it needs is missing, and a rule that tests it doesn't match. A composite can't have the same name as a question that a band or composite reads. Don't give it the name of any question: a rule condition on that name tests the composite, and only a range can match it.

In the example, `goodwill` is half the probability of a bribe plus half the reaction level, scaled from 0 to 1.

### Rules

Each rule has an `action` and a `when` map of conditions, keyed by question id or composite name. A rule matches when every condition holds, and the first rule that matches gives the action. A rule with an empty `when` always matches, so it works as a last rule.

| Condition | Written as | Holds when |
|---|---|---|
| An option | `intent: fight` | A choice's answer is that option. |
| Any of several options | `intent: [evade, wait]` | A choice's answer is one of them. |
| Yes or no | `bribe: true` | A noul's answer is yes (`true`) or no (`false`). |
| A range | `goodwill: {at_least: goodwill}` | The value is between `at_least` and `at_most`, both inclusive. Either can be left out. Each is a number or the name of a threshold. |

A range tests a noul's probability of yes, a choice's probability of its chosen option, a score's `score`, or a composite's value. A condition on a missing answer doesn't hold.

The policy is checked when it's loaded. A threshold name in a band, range, or `per_target` must be in `thresholds`, and every rule needs a non-empty `action`. `jevtester suite check` also reports a question the policy reads that the suite's question set doesn't ask.
