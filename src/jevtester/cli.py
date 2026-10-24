"""The jevtester command-line tool.

Every command writes its result to stdout and its progress and warnings to stderr.
"""

import argparse
from collections.abc import Sequence

from jevtester import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for every jevtester command.

    Returns:
        The top-level parser. `argparse` exits with code 2 on an invalid command line, which is the plan's exit code
        for that case.
    """
    parser = argparse.ArgumentParser(prog="jevtester", description=__doc__)
    parser.add_argument("--version", action="version", version=f"jevtester {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="<command>")

    serve = commands.add_parser("serve", help="Start the API and the web UI on 127.0.0.1.")
    serve.add_argument("--port", type=int, default=None, help="The port. Defaults to 8640.")
    return parser


def _serve(port: int | None) -> int:
    import uvicorn

    from jevtester.api import HOST, PORT, create_app

    uvicorn.run(create_app(), host=HOST, port=port or PORT)
    return 0


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
        case "serve":
            return _serve(args.port)
        case _:
            parser.print_help()
            return 0
