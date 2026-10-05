"""The tool that changes state on Odoo.sh, registered only when the server is started with the switch.

Each call writes one line to stderr, with the tool, its target and what came of it.
"""

import contextlib
import sys
from collections.abc import Callable
from dataclasses import dataclass

from mcp.types import ToolAnnotations

import odouche
from odouche_mcp._read import find_branch
from odouche_mcp._session import open_client


# Destructive as the cautious answer: a rebuild was seen once. Not idempotent: a second call starts a second build.
CHANGING = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=True)


@dataclass(frozen=True)
class Rebuilt:
    build: odouche.Build


def changing_tool(*, allow_changes: bool) -> Callable[[str, str], Rebuilt]:
    """Return the rebuild tool, whose client is read-only unless `allow_changes`."""

    def rebuild_branch(project: str, branch: str) -> Rebuilt:
        """Change state on Odoo.sh: start a new build of a branch of a project, which replaces its latest one.
        Only a development or a staging branch is rebuilt.
        """
        try:
            with open_client(changes=allow_changes) as client:
                # Sent once: an error is reported, never retried.
                started = client.rebuild(find_branch(client, project, branch))
        except Exception as error:
            _audit(project, branch, type(error).__name__)
            raise
        _audit(project, branch, f"build {started.id} started")
        return Rebuilt(started)

    return rebuild_branch


def _audit(project: str, branch: str, outcome: str) -> None:
    # Not through `logging`, which a level can silence. The names are third-party text, hence `repr`.
    # A stderr that cannot be written must not make an error of a build that was started.
    with contextlib.suppress(OSError, ValueError):
        print(f"odouche-mcp: rebuild_branch project={project!r} branch={branch!r}: {outcome}", file=sys.stderr)  # noqa: T201
