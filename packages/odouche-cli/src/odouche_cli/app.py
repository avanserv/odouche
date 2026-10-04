"""The `osh` command: the root application and its entry point."""

from dataclasses import dataclass
from typing import Annotated

import typer

import odouche
from odouche_cli import __version__
from odouche_cli._errors import DebugOption, OshGroup
from odouche_cli._output import Format, FormatOption, Output


app = typer.Typer(
    name="osh",
    help="Work with Odoo.sh projects from the command line (unofficial).",
    no_args_is_help=True,
    cls=OshGroup,
    # A locals dump is where a session would surface.
    pretty_exceptions_show_locals=False,
)


@dataclass(frozen=True, slots=True)
class Versions:
    """The versions `--version` reports."""

    osh: str
    odouche: str


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    *,
    version: Annotated[
        bool,
        typer.Option("--version", help="Show the version and exit.", is_eager=True),
    ] = False,
    debug: DebugOption = False,
    output_format: FormatOption = Format.TABLE,
) -> None:
    """Work with Odoo.sh projects from the command line (unofficial)."""
    output = ctx.obj = Output(output_format)
    if version:
        versions = Versions(osh=__version__, odouche=odouche.__version__)
        output.stream([versions], lambda found: f"osh {found.osh} (odouche {found.odouche})")
        raise typer.Exit


def main() -> None:
    """Run the `osh` command."""
    app()
