"""The settings of a branch."""

from odouche._upstream import builds
from odouche._upstream.reader import Reader
from odouche._upstream.transport import Transport
from odouche.models import AiAgent, BranchSettings, BuildTests, ModuleInstall, PushBehavior


_OPERATION = "branch settings"
_PUSH = {"nothing": PushBehavior.NOTHING, "new": PushBehavior.NEW_BUILD, "update": PushBehavior.UPDATE}
# `none` is the form's "a specific list", which `modules` holds.
_MODULES = {"repo": ModuleInstall.REPOSITORY, "all": ModuleInstall.ALL, "none": ModuleInstall.LISTED}
# `custom` is the form's "Run tests on module selection", and `all` its "Custom test filtering".
_TESTS = {"off": BuildTests.OFF, "custom": BuildTests.MODULES, "all": BuildTests.TAGS}
_AGENTS = {"claude": AiAgent.CLAUDE, "opencode": AiAgent.OPENCODE}


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


def _choice[E](reader: Reader, key: str, known: dict[str, E]) -> E:
    # Unlike a stage or a status, a setting is read to be written back: an unknown one is not passed through.
    member = known.get(reader.text(key))
    if member is None:
        raise reader.changed(key)
    return member
