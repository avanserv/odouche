"""The settings of a branch, and the request that changes them."""

from collections.abc import Set
from dataclasses import fields, replace

from odouche._upstream import branches, builds
from odouche._upstream.reader import Reader
from odouche._upstream.transport import Transport, state_changing
from odouche.errors import OdoucheError, OutcomeUnknownError, SettingsConflictError, StageRefusedError
from odouche.models import (
    AiAgent,
    BranchSettings,
    BuildTests,
    ModuleInstall,
    PushBehavior,
    SettingsChange,
    SettingsOutcome,
    Stage,
)


_OPERATION = "branch settings"
_OPERATION_CHANGE = "branch settings change"
_PUSH = {"nothing": PushBehavior.NOTHING, "new": PushBehavior.NEW_BUILD, "update": PushBehavior.UPDATE}
# `none` is the form's "a specific list", which `modules` holds.
_MODULES = {"repo": ModuleInstall.REPOSITORY, "all": ModuleInstall.ALL, "none": ModuleInstall.LISTED}
# `custom` is the form's "Run tests on module selection", and `all` its "Custom test filtering".
_TESTS = {"off": BuildTests.OFF, "custom": BuildTests.MODULES, "all": BuildTests.TAGS}
_AGENTS = {"claude": AiAgent.CLAUDE, "opencode": AiAgent.OPENCODE}
# Written from the tables that read, so that the two cannot drift.
_PUSH_SENT = {member: wire for wire, member in _PUSH.items()}
_MODULES_SENT = {member: wire for wire, member in _MODULES.items()}
_TESTS_SENT = {member: wire for wire, member in _TESTS.items()}
_AGENTS_SENT = {member: wire for wire, member in _AGENTS.items()}
# A checkbox, as the form sends it: its hidden `off` input, or the box's own `on`.
_FLAG = {True: "on", False: "off"}

# What a change can set, in the order of its fields.
_SETTABLE = tuple(field.name for field in fields(SettingsChange))
# The section of the Settings tab the page shows on a development branch only.
_BUILD_OPTIONS = frozenset(
    {"project_defaults", "module_install", "modules", "tests", "test_tags", "demo_data", "ai_agent"}
)


def settings(transport: Transport, branch_id: int) -> BranchSettings:
    """Return the settings of a branch. A value the library does not know raises the changed shape error."""
    builds.number("branch", branch_id)
    answer = Reader(
        _OPERATION,
        transport.call(
            _OPERATION,
            f"/app/branch/{branch_id}/get_settings",
            retry=True,
            not_found=f"The session's user can reach no branch numbered {branch_id}. Odoo.sh gives no reason.",
        ),
    )
    result = answer.child("result")
    modules = result.optional_text("modules")
    return BranchSettings(
        push_behavior=_choice(result, "push_behavior", _PUSH),
        project_defaults=result.boolean("apply_default_settings"),
        module_install=_choice(result, "modules_auto", _MODULES),
        modules=() if modules is None else tuple(name for name in map(str.strip, modules.split(",")) if name),
        tests=_choice(result, "test_mode", _TESTS),
        test_tags=result.optional_text("test_tags"),
        demo_data=result.boolean("demo_data"),
        ai_agent=_choice(result, "ai_agent", _AGENTS),
        odoo_version=result.optional_text("odoo_branch"),
        odoo_revision_id=result.optional_integer("odoo_revision_id"),
        machine=result.text("machine"),
        recommended_machine=result.text("recommended_machine"),
        # A machine's name when set, by the page's script: only `false` was seen.
        next_machine=result.optional_text("machine_next_commit"),
        domains=tuple(result.texts("domains")),
        dns_target=result.optional_text("domain_to_point_to"),
    )


@state_changing
def change_settings(transport: Transport, branch_id: int, change: SettingsChange) -> SettingsOutcome:
    """Send the settings of `change` that differ from the branch's, once, and return them before and after."""
    # The caller's branch may have changed stage since it was read.
    stage = branches.stage(builds.entry(transport, branch_id, 1).child("branch_info").text("stage"))
    current = settings(transport, branch_id)
    narrowed = narrow(stage, current, change)
    if narrowed is None:
        return SettingsOutcome(current, current, ())
    transport.change(_OPERATION_CHANGE, f"/app/branch/{branch_id}/set_settings", _form(narrowed))
    try:
        after = settings(transport, branch_id)
    except OdoucheError:
        after = None
    sent = narrowed.given()
    if after is None:
        found = "the settings could not be read back"
    else:
        unsent = [name for name, value in sent.items() if not _same(after, name, value)]
        if not unsent:
            # Odoo.sh may adjust a setting that depends on one sent, as the page does: reported, not refused.
            moved = tuple(
                name for name in _SETTABLE if name not in sent and not _same(after, name, getattr(current, name))
            )
            return SettingsOutcome(current, after, moved)
        found = f"the settings read back show {', '.join(unsent)} not as sent"
    # Raised out of the handler, and as unknown: an error that reads as a failure invites a second change.
    raise OutcomeUnknownError(
        f"The change of branch {branch_id}'s settings was sent, and {found}. Look before trying again.",
        operation=_OPERATION_CHANGE,
    )


def narrow(stage: Stage, current: BranchSettings, change: SettingsChange) -> SettingsChange | None:
    """Return the part of `change` that differs from `current`, or `None`, refused as the Settings tab refuses it.

    Raises `StageRefusedError` for a setting the tab does not show in that stage, and
    `SettingsConflictError` for one the tab disables, or hides, given the settings after the change.
    """
    differs = {name: value for name, value in change.given().items() if not _same(current, name, value)}
    if not differs:
        return None
    if "push_behavior" in differs and stage is Stage.PRODUCTION:
        msg = "What a new commit does is not changed on a production branch: its Settings tab does not offer it."
        raise StageRefusedError(msg, operation=_OPERATION_CHANGE)
    if differs.keys() & _BUILD_OPTIONS and stage is not Stage.DEVELOPMENT:
        msg = f"The new build options are changed on a development branch only, and this one is {stage.value}."
        raise StageRefusedError(msg, operation=_OPERATION_CHANGE)
    after = replace(current, **differs)  # pyright: ignore[reportArgumentType]
    if differs.keys() & (_BUILD_OPTIONS - {"project_defaults"}) and after.project_defaults:
        msg = (
            "The project's development defaults apply to this branch, so its own new build options are not "
            "changed: turn `project_defaults` off in the same change."
        )
        raise SettingsConflictError(msg)
    _check_options(differs.keys(), after)
    return replace(change, **dict.fromkeys(change.given().keys() - differs.keys()))


def _check_options(changed: Set[str], after: BranchSettings) -> None:
    """Raise `SettingsConflictError` for a changed option the tab hides, given the others after the change."""
    if "modules" in changed and after.module_install is not ModuleInstall.LISTED:
        msg = "`modules` applies only while `module_install` is `listed`: give both in one change."
        raise SettingsConflictError(msg)
    if changed & {"module_install", "modules"} and after.module_install is ModuleInstall.LISTED and not after.modules:
        msg = "`module_install` `listed` installs the modules of `modules`, which names none."
        raise SettingsConflictError(msg)
    if changed & {"tests", "test_tags"} and after.module_install is ModuleInstall.ALL:
        msg = "`tests` and `test_tags` are not offered while `module_install` is `all`, which turns the tests off."
        raise SettingsConflictError(msg)
    if "test_tags" in changed and after.tests is not BuildTests.TAGS:
        msg = "`test_tags` applies only while `tests` is `tags`: give both in one change."
        raise SettingsConflictError(msg)


def _same(read: BranchSettings, name: str, value: object) -> bool:
    held: object = getattr(read, name)
    if name == "test_tags":
        # Odoo.sh gives no tags as `false`, which the page shows as an empty field.
        return (value or None) == (held or None)
    return value == held


def _form(change: SettingsChange) -> dict[str, str]:
    """Return the parameters of a change, one for each setting it gives, as the page's form sends them."""
    sent = {
        "push_behavior": None if change.push_behavior is None else _PUSH_SENT[change.push_behavior],
        "apply_default_settings": None if change.project_defaults is None else _FLAG[change.project_defaults],
        "modules_auto": None if change.module_install is None else _MODULES_SENT[change.module_install],
        "modules": None if change.modules is None else ",".join(change.modules),
        "test_mode": None if change.tests is None else _TESTS_SENT[change.tests],
        "test_tags": change.test_tags,
        "demo_data": None if change.demo_data is None else _FLAG[change.demo_data],
        "ai_agent": None if change.ai_agent is None else _AGENTS_SENT[change.ai_agent],
    }
    return {key: value for key, value in sent.items() if value is not None}


def _choice[E](reader: Reader, key: str, known: dict[str, E]) -> E:
    # Unlike a stage or a status, a setting is read to be written back: an unknown one is not passed through.
    member = known.get(reader.text(key))
    if member is None:
        raise reader.changed(key)
    return member
