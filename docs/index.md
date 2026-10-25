# jevtester

jevtester tests decision models, the questions you write for them, and the decisions your code makes from their answers. It's a command-line tool, an HTTP API, and a web UI, and it runs on your own computer.

A *decision model* reads a state and a set of typed questions, and returns a probability for every allowed answer instead of generating text. jevtester supports these models:

- Microsoft-Decision-1 on your Azure AI Foundry resource.
- Clef, Clef-flash, and Clef-omni on Cloudflare Workers AI.
- Clef-flash on a local Ollama server.
- Clef and Clef-flash on a local MLX server, on a Mac with Apple silicon.

![The Compare view in the web UI. One request with three questions about goblins went to decision-1@foundry and clef-flash@workers-ai, and each option's probability from each target is shown side by side, with the expected answers tagged and the spread between targets.](images/compare.png)

## What it does

- Asks one question of one or more models, and shows each model's probabilities side by side.
- Runs a suite of test cases on several models, and measures accuracy, calibration, latency, and cost.
- Compares two runs and lists each answer that changed, so you can see whether a new wording or model is better.
- Probes for fragile questions by reordering options, reordering a state's keys, or replacing level descriptions with numbers.
- Applies a decision policy to the answers, measures the decisions, and sweeps a threshold to show the trade-off between deciding more cases and making fewer mistakes.
- Gives scripts and agents the same operations as the web UI, through the CLI with JSON output and through the HTTP API.

## Quick start

You need Python 3.14, [uv](https://docs.astral.sh/uv/), and at least one decision model you can reach. [Getting started](getting-started.md) walks you through setting one up.

```sh
git clone https://github.com/mmacy/jevtester.git
cd jevtester
uv sync
cp jevtester.toml jevtester.local.toml   # then add your own target settings
uv run jevtester targets check
uv run jevtester run parley --target clef-flash@ollama
uv run jevtester report 0001
```

To use the web UI, build it once with Node 24 or later, then start the server:

```sh
cd web && npm install && npm run build && cd ..
uv run jevtester serve
```

The server runs at <http://127.0.0.1:8640>.

## Documentation

- [Getting started](getting-started.md): install jevtester, run the included suite, and read the report.
- [How-to guides](how-to.md): set up each target, write suites and policies, compare runs, and call the HTTP API.
- [Concepts](concepts.md): decision models, questions, calibration, metrics, and policies.
- Reference: the [CLI](reference/cli.md), the [HTTP API](reference/http-api.md), the [configuration](reference/config.md), and the [suite format](reference/suite-format.md).
- [Architecture](architecture.md): how the code is organized, for developers.

## License

jevtester is licensed under [CC BY-NC-SA 4.0](https://github.com/mmacy/jevtester/blob/main/LICENSE).
