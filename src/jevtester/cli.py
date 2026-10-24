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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the jevtester command line.

    Args:
        argv: The arguments after the program name. `None` reads `sys.argv`.

    Returns:
        The process exit code.
    """
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0
