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


type SettingValue = str | bool | int | list[str] | None


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


@dataclass(frozen=True)
class ProjectSettingsChanged:
    project: str
    changed: list[str]
    unchanged: list[str]
    moved: list[MovedSetting]
    """The settings not given that Odoo.sh changed along with those given."""
    settings: odouche.ProjectSettings


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
            _audit("rebuild_branch", _target(project, branch), type(error).__name__)
            raise
        _audit("rebuild_branch", _target(project, branch), f"build {started.id} started")
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
                    modules=_names(modules),
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
            _audit("change_branch_settings", _target(project, branch), type(error).__name__)
            raise
        changed = [] if narrowed is None else list(narrowed.given())
        unchanged = [name for name in change.given() if name not in changed]
        # The names alone: a value, such as the tags, is the caller's text.
        _audit("change_branch_settings", _target(project, branch), f"changed {', '.join(changed) or 'nothing'}")
        return SettingsChanged(found, changed, unchanged, _moved(outcome), outcome.after)

    return change_branch_settings


def project_settings_tool(*, allow_changes: bool) -> Callable[..., ProjectSettingsChanged]:
    """Return the tool that changes a project's settings, whose client is read-only unless `allow_changes`.

    It has no parameter for a setting of `ProjectSettingsChange.ACCESS`, so that no agent changes who
    can reach the project: the server refuses a call that names one.
    """

    def change_project_settings(
        project: str,
        *,
        http_timeout_seconds: int | None = None,
        cron_timeout_seconds: int | None = None,
        module_install: odouche.ModuleInstall | None = None,
        modules: str | None = None,
        tests: odouche.BuildTests | None = None,
        test_tags: str | None = None,
        demo_data: bool | None = None,
        ai_agent: odouche.AiAgent | None = None,
    ) -> ProjectSettingsChanged:
        """Change state on Odoo.sh: change settings of a project, given by its name, sending only those given; the others keep their value. Only an admin of the project changes them.
        The timeouts are in seconds, a multiple of 60, and change on a dedicated server only. `module_install` to `ai_agent` are the defaults of new development branches: `modules` is module names separated by commas, and an empty `test_tags` clears the tags. The IP allow list, public access and session lifetime are not offered: they change who reaches the project, and only `osh projects settings set` changes them.
        """
        try:
            try:
                change = odouche.ProjectSettingsChange(
                    http_timeout_seconds=http_timeout_seconds,
                    cron_timeout_seconds=cron_timeout_seconds,
                    module_install=module_install,
                    modules=_names(modules),
                    tests=tests,
                    test_tags=test_tags,
                    demo_data=demo_data,
                    ai_agent=ai_agent,
                )
            except ValueError as error:
                raise ToolError(str(error)) from None
            with open_client(changes=allow_changes) as client:
                current = client.project_settings(project)
                narrowed = _refused(partial(client.check_project_settings_change, current, change))
                outcome = odouche.SettingsOutcome(current, current, ())
                if narrowed is not None:
                    # Sent once: an error is reported, never retried.
                    outcome = _refused(partial(client.change_project_settings, project, narrowed))
        except Exception as error:
            _audit("change_project_settings", _target(project), type(error).__name__)
            raise
        changed = [] if narrowed is None else list(narrowed.given())
        unchanged = [name for name in change.given() if name not in changed]
        # The names alone: a value, such as the tags, is the caller's text.
        _audit("change_project_settings", _target(project), f"changed {', '.join(changed) or 'nothing'}")
        return ProjectSettingsChanged(project, changed, unchanged, _moved(outcome), outcome.after)

    return change_project_settings


def _names(modules: str | None) -> tuple[str, ...] | None:
    """Return the module names of a text that separates them by commas."""
    return None if modules is None else tuple(filter(None, map(str.strip, modules.split(","))))


def _moved(outcome: odouche.SettingsOutcome[object]) -> list[MovedSetting]:
    return [
        MovedSetting(name, _plain(getattr(outcome.before, name)), _plain(getattr(outcome.after, name)))
        for name in outcome.moved
    ]


def _plain(value: object) -> SettingValue:
    """Return a setting's value as its JSON has it."""
    if isinstance(value, tuple):
        return [str(name) for name in value]
    if isinstance(value, bool | int) or value is None:
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


def _target(project: str, branch: str | None = None) -> str:
    # The names are third-party text, hence `repr`.
    return f"project={project!r}" if branch is None else f"project={project!r} branch={branch!r}"


def _audit(tool: str, target: str, outcome: str) -> None:
    # Not through `logging`, which a level can silence.
    # A stderr that cannot be written must not make an error of a change that was sent.
    with contextlib.suppress(OSError, ValueError):
        print(f"odouche-mcp: {tool} {target}: {outcome}", file=sys.stderr)  # noqa: T201
