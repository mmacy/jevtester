"""The jevtester command-line tool.

Every command writes its result to stdout and its progress and warnings to stderr. With `--format json`, the result
is the same JSON the HTTP API returns.

Exit codes: 0 for success, 1 when a run finished and a check failed, 2 for an invalid command line or input, and 3
when every target failed.
"""

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
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
from jevtester.spec import Case

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
    parser = argparse.ArgumentParser(
        prog="jevtester", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--version", action="version", version=f"jevtester {__version__}")
    parser.add_argument("--config", type=Path, help="The config file. Defaults to $JEVTESTER_CONFIG or jevtester.toml.")
    commands = parser.add_subparsers(dest="command", metavar="<command>")

    def add_format(command: argparse.ArgumentParser) -> None:
        command.add_argument("--format", choices=["text", "json"], default="text", help="The output format.")

    decide = commands.add_parser(
        "decide",
        help="Send one state and its questions to one or more targets, and print the answers.",
        description=(
            "Send one state and its questions to one or more targets. Give one question with --question, which is a "
            "yes/no question unless --option or --level makes it a choice or a score, or give a whole request with "
            "--request."
        ),
    )
    decide.add_argument(
        "--state", help="The state: text, @path to read a file (parsed as JSON if it is), or - for stdin."
    )
    decide.add_argument("--question", help="The question's instructions.")
    decide.add_argument("--id", default="question", help="The question's id. Defaults to question.")
    decide.add_argument(
        "--option", action="append", default=[], metavar="NAME=DESCRIPTION", help="A choice option. Repeat for each."
    )
    decide.add_argument(
        "--level", action="append", default=[], metavar="DESCRIPTION", help="A score level, lowest first. Repeat."
    )
    decide.add_argument("--request", help="The path of a JSON file with state and questions, or - for stdin.")
    decide.add_argument(
        "--target", action="append", default=[], help="A target name. Repeat for each. Defaults to the config's."
    )
    decide.add_argument("--targets", choices=["all"], help="Send to every configured target.")
    decide.add_argument("--timeout", type=float, help="Seconds to wait for each target.")
    add_format(decide)

    targets = commands.add_parser("targets", help="List targets or check them.")
    target_commands = targets.add_subparsers(dest="targets_command", metavar="<command>", required=True)
    add_format(target_commands.add_parser("list", help="List configured targets and their capabilities."))
    add_format(target_commands.add_parser("check", help="Run each target's health check."))

    run = commands.add_parser(
        "run",
        help="Run a suite and print the run's id and counts.",
        description="Run a suite on its targets. Progress goes to stderr, and the run's summary to stdout.",
    )
    run.add_argument("suite", help="The suite's name, or the path of its YAML file, like suites/parley.yaml.")
    run.add_argument("--target", action="append", default=[], help="A target name. Repeat. Defaults to the suite's.")
    run.add_argument("--repeats", type=int, help="Times to send each request. Defaults to the config's.")
    run.add_argument("--question-set-version", help="A question set version to run instead of the current one.")
    run.add_argument("--baseline", help="A run to compare with.")
    run.add_argument("--no-cache", action="store_true", help="Send every request, even when a cached result exists.")
    add_format(run)

    probe = commands.add_parser(
        "probe",
        help="Run probes on a suite and report how often answers change.",
        description=(
            "Run each case as written and as each probe changes it: shuffled choice options, reversed JSON keys, "
            "bare-number score levels, and a state padded toward the target's context window."
        ),
    )
    probe.add_argument("suite", help="The suite's name, or the path of its YAML file.")
    probe.add_argument(
        "--variant",
        action="append",
        choices=["option_order", "key_order", "bare_levels", "pad_state"],
        help="A probe to run. Repeat. Defaults to option_order, key_order, and bare_levels.",
    )
    probe.add_argument("--target", action="append", default=[], help="A target name. Repeat. Defaults to the suite's.")
    probe.add_argument("--no-cache", action="store_true", help="Send every request, even when a cached result exists.")
    add_format(probe)

    compare = commands.add_parser(
        "compare",
        help="Compare a run with a baseline run: metrics, changed answers, and McNemar's test.",
        description="Compare a run with a baseline. Exits with 1 when a metric dropped by more than --max-drop.",
    )
    compare.add_argument("run", help="The run's id.")
    compare.add_argument("baseline", help="The baseline run's id.")
    compare.add_argument(
        "--max-drop", type=float, help="The largest allowed drop in accuracy. Defaults to the config's."
    )
    add_format(compare)

    report = commands.add_parser("report", help="Write a run's report as Markdown or JSON.")
    report.add_argument("run", help="The run's id.")
    report.add_argument("--format", choices=["markdown", "json"], default="markdown", help="The output format.")

    suite = commands.add_parser("suite", help="Work with suites.")
    suite_commands = suite.add_subparsers(dest="suite_command", metavar="<command>", required=True)
    check = suite_commands.add_parser(
        "check",
        help="Validate a suite and run the question-wording checks.",
        description="Validate a suite and run the question-wording checks. Exits with 2 when the suite is invalid.",
    )
    check.add_argument("suite", help="The suite's name, or the path of its YAML file.")
    add_format(check)

    policy = commands.add_parser("policy", help="Work with decision policies.")
    policy_commands = policy.add_subparsers(dest="policy_command", metavar="<command>", required=True)
    sweep = policy_commands.add_parser(
        "sweep",
        help="Sweep a policy threshold over a finished run and print the trade-off points.",
        description="Measure a target's decisions in a finished run as one of the policy's thresholds moves.",
    )
    sweep.add_argument("policy", help="The policy's name.")
    sweep.add_argument("--run", required=True, help="The run's id.")
    sweep.add_argument("--target", required=True, help="A target the run ran.")
    sweep.add_argument("--threshold", required=True, help="The threshold to move.")
    sweep.add_argument("--start", type=float, default=0.0, help="The first value. Defaults to 0.")
    sweep.add_argument("--stop", type=float, default=1.0, help="The last value. Defaults to 1.")
    sweep.add_argument("--step", type=float, default=0.05, help="The step. Defaults to 0.05.")
    add_format(sweep)

    case = commands.add_parser("case", help="Work with a suite's cases.")
    case_commands = case.add_subparsers(dest="case_command", metavar="<command>", required=True)
    add = case_commands.add_parser(
        "add",
        help="Save a case to a suite, including one promoted from a decide call.",
        description=(
            "Save a case to the end of a suite's file. Give the state with --state, or promote a decide call with "
            "--from-decide, which reads `jevtester decide --format json` output. --expect-from takes the expected "
            "answers from one target's answers in that output."
        ),
    )
    add.add_argument("suite", help="The suite's name, or the path of its YAML file.")
    add.add_argument("--id", required=True, help="The case's id.")
    add.add_argument("--state", help="The state: text, @path to read a file (parsed as JSON if it is), or - for stdin.")
    add.add_argument("--from-decide", metavar="PATH", help="A decide response as JSON, or - for stdin.")
    add.add_argument("--expect-from", metavar="TARGET", help="Expect the answers this target gave in --from-decide.")
    add.add_argument(
        "--expect", action="append", default=[], metavar="QUESTION=ANSWER", help="An expected answer. Repeat."
    )
    add.add_argument(
        "--tolerance", action="append", default=[], metavar="QUESTION=LEVELS", help="Score levels of slack. Repeat."
    )
    add.add_argument("--expected-action", help="The action the suite's policy should choose.")
    add.add_argument("--tag", action="append", default=[], help="A tag. Repeat.")
    add_format(add)

    serve = commands.add_parser("serve", help="Start the API and the web UI on 127.0.0.1.")
    serve.add_argument("--port", type=int, default=None, help="The port. Defaults to 8640.")
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
    except OSError as error:
        _fail(f"Can't read the config: {error}")
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


def _answer_value(text: str) -> AnswerValue:
    lowered = text.strip().lower()
    if lowered in ("true", "yes"):
        return True
    if lowered in ("false", "no"):
        return False
    try:
        return int(text)
    except ValueError:
        return text


def _pairs(values: list[str], flag: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for value in values:
        key, separator, item = value.partition("=")
        if not separator or not key:
            raise _InputError(f"{flag} needs QUESTION=VALUE, got {value!r}.")
        pairs[key] = item
    return pairs


def _case_from_args(args: argparse.Namespace) -> Case:
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
        expected[key] = {**expected.get(key, {}), "answer": _answer_value(value)}
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
    try:
        case = _case_from_args(args)
    except _InputError as error:
        _fail(str(error))
    except ValidationError as error:
        _fail(f"The case is invalid:\n{_describe_validation(error)}")
    service = _load_service(args.config)
    try:
        created = service.add_case(_suite_name(args.suite), case)
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
