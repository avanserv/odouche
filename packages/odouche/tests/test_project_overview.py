import dataclasses
import json
import logging
import traceback

import pytest

from odouche import (
    Branch,
    BranchSummary,
    BuildResult,
    BuildStatus,
    Client,
    NotFoundError,
    PermissionDeniedError,
    ProductionBuild,
    ProjectHosting,
    ProjectOverview,
    Secret,
    Stage,
    StageCount,
    Subscription,
    TrackedBuild,
    UpstreamChangedError,
)
from odouche._upstream import projects


INFO = "/app/project/acme-shop/get_info"
PROJECTS = "/app/projects"
BRANCHES = "/app/project/acme-corp-odoo-addons-4217/branches"
SETTINGS = "/app/project/acme-corp-odoo-addons-4217/get_settings"
TOKEN = "t0k3n-0f-th3-pr0j3ct"
GITHUB = "ghp_" + "x" * 36
CODE = "M999999999999999"
LINK = f"https://accounts.example.com/my/subscription?contract={CODE}"
SECRETS = (TOKEN, GITHUB, CODE, LINK)

OVERVIEW = ProjectOverview(
    id=4217,
    name="acme-shop",
    repository="Acme-Corp/Odoo-Addons",
    subscription=Subscription.VALID,
    subscription_name="valid",
    trial_days_left=None,
    odoo_version="19.0",
    region="Europe",
    dedicated=False,
    production_build=ProductionBuild(id=88001, branch_name="19.0", url="https://acme-shop.odoo.com"),
    access_level="admin",
    hosting=ProjectHosting(
        storage_used_bytes=438272000,
        storage_quota_bytes=1073741824,
        workers=1,
        staging_branches=1,
    ),
    stages=(
        StageCount(Stage.PRODUCTION, "production", 1),
        StageCount(Stage.STAGING, "staging", 1),
        StageCount(Stage.DEVELOPMENT, "dev", 1),
    ),
    branches=(
        BranchSummary(
            Branch(51001, "19.0", Stage.PRODUCTION, "production"),
            TrackedBuild(88001, BuildStatus.DONE, "done", BuildResult.SUCCESS, "success"),
        ),
        BranchSummary(
            Branch(51044, "feature-invoicing", Stage.DEVELOPMENT, "dev"),
            TrackedBuild(88240, BuildStatus.PROGRESS, "progress", None, None),
        ),
        BranchSummary(
            Branch(51020, "staging", Stage.STAGING, "staging"),
            TrackedBuild(88195, BuildStatus.DONE, "done", BuildResult.SUCCESS, "success"),
        ),
    ),
)


def info(upstream):
    return upstream.bodies[INFO]["result"]


def repo(upstream):
    return info(upstream)["active_repo"]


def listed(upstream):
    return upstream.bodies[PROJECTS]["result"]["repos"][0]


def settings(upstream):
    return upstream.bodies[SETTINGS]["result"]["repository"]


def rows(upstream):
    return upstream.bodies[BRANCHES]["result"]


def paths(upstream):
    return [request.url.path for request in upstream.requests]


def with_secrets(upstream):
    info(upstream)["access_token"] = TOKEN
    repo(upstream)["subscription_code"] = CODE
    repo(upstream)["production_build_id"]["enterprise_code"] = CODE
    listed(upstream)["subscription_code"] = CODE
    settings(upstream).update(ci_token=GITHUB, subscription_code=CODE, subscription_code_display=CODE)
    upstream.bodies[SETTINGS]["result"]["upsells"] = {"can_have_worker_upsell_trial": True, "accounts_link": LINK}


def test_reads_the_overview_of_a_project_an_admin_reaches(client, upstream):
    assert client.project_overview("acme-shop") == OVERVIEW
    assert paths(upstream) == [INFO, PROJECTS, BRANCHES, SETTINGS]


def test_takes_a_project_or_its_name(client, upstream):
    project = client.projects()[0]
    upstream.requests.clear()

    assert client.project_overview(project) == OVERVIEW
    assert paths(upstream) == [INFO, PROJECTS, BRANCHES, SETTINGS]


def test_a_read_only_client_reads_it(upstream, session):
    with Client(Secret(session), read_only=True) as client:
        assert client.project_overview("acme-shop") == OVERVIEW


def test_no_token_or_code_reaches_the_overview(client, upstream):
    with_secrets(upstream)

    read = client.project_overview("acme-shop")

    for shown in (repr(read), str(dataclasses.asdict(read)), json.dumps(dataclasses.asdict(read), default=str)):
        assert not [secret for secret in SECRETS if secret in shown]


@pytest.mark.parametrize(
    ("body", "key", "field"),
    [
        (repo, "odoo_branch", "result.active_repo.odoo_branch"),
        (settings, "used_storage", "result.repository.used_storage"),
    ],
)
def test_a_changed_shape_holds_no_token_or_code(client, upstream, session, body, key, field):
    with_secrets(upstream)
    del body(upstream)[key]

    with pytest.raises(UpstreamChangedError) as raised:
        client.project_overview("acme-shop")

    assert raised.value.field == field
    error = raised.value
    assert error.__traceback__ is not None
    # From the client down: the test's own frame holds the session fixture.
    below = traceback.TracebackException(type(error), error, error.__traceback__.tb_next, capture_locals=True)
    shown = "".join(below.format())
    assert f"key = {key!r}" in shown
    assert not [secret for secret in (*SECRETS, session) if secret in shown]


def test_the_info_is_read_without_its_token_and_codes(upstream, session):
    with_secrets(upstream)

    result = projects.info(upstream.connect(Secret(session)), "acme-shop")
    active = result.child("active_repo")
    assert (result.has("access_token"), active.has("subscription_code")) == (False, False)
    assert active.child("production_build_id").has("enterprise_code") is False
    assert (result.has("user"), active.has("odoo_branch")) == (True, True)


def test_the_settings_are_read_without_their_subscription_link(upstream, session):
    with_secrets(upstream)

    answer = projects.settings_answer(upstream.connect(Secret(session)), "acme-corp-odoo-addons-4217")

    assert (answer.has("upsells"), answer.has("repository")) == (False, True)


@pytest.mark.parametrize(
    ("key", "value"),
    [("session_lifetime", "12-days"), ("submodules", [{"id": "71001", "deploy_key_public": "-----BEGIN"}])],
)
def test_a_setting_the_overview_does_not_read_cannot_break_it(client, upstream, key, value):
    upstream.bodies[SETTINGS]["result"][key] = value

    assert client.project_overview("acme-shop") == OVERVIEW


def test_the_projects_are_read_without_their_codes(upstream, session):
    with_secrets(upstream)

    read = projects._repos(upstream.connect(Secret(session)))  # pyright: ignore[reportPrivateUsage]

    assert [(repo.has("subscription_code"), repo.has("geolocation")) for repo in read] == [(False, True)] * 2


def test_a_project_the_listing_leaves_out_is_not_found(client, upstream):
    listed(upstream)["project_name"] = "renamed"

    with pytest.raises(NotFoundError, match="'acme-shop'") as raised:
        client.project_overview("acme-shop")

    assert raised.value.operation == "projects"
    assert paths(upstream) == [INFO, PROJECTS]


def test_a_changed_shape_in_the_info_sends_nothing_more(client, upstream):
    del repo(upstream)["odoo_branch"]

    with pytest.raises(UpstreamChangedError):
        client.project_overview("acme-shop")

    assert paths(upstream) == [INFO]


@pytest.mark.parametrize("access", ["developer", "tester"])
def test_the_settings_are_not_asked_below_admin(client, upstream, access):
    info(upstream)["user"]["access"] = access
    read = client.project_overview("acme-shop")

    assert read == dataclasses.replace(OVERVIEW, access_level=access, hosting=None)
    assert paths(upstream) == [INFO, PROJECTS, BRANCHES]


def test_an_access_the_map_does_not_hold_is_a_changed_shape(client, upstream):
    info(upstream)["user"]["access"] = "owner"

    with pytest.raises(UpstreamChangedError) as raised:
        client.project_overview("acme-shop")

    assert raised.value.operation == "project"
    assert raised.value.field == "result.config.access_level_map.owner"


@pytest.mark.parametrize(
    ("name", "subscription"),
    [
        ("valid", Subscription.VALID),
        ("trial", Subscription.TRIAL),
        ("custom", Subscription.NON_STANDARD),
        ("invalid", Subscription.EXPIRED),
    ],
)
def test_reads_each_subscription_the_page_names(client, upstream, name, subscription):
    repo(upstream)["subscription_validity"] = name
    read = client.project_overview("acme-shop")

    assert (read.subscription, read.subscription_name) == (subscription, name)


def test_an_unseen_subscription_is_unknown_and_keeps_its_name(client, upstream, caplog):
    repo(upstream)["subscription_validity"] = "suspended"

    with caplog.at_level(logging.DEBUG, logger="odouche"):
        read = client.project_overview("acme-shop")

    assert (read.subscription, read.subscription_name) == (Subscription.UNKNOWN, "suspended")
    assert "Unknown subscription state: 'suspended'" in caplog.messages


def test_reads_a_project_with_no_production_build_and_a_trial(client, upstream):
    repo(upstream).update(production_build_id=False, production_expiration_days_left=12, pays_dedicated=True)

    read = client.project_overview("acme-shop")

    assert (read.production_build, read.trial_days_left, read.dedicated) == (None, 12, True)


def test_counts_each_known_stage_even_empty_then_the_unknown_ones(client, upstream):
    rows(upstream)[2]["stage"] = "dev"
    rows(upstream).append({**rows(upstream)[1], "id": 51090, "name": "review", "stage": "qa"})

    read = client.project_overview("acme-shop")

    assert read.stages == (
        StageCount(Stage.PRODUCTION, "production", 1),
        StageCount(Stage.STAGING, "staging", 0),
        StageCount(Stage.DEVELOPMENT, "dev", 2),
        StageCount(Stage.UNKNOWN, "qa", 1),
    )


def test_a_branch_with_no_build_has_no_last_build(client, upstream):
    rows(upstream)[1].update(last_build_id=False, last_build_status=False, last_build_result=False)

    assert client.project_overview("acme-shop").branches[1].last_build is None


@pytest.mark.parametrize(
    ("body", "key", "field"),
    [
        (repo, key, f"result.active_repo.{key}")
        for key in ("id", "owner", "name", "project_name", "technical_name", "subscription_validity", "odoo_branch")
    ]
    + [(repo, "pays_dedicated", "result.active_repo.pays_dedicated")]
    + [
        (settings, key, f"result.repository.{key}")
        for key in (
            "used_storage",
            "max_storage",
            "max_production_workers",
            "max_staging_branches",
        )
    ]
    + [(lambda upstream: rows(upstream)[1], "last_build_status", "result[1].last_build_status")]
    + [(listed, "geolocation", "result.repos[0].geolocation")],
)
@pytest.mark.parametrize("change", ["missing", "null", "list"])
def test_names_the_field_that_changed_shape(client, upstream, body, key, field, change):
    fields = body(upstream)

    if change == "missing":
        del fields[key]
    else:
        fields[key] = {"null": None, "list": [fields[key]]}[change]

    with pytest.raises(UpstreamChangedError) as raised:
        client.project_overview("acme-shop")

    assert raised.value.field == field


@pytest.mark.parametrize(
    ("path", "body", "field"),
    [
        (INFO, {}, "result"),
        (INFO, {"result": []}, "result"),
        (SETTINGS, {"result": {"repository": []}}, "result.repository"),
    ],
)
def test_an_answer_without_its_object_is_named(client, upstream, path, body, field):
    upstream.bodies[path] = body

    with pytest.raises(UpstreamChangedError) as raised:
        client.project_overview("acme-shop")

    assert raised.value.field == field


def test_a_negative_storage_is_a_changed_shape(client, upstream):
    settings(upstream)["used_storage"] = -1.0

    with pytest.raises(UpstreamChangedError) as raised:
        client.project_overview("acme-shop")

    assert (raised.value.operation, raised.value.field) == ("project settings", "result.repository.used_storage")


def test_another_project_answered_is_a_changed_shape(client, upstream):
    repo(upstream)["project_name"] = "intranet"

    with pytest.raises(UpstreamChangedError) as raised:
        client.project_overview("acme-shop")

    assert raised.value.field == "result.active_repo.project_name"
    assert paths(upstream) == [INFO]


def test_a_project_the_user_cannot_reach_is_not_found(client, upstream):
    upstream.bodies["/app/project/other/get_info"] = {"error": {"data": {"name": "builtins.Exception"}}}

    with pytest.raises(NotFoundError, match="'other'"):
        client.project_overview("other")


@pytest.mark.parametrize(("path", "operation"), [(BRANCHES, "branches"), (SETTINGS, "project settings")])
def test_a_refused_request_is_denied(client, upstream, path, operation):
    upstream.bodies[path] = upstream.load("access_error.json")

    with pytest.raises(PermissionDeniedError) as raised:
        client.project_overview("acme-shop")

    assert raised.value.operation == operation


@pytest.mark.parametrize(
    ("technical_name", "sent"),
    [
        ("../branch/1/rebuild?x=", "%2E%2E%2Fbranch%2F1%2Frebuild%3Fx%3D"),
        ("..", "%2E%2E"),
    ],
)
def test_the_name_odoo_sh_gives_cannot_change_the_addresses(client, upstream, technical_name, sent):
    repo(upstream)["technical_name"] = technical_name
    upstream.bodies[f"/app/project/{technical_name}/branches"] = upstream.bodies[BRANCHES]
    upstream.bodies[f"/app/project/{technical_name}/get_settings"] = upstream.bodies[SETTINGS]

    client.project_overview("acme-shop")

    assert [request.url.raw_path for request in upstream.requests[2:]] == [
        f"/app/project/{sent}/branches".encode(),
        f"/app/project/{sent}/get_settings".encode(),
    ]


def test_the_overview_is_frozen(client):
    read = client.project_overview("acme-shop")

    with pytest.raises(dataclasses.FrozenInstanceError):
        read.name = "other"
