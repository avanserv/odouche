"""`osh ssh`: a shell on a build of a branch, through the user's own `ssh`.

`osh` reads no key and holds no connection: its process becomes `ssh`. Before that, when `ssh`
does not get in, it asks Odoo.sh to let this machine's address in, which is the one change it makes.
"""

import os
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from typing import Annotated, NoReturn

import typer
from rich.console import Console
from rich.live import Live
from rich.text import Text

import odouche
from odouche_cli import _terminal
from odouche_cli._client import forget_session_env, open_client
from odouche_cli._context import BranchOption, ContextError, ProjectOption, find_build, project_branch, resolve_branch
from odouche_cli._errors import EXIT_DECLINED, EXIT_NO_SSH, EXIT_OUTCOME_UNKNOWN, EXIT_TIMEOUT
from odouche_cli._output import strip_control


EPILOG = "Example: osh ssh --branch staging -- ls"

# The Odoo.sh gateway greets any address and applies the rule after the key exchange, so whether
# `ssh` gets in is the one sign that the rule applies. Every build host is a new name for the
# gateway's key, which a try neither checks nor records: the `ssh` that follows asks about it.
# A try runs `true` alone, whatever the user's configuration adds, and forwards nothing.
_TRY = (
    *("-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-o", "LogLevel=ERROR"),
    *("-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null"),
    *("-o", "RemoteCommand=none", "-o", "RequestTTY=no"),
    *("-o", "ForwardAgent=no", "-o", "ForwardX11=no", "-o", "ClearAllForwardings=yes"),
)
_TRY_BOUND = 45.0
# What `ssh` says when the address got through and the user's keys did not: the `ssh` that follows asks.
_NOT_THE_ADDRESS = "Permission denied ("
# Odoo.sh says five minutes; a staging rule was seen to take longer.
_RULE_WAIT = 600.0
_INTERVAL = 10.0
# How often a wait with no terminal to redraw says it is still waiting.
_REPORT_EVERY = 60.0

# What the tests replace: the call that turns this process into `ssh`, the run of `ssh` that
# tries to get in, the clock and the wait between two tries.
_exec = os.execv
_run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run
_monotonic: Callable[[], float] = time.monotonic
_sleep: Callable[[float], None] = time.sleep

ArgsArgument = Annotated[
    list[str] | None,
    typer.Argument(
        metavar="[SSH_ARGS]...",
        help="What to give `ssh` after the host: its own options, or a command to run on the build. "
        "Everything from the first one on is `ssh`'s. Put `--` before it when it starts with a dash.",
    ),
]
YesOption = Annotated[
    bool,
    typer.Option(
        "--yes",
        "-y",
        help="Allow this machine's address without asking, when `ssh` does not get in. "
        "Needed then when stdin or stderr is not a terminal.",
    ),
]


def ssh(
    ctx: typer.Context,
    args: ArgsArgument = None,
    project: ProjectOption = None,
    branch: BranchOption = None,
    *,
    yes: YesOption = False,
) -> None:
    """Open a shell on the branch's latest build, with your own `ssh`, its configuration and its keys.

    It first tries `ssh` with no prompt. When that does not get in, it changes state on Odoo.sh: it
    asks Odoo.sh to allow this machine's address for one hour, unless declined, and tries again
    for up to ten minutes.
    """
    name = resolve_branch(ctx, branch)

    with open_client() as client:
        project_name, found = project_branch(ctx, client, project, name)
        target = client.ssh_target(find_build(client, project_name, found, None))

    command = ["ssh", "-l", target.user, target.host, *(args or [])]

    if sys.platform == "win32":
        refuse("`osh` does not hand over to `ssh` on Windows.", subprocess.list2cmdline(command))

    program = shutil.which("ssh")

    if program is None:
        refuse("No `ssh` to hand over to.", shlex.join(command))

    reach(ctx, found, target, program, yes=yes, again="osh ssh")
    hand_over(program, command)


def reach(
    ctx: typer.Context, branch: odouche.Branch, target: odouche.SshTarget, program: str, *, yes: bool, again: str
) -> None:
    """Make sure the user's `ssh`, at `program`, gets into the build, allowing this machine's address once agreed.

    `again` is the command the user is told to run again when the address is still kept out.
    """
    forget_session_env()
    kept_out = _kept_out(program, target)

    if kept_out is not None:
        _allow(ctx, branch, target, program, kept_out, yes=yes, again=again)


def hand_over(program: str, command: list[str]) -> None:
    """Become `program`, after what was said is out."""
    sys.stdout.flush()
    sys.stderr.flush()
    _exec(program, command)


def _kept_out(program: str, target: odouche.SshTarget) -> str | None:
    """Run `true` on the build with the user's `ssh` and no prompt, and return why the address is kept out.

    `None` is that it is not: `ssh` got in, or the build refused the user's keys. The reason is the
    last line `ssh` printed, which is shown and nothing else is.
    """
    tried = [program, *_TRY, "-l", target.user, target.host, "true"]

    try:
        done = _run(
            tried,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            timeout=_TRY_BOUND,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"no answer within {_TRY_BOUND:.0f} s"

    if done.returncode == 0:
        return None

    lines = done.stderr.strip().splitlines()

    if lines and _NOT_THE_ADDRESS in lines[-1]:
        return None

    return lines[-1] if lines else f"`ssh` exited with {done.returncode}"


def _allow(
    ctx: typer.Context,
    branch: odouche.Branch,
    target: odouche.SshTarget,
    program: str,
    kept_out: str,
    *,
    yes: bool,
    again: str,
) -> None:
    """Ask Odoo.sh to let this machine's address in on the branch, once agreed, and wait until `ssh` gets in."""
    said = f"Your `ssh` does not get into build {target.user} from this machine's address: {kept_out}"

    if not yes and not _terminal.can_ask():
        msg = (
            f"{said} Stdin or stderr is not a terminal, so allowing the address cannot be confirmed. "
            "Give --yes to allow it without being asked, or use Allow my IP on the branch's page."
        )
        raise ContextError(strip_control(msg), ctx=ctx)

    typer.echo(strip_control(said), err=True)

    if not yes:
        line = f"Odoo.sh can allow the address it sees from here on branch {branch.name}, for one hour."
        typer.echo(strip_control(line), err=True)

        if not _terminal.confirmed("Allow it?"):
            typer.echo("Nothing was sent.", err=True)
            raise typer.Exit(EXIT_DECLINED)

    with open_client(writes=True) as client:
        # Sent once: an error is reported, never retried.
        try:
            address = client.allow_ip(branch)
        except odouche.OutcomeUnknownError as unknown:
            typer.echo(strip_control(str(unknown)), err=True)
            typer.echo(f"Run `{again}` again: it asks only if `ssh` still does not get in.", err=True)

            raise typer.Exit(EXIT_OUTCOME_UNKNOWN) from None

    typer.echo(f"Odoo.sh allowed {address} for one hour. It takes up to five minutes to apply.", err=True)
    still = _wait(program, target)

    if still is not None:
        line = (
            f"`ssh` still does not get into build {target.user}: {still}. "
            f"Odoo.sh may not have applied the rule yet: run `{again}` again in a few minutes."
        )
        typer.echo(strip_control(line), err=True)

        raise typer.Exit(EXIT_TIMEOUT)


def _wait(program: str, target: odouche.SshTarget) -> str | None:
    """Try `ssh` until the address is no longer what keeps it out, or return why it still is at the end.

    The wait is kept on one line on a terminal, and said once a minute otherwise.
    """

    def line(waited: float) -> str:
        return strip_control(f"Waiting for the rule to apply to build {target.user} ({waited:.0f} s).")

    console = Console(file=sys.stderr, highlight=False)

    try:
        if _terminal.redraws(console):
            with Live(Text(line(0)), console=console, transient=True) as live:
                for waited in _tries(program, target):
                    live.update(Text(line(waited)))
        else:
            reported = -_REPORT_EVERY

            for waited in _tries(program, target):
                if waited - reported >= _REPORT_EVERY:
                    typer.echo(line(waited), err=True)
                    reported = waited
    except _WaitOverError as over:
        return over.kept_out

    return None


class _WaitOverError(Exception):
    """The rule's wait is over and the address still keeps `ssh` out."""

    def __init__(self, kept_out: str) -> None:
        super().__init__(kept_out)
        self.kept_out = kept_out


def _tries(program: str, target: odouche.SshTarget) -> Iterator[float]:
    """Yield the seconds waited after each try the address kept `ssh` out, and end once it does not."""
    start = _monotonic()
    last = "no try"

    while (waited := _monotonic() - start) < _RULE_WAIT:
        _sleep(min(_INTERVAL, _RULE_WAIT - waited))
        kept_out = _kept_out(program, target)

        if kept_out is None:
            return

        last = kept_out

        yield _monotonic() - start

    raise _WaitOverError(last)


def refuse(reason: str, command: str) -> NoReturn:
    """Say why `osh` does not hand over, with the command to run by hand, and exit."""
    typer.echo(strip_control(f"{reason} Run it yourself: {command}"), err=True)

    raise typer.Exit(EXIT_NO_SSH)
