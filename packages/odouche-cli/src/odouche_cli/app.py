"""The `osh` command: the root application and its entry point."""

from typing import Annotated

import typer

import odouche
from odouche_cli import __version__


app = typer.Typer(
    name="osh",
    help="Work with Odoo.sh projects from the command line (unofficial).",
    no_args_is_help=True,
)


@app.callback(invoke_without_command=True)
def root(
    *,
    version: Annotated[
        bool,
        typer.Option("--version", help="Show the version and exit.", is_eager=True),
    ] = False,
) -> None:
    """Work with Odoo.sh projects from the command line (unofficial)."""
    if version:
        typer.echo(f"osh {__version__} (odouche {odouche.__version__})")
        raise typer.Exit


def main() -> None:
    """Run the `osh` command."""
    app()
