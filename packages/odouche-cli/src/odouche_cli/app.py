"""The `osh` command: the root application and its entry point."""

from typing import Annotated

import typer

import odouche
from odouche_cli import __version__
from odouche_cli._errors import DebugOption, OshGroup


app = typer.Typer(
    name="osh",
    help="Work with Odoo.sh projects from the command line (unofficial).",
    no_args_is_help=True,
    cls=OshGroup,
    # A locals dump is where a session would surface.
    pretty_exceptions_show_locals=False,
)


@app.callback(invoke_without_command=True)
def root(
    *,
    version: Annotated[
        bool,
        typer.Option("--version", help="Show the version and exit.", is_eager=True),
    ] = False,
    debug: DebugOption = False,
) -> None:
    """Work with Odoo.sh projects from the command line (unofficial)."""
    if version:
        typer.echo(f"osh {__version__} (odouche {odouche.__version__})")
        raise typer.Exit


def main() -> None:
    """Run the `osh` command."""
    app()
