"""The tools that change state on Odoo.sh, registered only when the server is started with the switch.

Each call writes one line to stderr, with the tool, its target and what came of it.
"""

import contextlib
import sys
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

import odouche
from odouche_mcp._read import find_branch
from odouche_mcp._session import open_client


# Destructive as the cautious answer: a rebuild was seen once. Not idempotent: a second call starts a second build.
CHANGING = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=True)
# A value is overwritten, and the same call twice leaves the settings as once.
SETTINGS = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=True)


@dataclass(frozen=True)
class Rebuilt:
    build: odouche.Build


type SettingValue = str | bool | list[str] | None


@dataclass(frozen=True)
class MovedSetting:
    name: str
    before: SettingValue
    after: SettingValue


@dataclass(frozen=True)
class SettingsChanged:
    branch: odouche.Branch
    changed: list[str]
    unchanged: list[str]
    moved: list[MovedSetting]
    """The settings not given that Odoo.sh changed along with those given."""
    settings: odouche.BranchSettings


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
            _audit("rebuild_branch", project, branch, type(error).__name__)
            raise
        _audit("rebuild_branch", project, branch, f"build {started.id} started")
        return Rebuilt(started)

    return rebuild_branch


def settings_tool(*, allow_changes: bool) -> Callable[..., SettingsChanged]:
    """Return the tool that changes a branch's settings, whose client is read-only unless `allow_changes`."""

    def change_branch_settings(
        project: str,
        branch: str,
        *,
        push_behavior: odouche.PushBehavior | None = None,
        project_defaults: bool | None = None,
        module_install: odouche.ModuleInstall | None = None,
        modules: str | None = None,
        tests: odouche.BuildTests | None = None,
        test_tags: str | None = None,
        demo_data: bool | None = None,
        ai_agent: odouche.AiAgent | None = None,
    ) -> SettingsChanged:
        """Change state on Odoo.sh: change settings of a branch of a project, sending only those given; the others keep their value.
        What a new commit does is not changed on a production branch, and the new build options only on a development branch, with `project_defaults` false while the project's defaults apply. `modules` is module names separated by commas, and an empty `test_tags` clears the tags.
        """
        try:
            try:
                change = odouche.SettingsChange(
                    push_behavior=push_behavior,
                    project_defaults=project_defaults,
                    module_install=module_install,
                    modules=None if modules is None else tuple(filter(None, map(str.strip, modules.split(",")))),
                    tests=tests,
                    test_tags=test_tags,
                    demo_data=demo_data,
                    ai_agent=ai_agent,
                )
            except ValueError as error:
                raise ToolError(str(error)) from None
            with open_client(changes=allow_changes) as client:
                found = find_branch(client, project, branch)
                current = client.branch_settings(found)
                narrowed = _refused(partial(client.check_settings_change, found, current, change))
                outcome = odouche.SettingsOutcome(current, current, ())
                if narrowed is not None:
                    # Sent once: an error is reported, never retried.
                    outcome = _refused(partial(client.change_branch_settings, found, narrowed))
        except Exception as error:
            _audit("change_branch_settings", project, branch, type(error).__name__)
            raise
        changed = [] if narrowed is None else list(narrowed.given())
        unchanged = [name for name in change.given() if name not in changed]
        # The names alone: a value, such as the tags, is the caller's text.
        _audit("change_branch_settings", project, branch, f"changed {', '.join(changed) or 'nothing'}")
        moved = [
            MovedSetting(name, _plain(getattr(outcome.before, name)), _plain(getattr(outcome.after, name)))
            for name in outcome.moved
        ]
        return SettingsChanged(found, changed, unchanged, moved, outcome.after)

    return change_branch_settings


def _plain(value: object) -> SettingValue:
    """Return a setting's value as its JSON has it."""
    if isinstance(value, tuple):
        return [str(name) for name in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, str):
        return str(value)
    msg = f"No setting holds a {type(value).__name__}."
    raise TypeError(msg)


def _refused[T](call: Callable[[], T]) -> T:
    """Run a call, with a setting the library refuses for the others after the change as a tool error."""
    try:
        return call()
    except odouche.SettingsConflictError as error:
        raise ToolError(str(error)) from None


def _audit(tool: str, project: str, branch: str, outcome: str) -> None:
    # Not through `logging`, which a level can silence. The names are third-party text, hence `repr`.
    # A stderr that cannot be written must not make an error of a change that was sent.
    with contextlib.suppress(OSError, ValueError):
        print(f"odouche-mcp: {tool} project={project!r} branch={branch!r}: {outcome}", file=sys.stderr)  # noqa: T201
