import dataclasses
import traceback

import pytest

from odouche import (
    AiAgent,
    Branch,
    BranchSettings,
    BuildTests,
    Client,
    ModuleInstall,
    NotFoundError,
    PushBehavior,
    Secret,
    Stage,
    UpstreamChangedError,
)


PATH = "/app/branch/51044/get_settings"
BRANCH = 51044
READ = [
    "push_behavior",
    "apply_default_settings",
    "modules_auto",
    "modules",
    "test_mode",
    "test_tags",
    "demo_data",
    "ai_agent",
    "odoo_branch",
    "odoo_revision_id",
    "machine",
    "recommended_machine",
    "machine_next_commit",
    "domains",
    "domain_to_point_to",
]


def result(upstream):
    return upstream.bodies[PATH]["result"]


def test_reads_a_development_branch(client):
    assert client.branch_settings(BRANCH) == BranchSettings(
        push_behavior=PushBehavior.NEW_BUILD,
        project_defaults=True,
        module_install=ModuleInstall.REPOSITORY,
        modules=(),
        tests=BuildTests.MODULES,
        test_tags=None,
        demo_data=True,
        ai_agent=AiAgent.CLAUDE,
        odoo_version=None,
        odoo_revision_id=None,
        machine="ubuntu-24.04",
        recommended_machine="ubuntu-24.04",
        next_machine=None,
        domains=(),
        dns_target="acme-shop-feature-invoicing-88240.dev.odoo.com",
    )


def test_reads_every_value_a_setting_can_take(client, upstream):
    result(upstream).update(
        push_behavior="update",
        apply_default_settings=False,
        modules_auto="none",
        modules="sale, purchase,,",
        test_mode="all",
        test_tags="/sale:TestSaleOrder",
        demo_data=False,
        ai_agent="opencode",
        odoo_branch="18.0",
        odoo_revision_id=4021,
        machine_next_commit="ubuntu-26.04",
        domains=["www.example.com"],
        domain_to_point_to="acme-shop.example.com",
    )

    read = client.branch_settings(BRANCH)

    assert read.push_behavior is PushBehavior.UPDATE
    assert read.project_defaults is False
    assert (read.module_install, read.modules) == (ModuleInstall.LISTED, ("sale", "purchase"))
    assert (read.tests, read.test_tags) == (BuildTests.TAGS, "/sale:TestSaleOrder")
    assert read.demo_data is False
    assert read.ai_agent is AiAgent.OPENCODE
    assert (read.odoo_version, read.odoo_revision_id) == ("18.0", 4021)
    assert read.next_machine == "ubuntu-26.04"
    assert read.domains == ("www.example.com",)
    assert read.dns_target == "acme-shop.example.com"


def test_the_stored_modules_and_tags_are_given_whatever_the_choice(client, upstream):
    result(upstream).update(modules="sale", test_tags="/sale")

    read = client.branch_settings(BRANCH)

    assert (read.module_install, read.modules) == (ModuleInstall.REPOSITORY, ("sale",))
    assert (read.tests, read.test_tags) == (BuildTests.MODULES, "/sale")


@pytest.mark.parametrize(
    ("key", "value", "field", "member"),
    [
        ("push_behavior", "nothing", "push_behavior", PushBehavior.NOTHING),
        ("modules_auto", "all", "module_install", ModuleInstall.ALL),
        ("test_mode", "off", "tests", BuildTests.OFF),
    ],
)
def test_reads_the_values_offered_and_not_seen(client, upstream, key, value, field, member):
    result(upstream)[key] = value

    assert getattr(client.branch_settings(BRANCH), field) is member


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("push_behavior", "rebuild-unseen"),
        ("modules_auto", "some-unseen"),
        ("test_mode", "fast-unseen"),
        ("ai_agent", "codex-unseen"),
    ],
)
def test_an_unknown_value_raises_the_changed_shape_error_without_it(client, upstream, key, value):
    result(upstream)[key] = value

    with pytest.raises(UpstreamChangedError) as raised:
        client.branch_settings(BRANCH)

    assert raised.value.operation == "branch settings"
    assert raised.value.field == f"result.{key}"
    assert value not in "".join(traceback.format_exception(raised.value))


@pytest.mark.parametrize("key", READ)
def test_a_missing_field_is_named(client, upstream, key):
    del result(upstream)[key]

    with pytest.raises(UpstreamChangedError) as raised:
        client.branch_settings(BRANCH)

    assert raised.value.field == f"result.{key}"


@pytest.mark.parametrize(
    ("key", "value", "field"),
    [
        ("domains", ["www.example.com", 1], "result.domains[1]"),
        ("domains", False, "result.domains"),
        ("odoo_revision_id", True, "result.odoo_revision_id"),
        ("machine_next_commit", True, "result.machine_next_commit"),
        ("apply_default_settings", "on", "result.apply_default_settings"),
        ("modules", ["sale"], "result.modules"),
    ],
)
def test_a_field_of_another_type_is_named(client, upstream, key, value, field):
    result(upstream)[key] = value

    with pytest.raises(UpstreamChangedError) as raised:
        client.branch_settings(BRANCH)

    assert raised.value.field == field


@pytest.mark.parametrize("body", [{}, {"result": []}])
def test_an_answer_without_its_result_is_named(client, upstream, body):
    upstream.bodies[PATH] = body

    with pytest.raises(UpstreamChangedError) as raised:
        client.branch_settings(BRANCH)

    assert raised.value.field == "result"


def test_takes_a_branch_or_its_number(client):
    branch = Branch(BRANCH, "feature-invoicing", Stage.DEVELOPMENT, "dev")

    assert client.branch_settings(branch) == client.branch_settings(BRANCH)


@pytest.mark.parametrize("branch", ["51044", True, 51044.0])
def test_a_branch_that_is_not_an_integer_is_refused(client, upstream, branch):
    with pytest.raises(TypeError):
        client.branch_settings(branch)

    assert upstream.requests == []


def test_a_read_only_client_reads_them_in_one_request(upstream, session):
    with Client(Secret(session), read_only=True) as client:
        client.branch_settings(BRANCH)

    assert [(request.method, request.url.path) for request in upstream.requests] == [("POST", PATH)]


def test_a_branch_out_of_reach_is_not_found(client, upstream):
    upstream.failures[PATH] = 404

    with pytest.raises(NotFoundError):
        client.branch_settings(BRANCH)


def test_a_branch_odoo_sh_refuses_without_a_reason_is_not_found(client, upstream):
    upstream.bodies[PATH] = {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": 200, "message": "Odoo Server Error", "data": {"name": "builtins.Exception"}},
    }

    with pytest.raises(NotFoundError, match=f"no branch numbered {BRANCH}") as raised:
        client.branch_settings(BRANCH)

    assert raised.value.operation == "branch settings"


def test_the_settings_are_frozen_and_named_as_documented(client):
    read = client.branch_settings(BRANCH)

    assert [field.name for field in dataclasses.fields(read)] == [
        "push_behavior",
        "project_defaults",
        "module_install",
        "modules",
        "tests",
        "test_tags",
        "demo_data",
        "ai_agent",
        "odoo_version",
        "odoo_revision_id",
        "machine",
        "recommended_machine",
        "next_machine",
        "domains",
        "dns_target",
    ]

    with pytest.raises(dataclasses.FrozenInstanceError):
        read.demo_data = False
