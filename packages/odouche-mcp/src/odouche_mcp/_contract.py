"""The contract every tool meets, and the one way to register a tool that meets it.

`tests/test_contract.py` checks the registered tools against it, however they were registered.
"""

import functools
import inspect
import re
import types
from collections.abc import Callable
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

import odouche
from odouche_mcp._errors import tool_error


# Verb then noun. Permission rules and hooks match on the name, so it never changes once released.
NAME = re.compile(r"[a-z]+(_[a-z]+)+")

# The labels of the lines every description ends with.
RETURNS = "Returns"
TOUCHES = "Touches"
BOUNDS = "Bounds"

READS_ONLY = "reads only"
"""What a tool that changes nothing on Odoo.sh touches."""

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)


def add_tool[**P, R](
    server: MCPServer[Any],
    fn: Callable[P, R],
    *,
    returns: str,
    bounds: str,
    touches: str = READS_ONLY,
    annotations: ToolAnnotations = READ_ONLY,
) -> None:
    """Register `fn` as the tool of its name, described by its docstring's first paragraph.

    `returns` is what it returns, `bounds` its limits on size and time, and `touches` what it can
    change on Odoo.sh. A tool that changes something says what and sets all four hints itself. Its
    return type is a dataclass of the server's own: the library's models go in its fields.
    """
    name = fn.__name__
    if not NAME.fullmatch(name):
        msg = f"{name}: a tool is named verb then noun, as `list_projects`."
        raise ValueError(msg)
    # The server keeps the first of two and only logs it, and has no public way to ask but an awaited one.
    if server._tool_manager.get_tool(name):
        msg = f"{name}: a tool of that name is registered."
        raise ValueError(msg)
    # Its errors would pass through unmapped.
    if inspect.iscoroutinefunction(fn):
        msg = f"{name}: a tool is a plain function, which the server runs in a thread."
        raise TypeError(msg)
    summary = " ".join((inspect.getdoc(fn) or "").split("\n\n", 1)[0].split())
    lines = {RETURNS: returns, TOUCHES: touches, BOUNDS: bounds}
    if not summary or not all(text.strip() and "\n" not in text for text in lines.values()):
        msg = f"{name}: a tool has a docstring, and one line each for what it returns, touches and is bound by."
        raise ValueError(msg)
    _check_hints(name, annotations, touches)

    @functools.wraps(fn)
    def tool(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return fn(*args, **kwargs)
        except odouche.OdoucheError as error:
            raise tool_error(error) from None

    server.add_tool(
        tool,
        description="\n".join([summary, "", *(f"{label}: {text}" for label, text in lines.items())]),
        annotations=annotations,
        # A return type with no schema fails here, not as a result without structure.
        structured_output=True,
    )
    if not annotations.read_only_hint:
        _refuse_undeclared(server, name)


def _check_hints(name: str, annotations: ToolAnnotations, touches: str) -> None:
    """Raise when a tool leaves a hint unset, or when its read-only hint and what it touches disagree."""
    hints = (
        annotations.read_only_hint,
        annotations.destructive_hint,
        annotations.idempotent_hint,
        annotations.open_world_hint,
    )
    if any(hint is None for hint in hints):
        msg = f"{name}: a tool sets all four hints."
        raise ValueError(msg)
    if annotations.read_only_hint != (touches == READS_ONLY):
        msg = f"{name}: a read-only tool touches `{READS_ONLY}`, and only a read-only tool does."
        raise ValueError(msg)


def _refuse_undeclared(server: MCPServer[Any], name: str) -> None:
    """Make a tool refuse a call that gives an argument it does not declare, before it runs.

    The server otherwise drops the argument and runs the tool on the rest, so a change asked for
    in an argument the tool does not take would send the others and return as if done.
    """
    registered = server._tool_manager.get_tool(name)
    if registered is None:
        msg = f"{name}: the tool was not registered."
        raise ValueError(msg)
    declared = registered.fn_metadata.arg_model
    config = {**declared.model_config, "extra": "forbid"}
    strict = types.new_class(
        declared.__name__, (declared,), {}, lambda namespace: namespace.update(model_config=config)
    )
    registered.fn_metadata.arg_model = strict
    # What the client is shown: `additionalProperties` false.
    registered.parameters = strict.model_json_schema(by_alias=True)
