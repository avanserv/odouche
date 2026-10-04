"""Library errors as exit codes and messages, handled once at the root of `osh`.

Scripts branch on the codes, so changing one is a breaking change. `docs/cli.md` has the table.
"""

import os
import traceback
from typing import Annotated, Any, override

import typer
from typer.core import TyperGroup

import odouche


ISSUES_URL = "https://github.com/avanserv/odouche/issues"

EXIT_UNEXPECTED = 1

_LOGIN = "Run `osh auth login`."
_LOGIN_AGAIN = "Run `osh auth login` again."

# The first row an error is an instance of wins, so the base class comes last. 1 and 2 are the
# unexpected error and click's usage error, 20 to 29 are kept for `osh builds watch`.
EXIT_CODES: tuple[tuple[type[odouche.OdoucheError], int, str | None], ...] = (
    (odouche.NoSessionError, 3, _LOGIN),
    (odouche.SessionExpiredError, 3, _LOGIN),
    (odouche.NotFoundError, 4, None),
    (odouche.PermissionDeniedError, 5, None),
    (odouche.UpstreamChangedError, 6, None),
    (odouche.UpstreamUnavailableError, 7, "Try again later."),
    (odouche.StreamTimeoutError, 8, None),
    (odouche.LoginTimeoutError, 8, _LOGIN_AGAIN),
    (odouche.ReadOnlyError, 9, None),
    (odouche.StageRefusedError, 9, None),
    (odouche.OutcomeUnknownError, 10, "Look at Odoo.sh before trying again."),
    (odouche.KeyringUnavailableError, 11, None),
    (odouche.LoginError, 12, _LOGIN_AGAIN),
    (odouche.OdoucheError, 13, None),
)

DebugOption = Annotated[
    bool,
    typer.Option("--debug", envvar="OSH_DEBUG", help="Show the traceback when a command fails."),
]


class OshGroup(TyperGroup):
    """The root group: a failed command ends with a message on stderr and an exit code."""

    # The base names typer's vendored click context, which is not public. Typer passes its own.
    @override
    def invoke(self, ctx: typer.Context) -> Any:  # pyright: ignore[reportIncompatibleMethodOverride]
        try:
            return super().invoke(ctx)
        # A closed pipe, as under `| head`, is typer's to end quietly.
        except (typer.Exit, typer.Abort, typer.TyperException, BrokenPipeError):
            raise
        except Exception as error:  # noqa: BLE001 - the root reports every failure
            debug = bool(ctx.params.get("debug"))
            if debug:
                _print_traceback(error)
            ctx.exit(_report(error, debug=debug))


def _print_traceback(error: Exception) -> None:
    """Print the standard traceback, which has no locals, with the environment's session masked."""
    text = "".join(traceback.format_exception(error))
    if session := os.environ.get(odouche.SESSION_ENV):
        text = text.replace(session, str(odouche.Secret(session)))
    typer.echo(text, err=True, nl=False)


def _report(error: Exception, *, debug: bool) -> int:
    """Print what happened and what to do on stderr, and return the exit code."""
    if not isinstance(error, odouche.OdoucheError):
        typer.echo(f"Unexpected error ({type(error).__name__}). Please report it at {ISSUES_URL}", err=True)
        if not debug:
            typer.echo("Run again with --debug for the traceback.", err=True)
        return EXIT_UNEXPECTED
    code, hint = next((code, hint) for kind, code, hint in EXIT_CODES if isinstance(error, kind))
    typer.echo(str(error), err=True)
    if hint:
        typer.echo(hint, err=True)
    return code
