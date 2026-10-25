"""Test decision models, their questions, and the decisions built on them.

A target is one decision model on one runtime, like decision-1@foundry, and the
config file lists them. A suite is a YAML file in suites/ with cases: states,
with the answers and action each one expects. A run sends every case to each
target and scores the answers.

Start with "jevtester targets check". Try a question with "jevtester decide",
run a suite with "jevtester run parley", and read its scores with
"jevtester report <run>". Run "jevtester <command> --help" for each command.

Every command writes its result to stdout, and its progress and warnings to
stderr. With --format json, the result is the same JSON the HTTP API returns.

exit codes:
  0  success
  1  "jevtester compare" found a regression
  2  invalid command line, input, or config, or a suite, run, policy, or
     target that doesn't exist; also an invalid suite in "jevtester suite check"
  3  "jevtester decide" got no answer from any target, or "jevtester run" got
     no answer for any job
"""

import argparse
import asyncio
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NoReturn, cast

from pydantic import BaseModel, ValidationError

from jevtester import __version__
from jevtester.errors import ServiceError
from jevtester.evaluate.scoring import answer_value
from jevtester.normalize import ChoiceAnswer, NoulAnswer, ScoreAnswer, TargetResult
from jevtester.schemas import (
    AnswerValue,
    DecideBody,
    DecideResponse,
    ProbeCreate,
    ProbeReport,
    ProbeVariant,
    ResultEvent,
    RunComparison,
    RunCreate,
    RunSummary,
    SweepBody,
    TargetList,
    TargetSkippedEvent,
)
from jevtester.service import Service
from jevtester.spec import Case, ChoiceQuestion, ConfigError, NoulQuestion, Question, ScoreQuestion

EXIT_OK = 0
EXIT_CHECK_FAILED = 1
EXIT_INVALID = 2
EXIT_ALL_FAILED = 3


class _InputError(Exception):
    """The command line or an input file is invalid."""


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for every jevtester command.

    Returns:
        The top-level parser. `argparse` exits with code 2 on an invalid command line, which is the plan's exit code
        for that case.
    """
    raw = argparse.RawDescriptionHelpFormatter
    parser = argparse.ArgumentParser(prog="jevtester", description=__doc__, formatter_class=raw)
    parser.add_argument("--version", action="version", version=f"jevtester {__version__}")
    parser.add_argument(
        "--config",
        type=Path,
        metavar="PATH",
        help=(
            "The config file, which lists the targets. Without it: $JEVTESTER_CONFIG, or else jevtester.toml in the "
            "working directory with jevtester.local.toml merged over it. Suite and run paths in the config are "
            "relative to its directory."
        ),
    )
    commands = parser.add_subparsers(dest="command", metavar="<command>", title="commands")

    def add_format(command: argparse.ArgumentParser) -> None:
        command.add_argument(
            "--format",
            choices=["text", "json"],
            default="text",
            help="text (the default) for people, or json for scripts: the same JSON the HTTP API returns.",
        )

    decide = commands.add_parser(
        "decide",
        formatter_class=raw,
        help="Send one state and its questions to targets, and print their answers.",
        description="""\
Send one state and its questions to one or more targets at once, and print each
target's answers, latency, tokens, and cost. A state is what the model reads:
text, a JSON object, or a JSON array.

Ask one question with --state and --question. It's a yes/no question unless
--option makes it a choice or --level makes it a score. To ask several
questions, put the state and questions in a JSON file and pass --request.

A target that fails prints "failed" with its error code, and the others still
answer. To keep a result as a test case, save the JSON output and pass it to
"jevtester case add --from-decide".

Exits with 3 when no target answered, and 2 for invalid input or an unknown
target.""",
        epilog="""\
examples:
  # Ask the default targets a yes/no question about a text state
  jevtester decide --id bribe \\
      --state "Six goblins block the stairs. The player offers them silver." \\
      --question "Does the player offer the monsters something of value?"

  # Ask a choice question of two targets
  jevtester decide --state @state.json --id intent \\
      --question "What is the player trying to do?" \\
      --option "parley=Talk or bargain" --option "fight=Attack the monsters" \\
      --target decision-1@foundry --target clef-flash@workers-ai

  # Send a request file to every target, and save the result for case add
  jevtester decide --request goblin.json --targets all --format json \\
      > decide.json""",
    )
    decide.add_argument(
        "--state",
        metavar="STATE",
        help="The state: text, @PATH to read a file (parsed as JSON when it's valid JSON), or - to read stdin.",
    )
    decide.add_argument("--question", metavar="TEXT", help="The question the model reads. Requires --state.")
    decide.add_argument("--id", default="question", help="The id the answer comes back under. Defaults to question.")
    decide.add_argument(
        "--option",
        action="append",
        default=[],
        metavar="NAME=DESCRIPTION",
        help="A choice option, like parley=Talk or bargain. Repeat for each option; a choice needs two or more.",
    )
    decide.add_argument(
        "--level",
        action="append",
        default=[],
        metavar="DESCRIPTION",
        help="A score level, lowest first. Repeat for each level; a score needs two or more. Not with --option.",
    )
    decide.add_argument(
        "--request",
        metavar="PATH",
        help=(
            "A JSON file with state and questions (and optionally images), or - to read stdin. A model field is "
            "ignored. Can't be used with --state, --question, --option, or --level."
        ),
    )
    decide.add_argument(
        "--target",
        action="append",
        default=[],
        metavar="NAME",
        help="A target to ask, like decision-1@foundry. Repeat for each. Defaults to the config's defaults.targets.",
    )
    decide.add_argument("--targets", choices=["all"], help="Ask every configured target. Overrides --target.")
    decide.add_argument(
        "--timeout",
        type=float,
        metavar="SECONDS",
        help="Seconds to wait for each target. Defaults to the config's defaults.timeout_s (60 unless set).",
    )
    add_format(decide)

    targets = commands.add_parser(
        "targets",
        help="List the configured targets, or run their health checks.",
        description=(
            "Work with targets. A target is one decision model on one runtime, like decision-1@foundry. The config "
            "file lists them. Run 'jevtester targets check' before your first decide or run."
        ),
    )
    target_commands = targets.add_subparsers(
        dest="targets_command", metavar="<command>", required=True, title="commands"
    )
    add_format(
        target_commands.add_parser(
            "list",
            formatter_class=raw,
            help="List targets and their capabilities, without a health check.",
            description="""\
Print each configured target with its status and a note: why it's down, where
its credential comes from, or a warning that applies to every request. This
command doesn't run a health check, so each target shows "unchecked". Use
"jevtester targets check" to check them.""",
            epilog="examples:\n  jevtester targets list\n  jevtester targets list --format json",
        )
    )
    add_format(
        target_commands.add_parser(
            "check",
            formatter_class=raw,
            help="Run every target's health check and print the results.",
            description="""\
Run every target's health check at once and print each target's status:
ready, warning (ready, with a warning), or down, with the reason. A health
check sends no decision request. Foundry needs an az sign-in, Ollama must have
the model pulled, the MLX server must have the target's model loaded, and
Workers AI needs a Wrangler sign-in or CLOUDFLARE_API_TOKEN and
cloudflare.account_id. A check that takes longer than 15 seconds marks the
target down.""",
            epilog="examples:\n  jevtester targets check",
        )
    )

    run = commands.add_parser(
        "run",
        formatter_class=raw,
        help="Run a suite on its targets and print the run's id and counts.",
        description="""\
Send every case in a suite to each target, wait for the run to finish, and
print the run's id and job counts. A job is one case on one target for one
repeat. Progress goes to stderr, one line per job.

The run first checks each target's health and skips the jobs of a target
that's down. Each result is cached by target, request, and repeat, so a rerun
of an unchanged suite sends nothing; --no-cache sends every request again.
Requests wait up to the config's defaults.timeout_s.

Pass the run's id to "jevtester report", "jevtester compare", or
"jevtester policy sweep". Exits with 3 when the run had jobs and none got an
answer, and 2 for an unknown suite, target, or baseline.""",
        epilog="""\
examples:
  # Run the parley suite on the suite's targets
  jevtester run parley

  # Run it on one target three times, and compare with run 0001 in the report
  jevtester run suites/parley.yaml --target decision-1@foundry \\
      --repeats 3 --baseline 0001""",
    )
    run.add_argument(
        "suite",
        help=(
            "The suite's name, like parley, or its file name, like suites/parley.yaml. jevtester reads the suite from "
            "the config's suites directory either way."
        ),
    )
    run.add_argument(
        "--target",
        action="append",
        default=[],
        metavar="NAME",
        help="A target to run. Repeat for each. Defaults to the suite's targets, or else the config's.",
    )
    run.add_argument(
        "--repeats",
        type=int,
        metavar="N",
        help="Times to send each case to each target, at least 1. Defaults to the config's defaults.repeats.",
    )
    run.add_argument(
        "--question-set-version",
        metavar="HASH",
        help="An earlier question set version to run, as its hash or a prefix of 8 or more characters.",
    )
    run.add_argument(
        "--baseline",
        metavar="RUN",
        help="A run to compare with. The run's report then lists the answers that changed from it.",
    )
    run.add_argument("--no-cache", action="store_true", help="Send every request, even when a cached result exists.")
    add_format(run)

    probe = commands.add_parser(
        "probe",
        formatter_class=raw,
        help="Run probes on a suite and report how often the answers change.",
        description="""\
Run each case as written and as each probe changes it, then print how often
each target's answers changed. A probe changes something that shouldn't change
the answers:

  option_order  3 variants, each a different order of every choice's options
  key_order     1 variant with every JSON object's keys reversed
  bare_levels   1 variant with each score level's description replaced by its number
  pad_state     1 variant padded to about 90% of the target's context window

A probe makes no variant of a case it can't change, like key_order on a text
state. Progress goes to stderr. The JSON output is the same as
GET /api/runs/{id}/probes.""",
        epilog="""\
examples:
  jevtester probe parley
  jevtester probe parley --variant option_order --target decision-1@foundry""",
    )
    probe.add_argument("suite", help="The suite's name, or its file name. See 'jevtester run --help'.")
    probe.add_argument(
        "--variant",
        action="append",
        choices=["option_order", "key_order", "bare_levels", "pad_state"],
        help=(
            "A probe to run. Repeat for each. Defaults to option_order, key_order, and bare_levels; pad_state sends "
            "large requests, so it runs only when named."
        ),
    )
    probe.add_argument(
        "--target",
        action="append",
        default=[],
        metavar="NAME",
        help="A target to probe. Repeat for each. Defaults to the suite's targets, or else the config's.",
    )
    probe.add_argument("--no-cache", action="store_true", help="Send every request, even when a cached result exists.")
    add_format(probe)

    compare = commands.add_parser(
        "compare",
        formatter_class=raw,
        help="Compare a run with a baseline run: changed answers, McNemar's test, and regressions.",
        description="""\
Compare a run with a baseline run. Print each answer that changed on the
targets both runs ran (fixed, broken, or changed), McNemar's exact test for
each target, and each regression: a target and question whose accuracy, or
within-tolerance accuracy for a score, dropped by more than --max-drop.

Exits with 1 when there's a regression, so a script or CI job can fail on it,
and 2 when either run doesn't exist.""",
        epilog="""\
examples:
  jevtester compare 0002 0001
  jevtester compare 0002 0001 --max-drop 0.1 --format json""",
    )
    compare.add_argument("run", help="The id of the run to check, like 0002.")
    compare.add_argument("baseline", help="The id of the run to compare it with, like 0001.")
    compare.add_argument(
        "--max-drop",
        type=float,
        metavar="SHARE",
        help="The largest allowed drop, as a share like 0.05. Defaults to the config's defaults.max_drop.",
    )
    add_format(compare)

    report = commands.add_parser(
        "report",
        formatter_class=raw,
        help="Print a run's report as Markdown or JSON.",
        description="""\
Print a run's summary and its metrics for each target and question, and the
policy's decisions when the suite has a policy. When the run has a baseline,
the report also lists the answers that changed from it.""",
        epilog="""\
examples:
  jevtester report 0002 > report.md
  jevtester report 0002 --format json""",
    )
    report.add_argument("run", help="The run's id, like 0002.")
    report.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="markdown (the default) for people, or json for scripts: the same JSON as GET /api/runs/{id}/report.",
    )

    suite = commands.add_parser(
        "suite",
        help="Check a suite.",
        description="Work with suites. A suite is a YAML file in suites/ with cases and the question set they ask.",
    )
    suite_commands = suite.add_subparsers(dest="suite_command", metavar="<command>", required=True, title="commands")
    check = suite_commands.add_parser(
        "check",
        formatter_class=raw,
        help="Validate a suite and run the question-wording checks.",
        description="""\
Check that a suite, its question set, and its policy load, that every case's
expectations fit the questions, and that the policy reads only questions the
question set asks. Then run the question-wording checks, whose findings are
prompts to look at a question and don't make the suite invalid.

Exits with 2 when the suite is invalid or doesn't exist.""",
        epilog="examples:\n  jevtester suite check parley",
    )
    check.add_argument("suite", help="The suite's name, or its file name. See 'jevtester run --help'.")
    add_format(check)

    policy = commands.add_parser(
        "policy",
        help="Tune a decision policy.",
        description=(
            "Work with policies. A policy is a YAML file in suites/policies/ that turns a result's answers into an "
            "action."
        ),
    )
    policy_commands = policy.add_subparsers(dest="policy_command", metavar="<command>", required=True, title="commands")
    sweep = policy_commands.add_parser(
        "sweep",
        formatter_class=raw,
        help="Sweep a policy threshold over a run's answers and print the trade-off.",
        description="""\
Measure one target's decisions in a run as one of the policy's thresholds
moves from --start to --stop. For each value, print the share of cases the
policy decided without escalating, the error rate among those, and the cost
from the policy's cost matrix. The sweep uses the policy file as it is now, so
you can tune a threshold without running the suite again.

A sweep has at most 1,000 points. Exits with 2 for an unknown policy, run, or
threshold, or a target the run didn't run.""",
        epilog="""\
examples:
  jevtester policy sweep parley --run 0002 --target decision-1@foundry \\
      --threshold goodwill --start 0.3 --stop 0.7 --step 0.1""",
    )
    sweep.add_argument("policy", help="The policy's name, like parley.")
    sweep.add_argument("--run", required=True, metavar="RUN", help="The id of the run whose answers to use.")
    sweep.add_argument("--target", required=True, metavar="NAME", help="A target the run ran.")
    sweep.add_argument("--threshold", required=True, metavar="NAME", help="The name of the threshold to move.")
    sweep.add_argument("--start", type=float, default=0.0, metavar="VALUE", help="The first value. Defaults to 0.")
    sweep.add_argument("--stop", type=float, default=1.0, metavar="VALUE", help="The last value. Defaults to 1.")
    sweep.add_argument(
        "--step", type=float, default=0.05, metavar="VALUE", help="The gap between values, over 0. Defaults to 0.05."
    )
    add_format(sweep)

    case = commands.add_parser(
        "case",
        help="Add a case to a suite.",
        description="Work with cases. A case is one state with the answers and action it expects.",
    )
    case_commands = case.add_subparsers(dest="case_command", metavar="<command>", required=True, title="commands")
    add = case_commands.add_parser(
        "add",
        formatter_class=raw,
        help="Save a case to a suite, including one promoted from a decide result.",
        description="""\
Add a case to the end of a suite's file. jevtester rewrites the file, so
comments in it are lost.

Give the state with --state, or promote a decide result with --from-decide,
which reads the output of "jevtester decide --format json" and takes its
state. --expect-from then takes the expected answers from one target's answers
in that output, and --expect sets or replaces single answers.

Exits with 2 for invalid input or a case id the suite already has.""",
        epilog="""\
examples:
  # Add a case with its expected answers
  jevtester case add parley --id troll-toll \\
      --state "A troll blocks the bridge and asks for a toll." \\
      --expect intent=parley --expect bribe=true --expect reaction=2 \\
      --tolerance reaction=1 --expected-action parley_succeeds --tag bribe

  # Promote a decide result, keeping Foundry's answers but one
  jevtester case add parley --id goblin-silver --from-decide decide.json \\
      --expect-from decision-1@foundry --expect reaction=3""",
    )
    add.add_argument("suite", help="The suite's name, or its file name. See 'jevtester run --help'.")
    add.add_argument("--id", required=True, help="The case's id. It must be new in the suite.")
    add.add_argument(
        "--state",
        metavar="STATE",
        help=(
            "The state: text, @PATH to read a file (parsed as JSON when it's valid JSON), or - to read stdin. "
            "Give this or --from-decide."
        ),
    )
    add.add_argument(
        "--from-decide",
        metavar="PATH",
        help="A file of 'jevtester decide --format json' output, or - to read stdin. The case takes its state.",
    )
    add.add_argument(
        "--expect-from",
        metavar="TARGET",
        help="Expect the answers this target gave in --from-decide. Requires --from-decide.",
    )
    add.add_argument(
        "--expect",
        action="append",
        default=[],
        metavar="QUESTION=ANSWER",
        help=(
            "An expected answer: true or false (or yes or no) for a yes/no question, an option name for a choice, or "
            "a level number from 0 for a score. Repeat for each question."
        ),
    )
    add.add_argument(
        "--tolerance",
        action="append",
        default=[],
        metavar="QUESTION=LEVELS",
        help="Levels of slack for a score question's answer, a whole number. Repeat for each question.",
    )
    add.add_argument(
        "--expected-action", metavar="ACTION", help="The action the suite's policy should choose, like parley_succeeds."
    )
    add.add_argument("--tag", action="append", default=[], help="A tag for grouping cases. Repeat for each.")
    add_format(add)

    serve = commands.add_parser(
        "serve",
        formatter_class=raw,
        help="Start the HTTP API and the web UI on 127.0.0.1.",
        description="""\
Start the HTTP API, with every route under /api, and the web UI at /. The
server listens only on 127.0.0.1 and runs until you stop it with Ctrl-C. It
serves the UI only when the frontend was built (npm run build in web/) before
the server started.""",
        epilog="examples:\n  jevtester serve\n  jevtester serve --port 8650",
    )
    serve.add_argument("--port", type=int, default=None, help="The port to listen on. Defaults to 8640.")
    return parser


def _read_input(value: str) -> str:
    if value == "-":
        return sys.stdin.read()
    if value.startswith("@"):
        try:
            return Path(value[1:]).read_text()
        except OSError as error:
            raise _InputError(f"Can't read {value[1:]}: {error.strerror}") from error
    return value


def _read_state(value: str) -> Any:
    text = _read_input(value)
    if value == "-" or value.startswith("@"):
        try:
            return json.loads(text)
        except ValueError:
            return text
    return text


def _decide_body(args: argparse.Namespace) -> DecideBody:
    targets: list[str] = ["all"] if args.targets == "all" else list(args.target)
    if args.request:
        if args.state or args.question or args.option or args.level:
            raise _InputError("Give --request, or --state and --question, not both.")
        try:
            loaded = json.loads(
                _read_input(args.request if args.request == "-" else f"@{args.request.removeprefix('@')}")
            )
        except ValueError as error:
            raise _InputError(f"The request isn't valid JSON: {error}") from error
        if not isinstance(loaded, dict):
            raise _InputError("The request must be a JSON object with state and questions.")
        fields = {key: value for key, value in cast(dict[str, Any], loaded).items() if key != "model"}
        return DecideBody.model_validate({**fields, "targets": targets, "timeout_s": args.timeout})
    if not args.state or not args.question:
        raise _InputError("Give --state and --question, or --request.")
    if args.option and args.level:
        raise _InputError("Give --option for a choice or --level for a score, not both.")
    question: dict[str, Any] = {"type": "noul", "instructions": args.question}
    if args.option:
        criteria: dict[str, str] = {}
        for option in args.option:
            name, separator, description = option.partition("=")
            if not separator or not name:
                raise _InputError(f"--option needs NAME=DESCRIPTION, got {option!r}.")
            criteria[name] = description
        question = {"type": "choice", "instructions": args.question, "criteria": criteria}
    elif args.level:
        question = {"type": "score", "instructions": args.question, "criteria": list(args.level)}
    return DecideBody.model_validate(
        {
            "state": _read_state(args.state),
            "questions": {args.id: question},
            "targets": targets,
            "timeout_s": args.timeout,
        }
    )


def _describe_validation(error: ValidationError) -> str:
    lines = [
        f"{'.'.join(str(part) for part in item['loc']) or 'input'}: {item['msg']}"
        for item in error.errors(include_url=False)
    ]
    return "\n".join(lines)


def _print_json(model: BaseModel) -> None:
    print(model.model_dump_json(indent=2))


def _format_result(result: TargetResult) -> list[str]:
    if not result.ok:
        error = result.error
        reason = f"{error.code}: {error.message}" if error else "failed"
        return [f"{result.target}  failed  {reason}"]
    latency = f"{result.latency_ms:,.0f} ms" if result.latency_ms is not None else "latency unknown"
    tokens = f"{result.usage.input_tokens or 0} in, {result.usage.output_tokens or 0} out"
    cost = f"${result.cost_usd:.7f}" if result.cost_usd is not None else "cost unknown"
    lines = [f"{result.target}  {latency}  {tokens}  {cost}"]
    for key, answer in result.answers.items():
        match answer:
            case NoulAnswer():
                verdict = "yes" if answer.probability >= 0.5 else "no"
                lines.append(f"  {key}: {verdict}  p(yes) {answer.probability:.4f}  confidence {answer.confidence:.4f}")
            case ChoiceAnswer():
                spread = ", ".join(f"{option} {p:.4f}" for option, p in answer.probabilities.items())
                lines.append(f"  {key}: {answer.choice}  confidence {answer.confidence:.4f}  ({spread})")
            case ScoreAnswer():
                level = f"level {answer.level}: {answer.legend[answer.level]}" if answer.level is not None else ""
                confidence = answer.server_confidence
                shown = f"  server confidence {confidence:.4f}" if confidence is not None else ""
                lines.append(f"  {key}: {answer.score:.2f}  {level}{shown}")
    lines.extend(f"  warning {warning.code}: {warning.message}" for warning in result.warnings)
    return lines


def _print_decide(response: DecideResponse) -> None:
    for result in response.results:
        print("\n".join(_format_result(result)))


def _print_targets(targets: TargetList) -> None:
    width = max(len(info.name) for info in targets.targets)
    for info in targets.targets:
        note = info.reason or info.credential or ", ".join(warning.message for warning in info.warnings)
        print(f"{info.name:<{width}}  {info.status:<9}  {note}".rstrip())


def _fail(message: str) -> NoReturn:
    print(f"jevtester: {message}", file=sys.stderr)
    sys.exit(EXIT_INVALID)


def _load_service(path: Path | None) -> Service:
    try:
        return Service.load(path)
    except ConfigError as error:
        _fail(str(error))
    except ValidationError as error:
        _fail(f"The config is invalid:\n{_describe_validation(error)}")


def _decide(args: argparse.Namespace) -> int:
    try:
        body = _decide_body(args)
    except _InputError as error:
        _fail(str(error))
    except ValidationError as error:
        _fail(f"The request is invalid:\n{_describe_validation(error)}")
    service = _load_service(args.config)
    try:
        response = asyncio.run(service.decide(body))
    except ServiceError as error:
        _fail(str(error))
    if args.format == "json":
        _print_json(response)
    else:
        _print_decide(response)
    return EXIT_ALL_FAILED if not any(result.ok for result in response.results) else EXIT_OK


def _targets(args: argparse.Namespace) -> int:
    service = _load_service(args.config)
    targets = asyncio.run(service.check_targets()) if args.targets_command == "check" else service.list_targets()
    if args.format == "json":
        _print_json(targets)
    else:
        _print_targets(targets)
    return EXIT_OK


def _suite_name(value: str) -> str:
    path = Path(value)
    return path.stem if path.suffix in (".yaml", ".yml") else value


def _print_run(summary: RunSummary) -> None:
    counts = summary.counts
    cost = f"${summary.cost_usd:.6f}" if summary.cost_usd is not None else "cost unknown"
    print(
        f"Run {summary.id} {summary.status}: {counts.jobs} jobs, {counts.sent} sent, {counts.cached} from cache, "
        f"{counts.failed} failed, {counts.skipped} skipped, {cost}"
    )
    for row in counts.targets:
        note = f"  skipped: {row.skip_reason}" if row.skip_reason else ""
        print(f"  {row.target}  {row.sent} sent, {row.cached} cached, {row.failed} failed{note}")


async def _run_and_follow(service: Service, body: RunCreate) -> RunSummary:
    created = await service.start_run(body)
    print(f"Run {created.id} started", file=sys.stderr)
    async for event in service.run_events(created.id):
        match event:
            case ResultEvent():
                state = "cached" if event.cached else "ok" if event.result.ok else "failed"
                done = f"{event.counts.done}/{event.counts.jobs}"
                print(f"{done}  {event.case_id}  {event.target}  {state}", file=sys.stderr)
            case TargetSkippedEvent():
                print(f"Skipped {event.target}: {event.reason}", file=sys.stderr)
            case _:
                pass
    return await service.wait_run(created.id)


def _run(args: argparse.Namespace) -> int:
    try:
        body = RunCreate(
            suite=_suite_name(args.suite),
            targets=list(args.target),
            repeats=args.repeats,
            question_set_version=args.question_set_version,
            baseline=args.baseline,
            no_cache=args.no_cache,
        )
    except ValidationError as error:
        _fail(f"The run is invalid:\n{_describe_validation(error)}")
    service = _load_service(args.config)
    try:
        summary = asyncio.run(_run_and_follow(service, body))
    except ServiceError as error:
        _fail(str(error))
    if args.format == "json":
        _print_json(summary)
    else:
        _print_run(summary)
    counts = summary.counts
    return EXIT_ALL_FAILED if counts.jobs and counts.sent + counts.cached == 0 else EXIT_OK


DEFAULT_PROBES: list[ProbeVariant] = ["option_order", "key_order", "bare_levels"]
"""The probes `jevtester probe` runs without `--variant`. `pad_state` sends large requests, so it's opt-in."""


def _print_probes(report: ProbeReport) -> None:
    print(f"Run {report.run_id}")
    for row in report.summary:
        rate = f"{row.change_rate:.3f}" if row.change_rate is not None else "n/a"
        print(f"  {row.target}  {row.variant}  change rate {rate} over {row.cases} cases")
    for cell in report.cells:
        if cell.changed:
            print(f"  changed  {cell.case_id}  {cell.target}  {cell.variant}: {cell.changed} of {cell.instances}")


async def _probe_and_follow(service: Service, body: ProbeCreate) -> ProbeReport:
    created = await service.start_probe(body)
    print(f"Run {created.id} started", file=sys.stderr)
    async for event in service.run_events(created.id):
        if isinstance(event, ResultEvent):
            state = "cached" if event.cached else "ok" if event.result.ok else "failed"
            variant = event.variant or "original"
            print(
                f"{event.counts.done}/{event.counts.jobs}  {event.case_id}  {event.target}  {variant}  {state}",
                file=sys.stderr,
            )
        elif isinstance(event, TargetSkippedEvent):
            print(f"Skipped {event.target}: {event.reason}", file=sys.stderr)
    await service.wait_run(created.id)
    return service.run_probes(created.id)


def _probe(args: argparse.Namespace) -> int:
    body = ProbeCreate.model_validate(
        {
            "suite": _suite_name(args.suite),
            "targets": list(args.target),
            "variants": args.variant or DEFAULT_PROBES,
            "no_cache": args.no_cache,
        }
    )
    service = _load_service(args.config)
    try:
        report = asyncio.run(_probe_and_follow(service, body))
    except ServiceError as error:
        _fail(str(error))
    if args.format == "json":
        _print_json(report)
    else:
        _print_probes(report)
    return EXIT_OK


def _print_comparison(comparison: RunComparison) -> None:
    changes = comparison.changes
    print(f"Run {changes.run_id} against baseline {changes.baseline}")
    if not changes.changes:
        print("No answers changed.")
    for change in changes.changes:
        print(
            f"  {change.status:<7}  {change.case_id}  {change.target}  {change.question}: "
            f"{change.baseline_answer} -> {change.answer} (expected {change.expected})"
        )
    for row in changes.summary:
        p_value = f"{row.mcnemar_p:.3f}" if row.mcnemar_p is not None else "n/a"
        print(f"{row.target}: {row.fixed} fixed, {row.broken} broken, {row.changed} changed, McNemar p {p_value}")
    for regression in comparison.regressions:
        print(
            f"Regression: {regression.target} {regression.question} {regression.metric} "
            f"{regression.baseline:.3f} -> {regression.value:.3f} (allowed drop {comparison.max_drop:g})"
        )


def _compare(args: argparse.Namespace) -> int:
    service = _load_service(args.config)
    try:
        comparison = service.compare_runs(args.run, args.baseline, args.max_drop)
    except ServiceError as error:
        _fail(str(error))
    if args.format == "json":
        _print_json(comparison)
    else:
        _print_comparison(comparison)
    return EXIT_CHECK_FAILED if comparison.regressions else EXIT_OK


def _report(args: argparse.Namespace) -> int:
    service = _load_service(args.config)
    try:
        report = service.run_report(args.run)
    except ServiceError as error:
        _fail(str(error))
    if args.format == "json":
        _print_json(report)
    else:
        print(report.markdown, end="")
    return EXIT_OK


def _suite_check(args: argparse.Namespace) -> int:
    service = _load_service(args.config)
    try:
        result = service.check_suite(_suite_name(args.suite))
    except ServiceError as error:
        _fail(str(error))
    if args.format == "json":
        _print_json(result)
    else:
        print(f"Suite {result.suite} is {'valid' if result.valid else 'invalid'}")
        for error in result.errors:
            where = f" {error.field}" if error.field else ""
            print(f"  error{where}: {error.message}")
        for finding in result.checks:
            print(f"  {finding.code}  {finding.question}: {finding.message}")
    return EXIT_OK if result.valid else EXIT_INVALID


def _policy_sweep(args: argparse.Namespace) -> int:
    try:
        body = SweepBody(
            run_id=args.run,
            target=args.target,
            threshold=args.threshold,
            start=args.start,
            stop=args.stop,
            step=args.step,
        )
    except ValidationError as error:
        _fail(f"The sweep is invalid:\n{_describe_validation(error)}")
    service = _load_service(args.config)
    try:
        result = service.sweep_policy(args.policy, body)
    except ServiceError as error:
        _fail(str(error))
    if args.format == "json":
        _print_json(result)
        return EXIT_OK

    def show(value: float | None) -> str:
        return "" if value is None else f"{value:.3f}"

    print(f"{result.policy} {result.threshold} on {result.target}, run {result.run_id} (now {show(result.current)})")
    print("value   decided  error rate  cost")
    for point in result.points:
        print(f"{point.value:<7g} {show(point.decided_share):<8} {show(point.error_rate):<11} {show(point.cost)}")
    return EXIT_OK


def _answer_value(key: str, text: str, question: Question | None) -> AnswerValue:
    # The question's type says how to read the answer, so a choice option named "yes" or "2" stays a name.
    lowered = text.strip().lower()
    match question:
        case ChoiceQuestion():
            return text
        case NoulQuestion():
            if lowered in ("true", "yes"):
                return True
            if lowered in ("false", "no"):
                return False
            raise _InputError(f"{key} is a yes/no question, so --expect needs true or false, got {text!r}.")
        case ScoreQuestion():
            try:
                return int(text)
            except ValueError as error:
                raise _InputError(
                    f"{key} is a score question, so --expect needs a level number, got {text!r}."
                ) from error
        case None:
            raise _InputError(f"The suite's question set has no question {key}.")


def _pairs(values: list[str], flag: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for value in values:
        key, separator, item = value.partition("=")
        if not separator or not key:
            raise _InputError(f"{flag} needs QUESTION=VALUE, got {value!r}.")
        pairs[key] = item
    return pairs


def _case_from_args(args: argparse.Namespace, questions: Mapping[str, Question]) -> Case:
    if bool(args.state) == bool(args.from_decide):
        raise _InputError("Give --state or --from-decide.")
    expected: dict[str, dict[str, Any]] = {}
    if args.from_decide:
        try:
            response = DecideResponse.model_validate_json(
                _read_input(args.from_decide if args.from_decide == "-" else f"@{args.from_decide}")
            )
        except ValidationError as error:
            raise _InputError(f"That isn't a decide response:\n{_describe_validation(error)}") from error
        state: Any = response.request.state
        if args.expect_from:
            result = next((r for r in response.results if r.target == args.expect_from), None)
            if result is None or not result.ok:
                raise _InputError(f"The decide response has no answers from {args.expect_from}.")
            for key, answer in result.answers.items():
                value = answer_value(answer)
                if value is not None:
                    expected[key] = {"answer": value}
    else:
        if args.expect_from:
            raise _InputError("--expect-from needs --from-decide.")
        state = _read_state(args.state)
    for key, value in _pairs(args.expect, "--expect").items():
        expected[key] = {**expected.get(key, {}), "answer": _answer_value(key, value, questions.get(key))}
    for key, value in _pairs(args.tolerance, "--tolerance").items():
        try:
            expected.setdefault(key, {})["tolerance"] = int(value)
        except ValueError as error:
            raise _InputError(f"--tolerance needs a whole number of levels, got {value!r}.") from error
    return Case.model_validate(
        {
            "id": args.id,
            "state": state,
            "expected": expected,
            "expected_action": args.expected_action,
            "tags": list(args.tag),
        }
    )


def _case_add(args: argparse.Namespace) -> int:
    service = _load_service(args.config)
    name = _suite_name(args.suite)
    try:
        questions = service.get_suite(name).question_set.questions
        case = _case_from_args(args, questions)
        created = service.add_case(name, case)
    except _InputError as error:
        _fail(str(error))
    except ValidationError as error:
        _fail(f"The case is invalid:\n{_describe_validation(error)}")
    except ServiceError as error:
        _fail(str(error))
    if args.format == "json":
        _print_json(created)
    else:
        print(f"Added case {created.case.id} to suite {created.suite} ({created.case_count} cases)")
    return EXIT_OK


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from jevtester.api import HOST, PORT, create_app

    service = _load_service(args.config)
    uvicorn.run(create_app(service), host=HOST, port=args.port or PORT)
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """Run the jevtester command line.

    Args:
        argv: The arguments after the program name. `None` reads `sys.argv`.

    Returns:
        The process exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    match args.command:
        case "decide":
            return _decide(args)
        case "targets":
            return _targets(args)
        case "run":
            return _run(args)
        case "probe":
            return _probe(args)
        case "compare":
            return _compare(args)
        case "report":
            return _report(args)
        case "suite":
            return _suite_check(args)
        case "policy":
            return _policy_sweep(args)
        case "case":
            return _case_add(args)
        case "serve":
            return _serve(args)
        case _:
            parser.print_help()
            return EXIT_OK
