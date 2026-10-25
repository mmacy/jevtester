# jevtester

jevtester tests decision models, the questions you write for them, and the decisions your code makes from their answers. It's a command-line tool, an HTTP API, and a web UI, and it runs on your own computer.

A *decision model* reads a state and a set of typed questions, and returns a probability for every allowed answer instead of generating text. jevtester supports these models:

- Microsoft-Decision-1 on your Azure AI Foundry resource.
- Clef, Clef-flash, and Clef-omni on Cloudflare Workers AI.
- Clef-flash on a local Ollama server.
- Clef and Clef-flash on a local MLX server, on a Mac with Apple silicon.

![The Compare view in the web UI. One request with three questions about goblins went to decision-1@foundry and clef-flash@workers-ai, and each option's probability from each target is shown side by side, with the expected answers tagged and the spread between targets.](docs/images/compare.png)

## Quick start

You need Python 3.14, [uv](https://docs.astral.sh/uv/), and at least one decision model you can reach. [Getting started](docs/getting-started.md) walks you through setting one up.

```sh
git clone https://github.com/mmacy/jevtester.git
cd jevtester
uv sync
cp jevtester.toml jevtester.local.toml   # then add your own target settings
uv run jevtester targets check
uv run jevtester run parley --target clef-flash@ollama
uv run jevtester report 0001
```

To use the web UI, build it once with Node 24 or later, then start the server at <http://127.0.0.1:8640>:

```sh
cd web && npm install && npm run build && cd ..
uv run jevtester serve
```

## Documentation

The documentation is at <https://mmacy.github.io/jevtester/>, and its source is in [`docs/`](docs/):

- [Getting started](docs/getting-started.md)
- [How-to guides](docs/how-to.md)
- [Concepts](docs/concepts.md)
- [Architecture](docs/architecture.md), for developers

## License

This repository is licensed under [CC BY-NC-SA 4.0](LICENSE).
