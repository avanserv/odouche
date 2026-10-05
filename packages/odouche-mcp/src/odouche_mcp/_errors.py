"""Library errors as tool errors, mapped once for every tool.

An agent gets the library's message and what to do next: never a traceback or an upstream body.
"""

from mcp.server.mcpserver.exceptions import ToolError

import odouche


_LOGIN = "Ask the user to run `osh auth login`, then call the tool again."

# The first row an error is an instance of wins, so the base class comes last.
NEXT_STEPS: tuple[tuple[type[odouche.OdoucheError], str | None], ...] = (
    (odouche.NoSessionError, _LOGIN),
    (odouche.SessionExpiredError, _LOGIN),
    (odouche.NotFoundError, None),
    (odouche.PermissionDeniedError, None),
    (odouche.UpstreamChangedError, None),
    (odouche.UpstreamUnavailableError, "Try again later."),
    (odouche.StreamTimeoutError, None),
    (odouche.LoginTimeoutError, None),
    (odouche.ReadOnlyError, None),
    (odouche.StageRefusedError, None),
    (odouche.OutcomeUnknownError, "List the branch's builds to see whether it was carried out before trying again."),
    (odouche.KeyringUnavailableError, None),
    (odouche.LoginError, None),
    (odouche.OdoucheError, None),
)


def tool_error(error: odouche.OdoucheError) -> ToolError:
    """Return the tool error that says what happened and, when there is one, the next step."""
    step = next(step for kind, step in NEXT_STEPS if isinstance(error, kind))
    return ToolError(f"{error} {step}" if step else str(error))
