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
from jevtester.normalize import ChoiceAnswer, NoulAnswer, ScoreAnswer, TargetResult
from jevtester.schemas import DecideBody, DecideResponse, TargetList
from jevtester.service import Service, UnknownTargetError

EXIT_OK = 0
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
    except UnknownTargetError as error:
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
        case "serve":
            return _serve(args)
        case _:
            parser.print_help()
            return EXIT_OK
