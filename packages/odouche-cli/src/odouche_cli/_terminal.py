"""What a command needs of the terminal: to ask a question before a change, or to redraw a line."""

import sys
from typing import TextIO

import typer
from rich.console import Console


def confirmed(question: str) -> bool:
    """Ask on stderr and read the answer from stdin: only `y` or `yes` is a yes. Nothing goes to stdout."""
    typer.echo(f"{question} [y/N]: ", nl=False, err=True)

    return sys.stdin.readline().strip().lower() in {"y", "yes"}


def can_ask() -> bool:
    """Tell whether a question can be both seen and answered."""
    return stdin_is_terminal() and stderr_is_terminal()


def stdin_is_terminal() -> bool:
    return _is_terminal(sys.stdin)


def stdout_is_terminal() -> bool:
    return _is_terminal(sys.stdout)


def stderr_is_terminal() -> bool:
    return _is_terminal(sys.stderr)


def redraws(console: Console) -> bool:
    """Tell whether a `Live` on that console draws: Rich needs the three, and the environment sets each."""
    return stderr_is_terminal() and console.is_terminal and not console.is_dumb_terminal and console.is_interactive


def _is_terminal(stream: TextIO | None) -> bool:
    """Tell whether a standard stream is a terminal, which a closed one is not."""
    return stream is not None and stream.isatty()
