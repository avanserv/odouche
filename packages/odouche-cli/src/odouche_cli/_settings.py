"""What changing a branch's and a project's settings share: reading a setting given, showing one, and asking first."""

from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Annotated

import typer

import odouche
from odouche_cli import _terminal
from odouche_cli._context import ContextError
from odouche_cli._output import strip_control


YesOption = Annotated[
    bool,
    typer.Option("--yes", "-y", help="Change without asking. Needed when stdin or stderr is not a terminal."),
]

PARAM = "NAME=VALUE"

type Read = Callable[[str, str], object]
"""Reads the text given for the setting it names, and raises `ValueError` with what to say."""

_FLAGS = {"yes": True, "true": True, "no": False, "false": False}


def shown(value: object) -> str:
    """Return a setting's value: `yes` or `no`, an enumeration's value, a list joined by commas, and nothing as `none`."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple):
        return ", ".join(str(item) for item in value) or "none"
    return str(value) if value else "none"


def quoted(value: object) -> str:
    """Return a setting's value as `shown` does, with a text quoted, so that tags named `none` are not none."""
    return f'"{value}"' if type(value) is str and value else shown(value)


def choice(kind: type[StrEnum]) -> Read:
    """Return the reader of a choice, which takes a value `show --format json` prints."""

    def read(name: str, text: str) -> object:
        try:
            return kind(text)
        except ValueError:
            msg = f"{text!r} is not a value of {name}. One of: {', '.join(kind)}."
            raise ValueError(msg) from None

    return read


def flag(name: str, text: str) -> bool:
    """Read a yes or a no."""
    value = _FLAGS.get(text.lower())
    if value is None:
        msg = f"{text!r} is not a value of {name}. One of: yes, no."
        raise ValueError(msg)
    return value


def names(_: str, text: str) -> tuple[str, ...]:
    """Read names separated by commas."""
    return tuple(name for name in (part.strip() for part in text.split(",")) if name)


def text(_: str, value: str) -> str:
    return value


def seconds(name: str, text: str) -> int:
    """Read a whole number of seconds."""
    if not text.isascii() or not text.isdigit():
        msg = f"{text!r} is not a value of {name}: a whole number of seconds."
        raise ValueError(msg)
    return int(text)


def given(
    ctx: typer.Context, pairs: list[str], reads: Mapping[str, Read], refused: Mapping[str, str] | None = None
) -> dict[str, object]:
    """Read each `NAME=VALUE` by the reader of its name, refusing what the library would before asking Odoo.sh.

    `refused` holds what to say of a name that is not given this way.
    """
    values: dict[str, object] = {}
    for pair in pairs:
        name, sign, value = pair.partition("=")
        if not sign:
            msg = f"{pair!r} is not NAME=VALUE."
            raise typer.BadParameter(msg, ctx=ctx, param_hint=PARAM)
        if refused and name in refused:
            raise typer.BadParameter(refused[name], ctx=ctx, param_hint=PARAM)
        if name not in reads:
            msg = f"{name!r} is not a setting that is changed. One of: {', '.join(reads)}."
            raise typer.BadParameter(msg, ctx=ctx, param_hint=PARAM)
        if name in values:
            msg = f"{name} is given twice."
            raise typer.BadParameter(msg, ctx=ctx, param_hint=PARAM)
        values[name] = _read(ctx, reads[name], name, value)
    return values


def built[T](ctx: typer.Context, build: Callable[[], T], param_hint: str = PARAM) -> T:
    """Build a change, with a value the library refuses as a usage error."""
    try:
        return build()
    except ValueError as error:
        raise typer.BadParameter(str(error), ctx=ctx, param_hint=param_hint) from None


def can_ask(ctx: typer.Context, *, yes: bool) -> None:
    """Raise a usage error when the change is to be asked about and cannot be."""
    if not yes and not _terminal.can_ask():
        msg = (
            "Stdin or stderr is not a terminal, so the change cannot be confirmed. "
            "Give --yes to change without being asked."
        )
        raise ContextError(msg, ctx=ctx)


def checked[T](ctx: typer.Context, call: Callable[[], T]) -> T:
    """Run a call of the library, with a setting it refuses for the others after the change as a usage error."""
    try:
        return call()
    except odouche.SettingsConflictError as error:
        raise ContextError(str(error), ctx=ctx) from None


def say(line: str) -> None:
    """Write a line about the change on stderr, without the control characters of a name it holds."""
    typer.echo(strip_control(line), err=True)


def say_moved(outcome: odouche.SettingsOutcome[object]) -> None:
    """Say each setting Odoo.sh changed along with those sent, from its value to the new one."""
    for name in outcome.moved:
        say(
            f"{name}: {quoted(getattr(outcome.before, name))} → {quoted(getattr(outcome.after, name))}, also changed by Odoo.sh."
        )


def _read(ctx: typer.Context, read: Read, name: str, value: str) -> object:
    try:
        return read(name, value)
    except ValueError as error:
        raise typer.BadParameter(str(error), ctx=ctx, param_hint=PARAM) from None
