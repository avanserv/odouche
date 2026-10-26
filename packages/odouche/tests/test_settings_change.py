import inspect
import json
import traceback

import httpx2
import pytest

from odouche import (
    AiAgent,
    Branch,
    BuildTests,
    Client,
    ModuleInstall,
    OdoucheError,
    OutcomeUnknownError,
    PermissionDeniedError,
    PushBehavior,
    ReadOnlyError,
    Secret,
    SettingsChange,
    SettingsConflictError,
    SettingsOutcome,
    Stage,
    StageRefusedError,
    UpstreamUnavailableError,
)
from odouche._upstream import settings


BRANCH = 51044
BUILDS = "/app/branch/51044/builds"
GET = "/app/branch/51044/get_settings"
SET = "/app/branch/51044/set_settings"
DEVELOPMENT = Branch(BRANCH, "feature-invoicing", Stage.DEVELOPMENT, "dev")
FLAGS = {"apply_default_settings", "demo_data"}
REFUSAL = {"jsonrpc": "2.0", "id": None, "error": {"code": 200, "data": {"name": "builtins.Exception"}}}


def stored(upstream):
    return upstream.bodies[GET]["result"]


def paths(upstream):
    return [request.url.path for request in upstream.requests]


def params(upstream):
    """Return the parameters of each change sent."""
    return [json.loads(request.content)["params"] for request in upstream.requests if request.url.path == SET]


@pytest.fixture(autouse=True)
def saves(upstream):
    """Answer a change as Odoo.sh is taken to: it stores each field sent, and keeps the others."""

    def answer(request):
        for key, value in json.loads(request.content)["params"].items():
            stored(upstream)[key] = value == "on" if key in FLAGS else value or False

        return httpx2.Response(200, json=upstream.load("set_settings.json"))

    upstream.bodies[SET] = answer


@pytest.fixture
def own_options(upstream):
    """Give the branch its own new build options, which the project's defaults otherwise replace."""
    stored(upstream)["apply_default_settings"] = False


def in_stage(upstream, stage):
    upstream.bodies[BUILDS]["result"][0]["branch_info"]["stage"] = stage


@pytest.mark.parametrize(
    ("change", "sent"),
    [
        (SettingsChange(push_behavior=PushBehavior.UPDATE), {"push_behavior": "update"}),
        (SettingsChange(push_behavior=PushBehavior.NOTHING), {"push_behavior": "nothing"}),
        (SettingsChange(module_install=ModuleInstall.ALL), {"modules_auto": "all"}),
        (
            SettingsChange(module_install=ModuleInstall.LISTED, modules=("sale", "purchase")),
            {"modules_auto": "none", "modules": "sale,purchase"},
        ),
        (SettingsChange(tests=BuildTests.OFF), {"test_mode": "off"}),
        (
            SettingsChange(tests=BuildTests.TAGS, test_tags="/sale:TestSaleOrder"),
            {"test_mode": "all", "test_tags": "/sale:TestSaleOrder"},
        ),
        (SettingsChange(demo_data=False), {"demo_data": "off"}),
        (SettingsChange(ai_agent=AiAgent.OPENCODE), {"ai_agent": "opencode"}),
    ],
    ids=lambda value: ",".join(value.given()) if isinstance(value, SettingsChange) else "",
)
@pytest.mark.usefixtures("own_options")
def test_sends_only_the_settings_given_once_and_reads_them_back(client, upstream, change, sent):
    outcome = client.change_branch_settings(BRANCH, change)

    assert paths(upstream) == [BUILDS, GET, SET, GET]
    assert params(upstream) == [sent]
    assert all(getattr(outcome.after, name) == value for name, value in change.given().items())
    assert outcome.moved == ()


def test_the_project_defaults_are_turned_off_alone(client, upstream):
    assert client.change_branch_settings(BRANCH, SettingsChange(project_defaults=False)).after.project_defaults is False
    assert params(upstream) == [{"apply_default_settings": "off"}]


@pytest.mark.usefixtures("own_options")
def test_the_project_defaults_are_turned_back_on_alone(client, upstream):
    assert client.change_branch_settings(BRANCH, SettingsChange(project_defaults=True)).after.project_defaults is True
    assert params(upstream) == [{"apply_default_settings": "on"}]


def test_settings_of_two_sections_go_in_one_request(client, upstream):
    after = client.change_branch_settings(
        BRANCH, SettingsChange(push_behavior=PushBehavior.UPDATE, project_defaults=False, ai_agent=AiAgent.OPENCODE)
    ).after

    assert params(upstream) == [{"push_behavior": "update", "apply_default_settings": "off", "ai_agent": "opencode"}]
    assert (after.push_behavior, after.project_defaults, after.ai_agent) == (
        PushBehavior.UPDATE,
        False,
        AiAgent.OPENCODE,
    )


@pytest.mark.usefixtures("own_options")
def test_tags_are_cleared_with_an_empty_text(client, upstream):
    stored(upstream).update(test_mode="all", test_tags="/sale")

    outcome = client.change_branch_settings(BRANCH, SettingsChange(test_tags=""))

    assert params(upstream) == [{"test_tags": ""}]
    assert (outcome.before.test_tags, outcome.after.test_tags) == ("/sale", None)


@pytest.mark.usefixtures("own_options")
def test_a_setting_that_already_has_its_value_is_not_sent(client, upstream):
    client.change_branch_settings(BRANCH, SettingsChange(push_behavior=PushBehavior.UPDATE, ai_agent=AiAgent.CLAUDE))

    assert params(upstream) == [{"push_behavior": "update"}]


def test_a_change_with_nothing_new_sends_nothing_and_returns_the_settings(client, upstream):
    current = client.branch_settings(BRANCH)
    upstream.requests.clear()

    outcome = client.change_branch_settings(
        BRANCH, SettingsChange(push_behavior=PushBehavior.NEW_BUILD, ai_agent=AiAgent.CLAUDE, test_tags="")
    )

    assert outcome == SettingsOutcome(current, current, ())
    assert paths(upstream) == [BUILDS, GET]


def test_takes_a_branch_or_its_number(client, upstream):
    client.change_branch_settings(DEVELOPMENT, SettingsChange(push_behavior=PushBehavior.UPDATE))

    assert paths(upstream).count(SET) == 1


def test_a_read_only_client_sends_nothing(upstream, session):
    client = Client(Secret(session), read_only=True)

    with pytest.raises(ReadOnlyError) as raised:
        client.change_branch_settings(BRANCH, SettingsChange(push_behavior=PushBehavior.UPDATE))

    assert raised.value.operation == "change_settings"
    assert upstream.requests == []


def test_the_change_is_marked_as_state_changing():
    assert inspect.unwrap(settings.change_settings) is not settings.change_settings


@pytest.mark.parametrize("failure", [502, 500, httpx2.ReadTimeout, httpx2.WriteTimeout, httpx2.RemoteProtocolError])
def test_a_change_that_is_not_confirmed_is_sent_once_and_its_outcome_is_unknown(client, upstream, failure):
    upstream.failures[SET] = failure

    with pytest.raises(OutcomeUnknownError, match="Look before trying again") as raised:
        client.change_branch_settings(BRANCH, SettingsChange(push_behavior=PushBehavior.UPDATE))

    assert raised.value.operation == "branch settings change"
    assert not isinstance(raised.value, UpstreamUnavailableError)
    assert paths(upstream) == [BUILDS, GET, SET]


def test_a_change_odoo_sh_refuses_without_a_reason_is_unknown(client, upstream):
    upstream.bodies[SET] = REFUSAL

    with pytest.raises(OutcomeUnknownError):
        client.change_branch_settings(BRANCH, SettingsChange(push_behavior=PushBehavior.UPDATE))

    assert paths(upstream) == [BUILDS, GET, SET]


@pytest.mark.parametrize("failure", [httpx2.ConnectError, httpx2.ConnectTimeout])
def test_a_change_that_did_not_leave_is_not_repeated(client, upstream, failure):
    upstream.failures[SET] = failure

    with pytest.raises(UpstreamUnavailableError):
        client.change_branch_settings(BRANCH, SettingsChange(push_behavior=PushBehavior.UPDATE))

    assert paths(upstream).count(SET) == 1


def test_an_access_error_is_a_refusal_and_not_unknown(client, upstream):
    upstream.bodies[SET] = upstream.load("access_error.json")

    with pytest.raises(PermissionDeniedError):
        client.change_branch_settings(BRANCH, SettingsChange(push_behavior=PushBehavior.UPDATE))

    assert paths(upstream) == [BUILDS, GET, SET]


def test_settings_read_back_without_the_change_are_unknown(client, upstream):
    upstream.bodies[SET] = upstream.load("set_settings.json")

    with pytest.raises(OutcomeUnknownError, match=r"show push_behavior not as sent\. Look") as raised:
        client.change_branch_settings(BRANCH, SettingsChange(push_behavior=PushBehavior.UPDATE))

    assert raised.value.__context__ is None
    assert paths(upstream) == [BUILDS, GET, SET, GET]


@pytest.mark.usefixtures("own_options")
def test_a_setting_odoo_sh_moves_along_is_reported_and_the_change_succeeds(client, upstream):
    """As the page says Odoo.sh does: installing every module turns the test suite off."""
    keep = upstream.bodies[SET]

    def tests_off(request):
        answer = keep(request)

        if stored(upstream)["modules_auto"] == "all":
            stored(upstream)["test_mode"] = "off"

        return answer

    upstream.bodies[SET] = tests_off
    outcome = client.change_branch_settings(BRANCH, SettingsChange(module_install=ModuleInstall.ALL))

    assert outcome.moved == ("tests",)
    assert (outcome.before.tests, outcome.after.tests) == (BuildTests.MODULES, BuildTests.OFF)
    assert outcome.after.module_install is ModuleInstall.ALL
    assert paths(upstream).count(SET) == 1


@pytest.mark.usefixtures("own_options")
def test_settings_left_out_that_move_are_each_reported(client, upstream):
    """As a server would that reads a checkbox left out as off."""
    stored(upstream).update(modules="sale", test_mode="all", test_tags="/sale")
    keep = upstream.bodies[SET]

    def resets(request):
        stored(upstream).update(demo_data=False, modules=False, test_tags=False)
        return keep(request)

    upstream.bodies[SET] = resets

    assert client.change_branch_settings(BRANCH, SettingsChange(ai_agent=AiAgent.OPENCODE)).moved == (
        "modules",
        "test_tags",
        "demo_data",
    )


def test_a_setting_sent_that_does_not_read_back_is_named_whatever_else_moved(client, upstream):
    def ignores(_):
        stored(upstream)["ai_agent"] = "opencode"
        return httpx2.Response(200, json=upstream.load("set_settings.json"))

    upstream.bodies[SET] = ignores

    with pytest.raises(OutcomeUnknownError) as raised:
        client.change_branch_settings(BRANCH, SettingsChange(push_behavior=PushBehavior.UPDATE))

    assert str(raised.value) == (
        f"The change of branch {BRANCH}'s settings was sent, and the settings read back show push_behavior not as "
        "sent. Look before trying again."
    )


@pytest.mark.parametrize("read_back", [503, 403, {"result": []}, "unauthenticated.json"])
def test_settings_that_cannot_be_read_back_are_unknown(client, upstream, read_back):
    def answer(_):
        if isinstance(read_back, int):
            upstream.failures[GET] = read_back
        else:
            upstream.bodies[GET] = upstream.load(read_back) if isinstance(read_back, str) else read_back

        return httpx2.Response(200, json=upstream.load("set_settings.json"))

    upstream.bodies[SET] = answer

    with pytest.raises(OutcomeUnknownError, match="could not be read back") as raised:
        client.change_branch_settings(BRANCH, SettingsChange(push_behavior=PushBehavior.UPDATE))

    assert raised.value.__context__ is None
    assert paths(upstream).count(SET) == 1


def test_what_a_new_commit_does_is_not_changed_on_production(client, upstream):
    in_stage(upstream, "production")

    with pytest.raises(StageRefusedError, match="production") as raised:
        client.change_branch_settings(BRANCH, SettingsChange(push_behavior=PushBehavior.UPDATE))

    assert raised.value.operation == "branch settings change"
    assert SET not in paths(upstream)


@pytest.mark.parametrize("stage", ["staging", "production", "archived"])
def test_a_new_build_option_is_changed_on_a_development_branch_only(client, upstream, stage):
    in_stage(upstream, stage)

    with pytest.raises(StageRefusedError, match="development branch only"):
        client.change_branch_settings(BRANCH, SettingsChange(project_defaults=False))

    assert SET not in paths(upstream)


def test_a_staging_branch_takes_what_a_new_commit_does(client, upstream):
    in_stage(upstream, "staging")

    assert client.change_branch_settings(
        BRANCH, SettingsChange(push_behavior=PushBehavior.UPDATE)
    ).after.push_behavior is (PushBehavior.UPDATE)


def test_the_stage_is_read_from_odoo_sh_and_not_from_the_branch_given(client, upstream):
    in_stage(upstream, "staging")

    with pytest.raises(StageRefusedError):
        client.change_branch_settings(DEVELOPMENT, SettingsChange(project_defaults=False))

    assert SET not in paths(upstream)


@pytest.mark.parametrize(
    ("current", "change", "message"),
    [
        ({}, SettingsChange(ai_agent=AiAgent.OPENCODE), "project_defaults"),
        ({}, SettingsChange(module_install=ModuleInstall.ALL), "project_defaults"),
        ({"apply_default_settings": False}, SettingsChange(modules=("sale",)), "`modules` applies only"),
        ({"apply_default_settings": False}, SettingsChange(module_install=ModuleInstall.LISTED), "names none"),
        (
            {"apply_default_settings": False, "modules_auto": "none", "modules": "sale"},
            SettingsChange(modules=()),
            "names none",
        ),
        (
            {"apply_default_settings": False, "modules_auto": "all"},
            SettingsChange(tests=BuildTests.OFF),
            "`module_install` is `all`",
        ),
        (
            {"apply_default_settings": False},
            SettingsChange(module_install=ModuleInstall.ALL, tests=BuildTests.OFF),
            "`module_install` is `all`",
        ),
        ({"apply_default_settings": False}, SettingsChange(test_tags="/sale"), "`test_tags` applies only"),
    ],
)
def test_an_option_the_tab_disables_or_hides_is_refused_before_the_request(client, upstream, current, change, message):
    stored(upstream).update(current)

    with pytest.raises(SettingsConflictError, match=message):
        client.change_branch_settings(BRANCH, change)

    assert SET not in paths(upstream)


def test_options_of_their_own_are_given_with_the_defaults_turned_off(client, upstream):
    client.change_branch_settings(BRANCH, SettingsChange(project_defaults=False, ai_agent=AiAgent.OPENCODE))

    assert params(upstream) == [{"apply_default_settings": "off", "ai_agent": "opencode"}]


def test_an_option_already_at_its_value_is_not_refused(client, upstream):
    assert client.change_branch_settings(BRANCH, SettingsChange(ai_agent=AiAgent.CLAUDE)).after.ai_agent is (
        AiAgent.CLAUDE
    )
    assert SET not in paths(upstream)


def test_a_check_narrows_as_the_change_does_and_asks_nothing(upstream, session):
    client = Client(Secret(session), read_only=True)
    current = client.branch_settings(BRANCH)
    production = Branch(1, "main", Stage.PRODUCTION, "production")
    upstream.requests.clear()

    narrowed = client.check_settings_change(
        DEVELOPMENT, current, SettingsChange(push_behavior=PushBehavior.UPDATE, ai_agent=AiAgent.CLAUDE)
    )
    unchanged = client.check_settings_change(DEVELOPMENT, current, SettingsChange(ai_agent=AiAgent.CLAUDE))

    with pytest.raises(StageRefusedError):
        client.check_settings_change(production, current, SettingsChange(push_behavior=PushBehavior.UPDATE))

    with pytest.raises(SettingsConflictError, match="project_defaults"):
        client.check_settings_change(DEVELOPMENT, current, SettingsChange(ai_agent=AiAgent.OPENCODE))

    assert narrowed == SettingsChange(push_behavior=PushBehavior.UPDATE)
    assert unchanged is None
    assert upstream.requests == []


def test_a_change_names_at_least_one_setting():
    with pytest.raises(ValueError, match="at least one"):
        SettingsChange()


@pytest.mark.parametrize("name", ["sale,purchase", "sale purchase", "", "sale\n", "vente_é", "../sale"])
def test_a_module_name_is_letters_digits_and_underscores(name):
    with pytest.raises(ValueError, match="not a module name"):
        SettingsChange(modules=("sale", name))


@pytest.mark.parametrize(
    "tags", ["/sale\n/purchase", "/sale\x1b[2J", "/sale\r", "/sale /purchase", "$(id)", "`id`", "/sale;x", "'/sale'"]
)
def test_test_tags_hold_only_the_characters_of_odoo_tags(tags):
    with pytest.raises(ValueError, match="Test tags hold only"):
        SettingsChange(test_tags=tags)


@pytest.mark.parametrize("tags", ["", "/sale", "-at_install,post_install", "/sale:TestSale.test_x", "*/web[a,b]+x"])
def test_odoo_tags_are_taken(tags):
    assert SettingsChange(test_tags=tags).test_tags == tags


@pytest.mark.parametrize(
    "given",
    [
        {"push_behavior": "update"},
        {"ai_agent": "opencode"},
        {"project_defaults": 0},
        {"demo_data": "no"},
        {"modules": ["sale"]},
        {"test_tags": 1},
    ],
    ids=repr,
)
def test_a_value_of_another_type_is_refused(given):
    with pytest.raises(TypeError, match=next(iter(given))):
        SettingsChange(**given)


def test_a_conflict_is_a_value_error_and_not_an_odouche_error():
    assert issubclass(SettingsConflictError, ValueError)
    assert not issubclass(SettingsConflictError, OdoucheError)


def test_given_lists_the_settings_named_in_field_order():
    change = SettingsChange(ai_agent=AiAgent.CLAUDE, push_behavior=PushBehavior.UPDATE, test_tags="")

    assert change.given() == {"push_behavior": PushBehavior.UPDATE, "test_tags": "", "ai_agent": AiAgent.CLAUDE}


def test_an_unknown_outcome_shows_nothing_of_the_session(client, upstream, session):
    upstream.failures[SET] = httpx2.ReadTimeout

    with pytest.raises(OutcomeUnknownError) as raised:
        client.change_branch_settings(BRANCH, SettingsChange(push_behavior=PushBehavior.UPDATE))

    assert raised.value.__context__ is None
    assert session not in "".join(traceback.format_exception(raised.value))
