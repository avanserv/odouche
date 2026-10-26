import dataclasses
import json
import logging
import traceback
from ipaddress import ip_address, ip_network

import httpx2
import pytest

from odouche import (
    AiAgent,
    BuildTests,
    Client,
    ModuleInstall,
    NotFoundError,
    PermissionDeniedError,
    ProjectHosting,
    ProjectSettings,
    Secret,
    SessionLifetime,
    Submodule,
    UpstreamChangedError,
)
from odouche._upstream import projects


INFO = "/app/project/acme-shop/get_info"
SETTINGS = "/app/project/acme-corp-odoo-addons-4217/get_settings"
GITHUB = "ghp_" + "x" * 36
CODE = "M999999999999999"
LINK = f"https://accounts.example.com/my/subscription?contract={CODE}"
PRIVATE_KEY = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAAc2VjcmV0\n-----END OPENSSH PRIVATE KEY-----"
PASSWORD = "p4ss-" + "x" * 16
SECRETS = (GITHUB, CODE, PASSWORD)
PUBLIC_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEFjbWVJbnZlbnRlZEtleUZvclRlc3RzT25seTAwMDA= odoo.sh"
FINGERPRINT = "SHA256:aW52ZW50ZWQgZmluZ2VycHJpbnQgZm9yIHRlc3Rz"
SUBMODULE = {
    "id": 71001,
    "name": "git@github.com:acme-corp/acme-theme.git",
    "deploy_key_public_fingerprint": FINGERPRINT,
    "deploy_key_public": PUBLIC_KEY,
}

SETTINGS_READ = ProjectSettings(
    name="acme-shop",
    odoo_domain_blocked=False,
    session_lifetime=SessionLifetime.AUTO,
    public=False,
    commit_statuses_suspended=False,
    deploy_key_writable=False,
    submodules=(),
    hosting=ProjectHosting(
        storage_used_bytes=438272000,
        storage_quota_bytes=1073741824,
        workers=1,
        staging_branches=1,
    ),
    dedicated=False,
    http_timeout_seconds=900,
    cron_timeout_seconds=900,
    module_install=ModuleInstall.REPOSITORY,
    modules=(),
    tests=BuildTests.MODULES,
    test_tags=None,
    demo_data=True,
    ai_agent=AiAgent.CLAUDE,
    ip_allow_list=(),
)


def result(upstream):
    return upstream.bodies[SETTINGS]["result"]


def repo(upstream):
    return result(upstream)["repository"]


def limit(upstream, key="limit_real_time"):
    return result(upstream)["dedicated_limits"][key]


def paths(upstream):
    return [request.url.path for request in upstream.requests]


def with_secrets(upstream):
    repo(upstream).update(ci_token=GITHUB, subscription_code=CODE, subscription_code_display=CODE)
    result(upstream)["upsells"] = {"can_have_worker_upsell_trial": True, "accounts_link": LINK}
    url = f"https://x-access-token:{PASSWORD}@github.com/acme-corp/acme-theme.git?token={PASSWORD}"
    result(upstream)["submodules"] = [{**SUBMODULE, "name": url}]


def test_reads_the_settings_of_a_project_an_admin_reaches(client, upstream):
    assert client.project_settings("acme-shop") == SETTINGS_READ
    assert paths(upstream) == [INFO, SETTINGS]


def test_reads_every_setting_set_otherwise(client, upstream):
    repo(upstream).update(
        block_odoo_domain=True,
        private=False,
        ci_suspended=True,
        deploy_key_writable=True,
        pays_dedicated=True,
        modules_auto="none",
        modules="sale, stock,,account",
        test_mode="all",
        test_tags="/sale:TestSale",
        demo_data=False,
        ai_agent="opencode",
        ip_whitelist="198.51.100.42\n203.0.113.10\n2001:db8::1",
    )
    result(upstream).update(session_lifetime="4-days", submodules=[SUBMODULE])
    limit(upstream)["value"] = 2.5
    limit(upstream, "limit_real_time_cron").update(value=1, unit_conversion=3600)

    read = client.project_settings("acme-shop")

    assert read == dataclasses.replace(
        SETTINGS_READ,
        odoo_domain_blocked=True,
        session_lifetime=SessionLifetime.FOUR_DAYS,
        public=True,
        commit_statuses_suspended=True,
        deploy_key_writable=True,
        submodules=(Submodule(71001, "git@github.com:acme-corp/acme-theme.git", FINGERPRINT, PUBLIC_KEY),),
        dedicated=True,
        http_timeout_seconds=150,
        cron_timeout_seconds=3600,
        module_install=ModuleInstall.LISTED,
        modules=("sale", "stock", "account"),
        tests=BuildTests.TAGS,
        test_tags="/sale:TestSale",
        demo_data=False,
        ai_agent=AiAgent.OPENCODE,
        ip_allow_list=(ip_address("198.51.100.42"), ip_address("203.0.113.10"), ip_address("2001:db8::1")),
    )


@pytest.mark.parametrize(
    ("key", "member"),
    [
        ("auto", SessionLifetime.AUTO),
        ("4-hours", SessionLifetime.FOUR_HOURS),
        ("8-hours", SessionLifetime.EIGHT_HOURS),
        ("1-day", SessionLifetime.ONE_DAY),
        ("2-days", SessionLifetime.TWO_DAYS),
        ("4-days", SessionLifetime.FOUR_DAYS),
        ("8-days", SessionLifetime.EIGHT_DAYS),
    ],
)
def test_reads_each_session_lifetime_the_page_offers(client, upstream, key, member):
    result(upstream)["session_lifetime"] = key

    assert client.project_settings("acme-shop").session_lifetime is member


def test_takes_a_project_or_its_name(client, upstream):
    project = client.projects()[0]
    upstream.requests.clear()

    assert client.project_settings(project) == SETTINGS_READ
    assert paths(upstream) == [INFO, SETTINGS]


def test_a_read_only_client_reads_them(upstream, session):
    with Client(Secret(session), read_only=True) as client:
        assert client.project_settings("acme-shop") == SETTINGS_READ


@pytest.mark.parametrize(
    ("listed", "addresses"),
    [
        ("", ()),
        ("\n\n", ()),
        ("198.51.100.42\r\n203.0.113.10\r\n", (ip_address("198.51.100.42"), ip_address("203.0.113.10"))),
        ("  203.0.113.10  \n\n198.51.100.42", (ip_address("203.0.113.10"), ip_address("198.51.100.42"))),
        ("2001:db8::1\n198.51.100.42", (ip_address("2001:db8::1"), ip_address("198.51.100.42"))),
        ("198.51.100.42/32\n198.51.100.42", (ip_network("198.51.100.42/32"), ip_address("198.51.100.42"))),
        ("203.0.113.0/24\n2001:db8::/32", (ip_network("203.0.113.0/24"), ip_network("2001:db8::/32"))),
        ("203.0.113.7/24", (ip_network("203.0.113.0/24"),)),
    ],
)
def test_reads_the_allowed_addresses_and_networks_in_their_order(client, upstream, listed, addresses):
    repo(upstream)["ip_whitelist"] = listed

    assert client.project_settings("acme-shop").ip_allow_list == addresses


@pytest.mark.parametrize("entry", ["198.51.100.300", "203.0.113.0/33", "host.example.com", "198.51.100.42 # office"])
def test_an_allowed_entry_that_is_no_address_or_network_is_a_changed_shape_without_it(client, upstream, entry):
    repo(upstream)["ip_whitelist"] = f"198.51.100.42\n{entry}"

    with pytest.raises(UpstreamChangedError) as raised:
        client.project_settings("acme-shop")

    assert (raised.value.operation, raised.value.field) == ("project settings", "result.repository.ip_whitelist")
    assert raised.value.__suppress_context__
    assert entry not in str(raised.value)


@pytest.mark.parametrize(
    ("body", "key", "field"),
    [
        (result, "session_lifetime", "result.session_lifetime"),
        (repo, "modules_auto", "result.repository.modules_auto"),
        (repo, "test_mode", "result.repository.test_mode"),
        (repo, "ai_agent", "result.repository.ai_agent"),
    ],
)
def test_an_unknown_choice_is_a_changed_shape_without_it(client, upstream, body, key, field):
    body(upstream)[key] = "s0m3th1ng-n3w"

    with pytest.raises(UpstreamChangedError) as raised:
        client.project_settings("acme-shop")

    assert raised.value.field == field
    assert "s0m3th1ng-n3w" not in str(raised.value)


@pytest.mark.parametrize(
    ("key", "value"),
    [("value", -1.0), ("value", float("nan")), ("value", float("inf")), ("unit_conversion", 0)],
)
def test_a_timeout_out_of_range_is_a_changed_shape(client, upstream, key, value):
    limit(upstream, "limit_real_time_cron")[key] = value
    # `NaN` and `Infinity` are not JSON, and Python's parser reads them still.
    body = json.dumps(upstream.bodies[SETTINGS])
    upstream.bodies[SETTINGS] = lambda _: httpx2.Response(
        200, content=body, headers={"Content-Type": "application/json"}
    )

    with pytest.raises(UpstreamChangedError) as raised:
        client.project_settings("acme-shop")

    assert raised.value.field == f"result.dedicated_limits.limit_real_time_cron.{key}"


@pytest.mark.parametrize(
    "key",
    [
        PRIVATE_KEY,
        f"{PUBLIC_KEY}\n{PRIVATE_KEY}",
        "ssh-ed25519",
        "rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQ==",
        "ssh-ed25519 AAAA=C3Nz",
        "",
    ],
)
def test_a_deploy_key_that_is_no_public_key_is_a_changed_shape_without_it(client, upstream, key):
    result(upstream)["submodules"] = [{**SUBMODULE, "deploy_key_public": key}]

    with pytest.raises(UpstreamChangedError) as raised:
        client.project_settings("acme-shop")

    assert raised.value.field == "result.submodules[0].deploy_key_public"
    assert "PRIVATE KEY" not in str(raised.value)


def test_a_private_key_is_held_by_no_frame_of_the_error(client, upstream):
    result(upstream)["submodules"] = [{**SUBMODULE, "deploy_key_public": PRIVATE_KEY}]

    with pytest.raises(UpstreamChangedError) as raised:
        client.project_settings("acme-shop")

    error = raised.value
    assert error.__traceback__ is not None
    # From the client down: the test's own frame holds the key.
    below = traceback.TracebackException(type(error), error, error.__traceback__.tb_next, capture_locals=True)
    assert "PRIVATE KEY" not in "".join(below.format())


@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_a_deploy_key_is_read_without_its_line_break(client, upstream, ending):
    result(upstream)["submodules"] = [{**SUBMODULE, "deploy_key_public": PUBLIC_KEY + ending}]

    assert client.project_settings("acme-shop").submodules[0].public_key == PUBLIC_KEY


THEME = "github.com/acme-corp/acme-theme.git"


@pytest.mark.parametrize(
    ("url", "read"),
    [
        (f"https://x-access-token:s3cr3t@{THEME}", f"https://{THEME}"),
        (f"https://ghp_s3cr3t@{THEME}", f"https://{THEME}"),
        (f"https://acme:p@ss@{THEME}", f"https://{THEME}"),
        ("https://github.com/acme-corp/acme-theme@v1.git", "https://github.com/acme-corp/acme-theme@v1.git"),
        # A password and an `@` in the path cannot be told from a password that holds a `/`.
        ("https://u:s3cr3t@github.com/acme-corp/acme-theme@v1.git", ""),
        ("https://u@github.com/acme-corp/acme-theme@v1.git", "https://github.com/acme-corp/acme-theme@v1.git"),
        ("git@github.com:acme-corp/acme-theme@v1.git", "git@github.com:acme-corp/acme-theme@v1.git"),
        ("github.com:acme-corp/acme-theme@v1.git", "github.com:acme-corp/acme-theme@v1.git"),
        (f"https://acme:p@ss/w0rd@{THEME}", ""),
        (f"https://acme:p4ss/w0rd@{THEME}", ""),
        ("https://[2001:db8::1]:8443/acme-corp/acme-theme.git", "https://[2001:db8::1]:8443/acme-corp/acme-theme.git"),
        (f"https://u:s3cr3t@[2001:db8::1]:8443/{THEME}", f"https://[2001:db8::1]:8443/{THEME}"),
        (f"https://github.com:s3cr3t/{THEME}", ""),
        (f"ssh://ghp_s3cr3t@{THEME}", f"ssh://{THEME}"),
        (f"ssh://github_pat_s3cr3t@{THEME}", f"ssh://{THEME}"),
        (f"ssh://glpat-s3cr3t@{THEME}", f"ssh://{THEME}"),
        (f"ssh://x-access-token@{THEME}", f"ssh://{THEME}"),
        (f"ssh://Git@{THEME}", f"ssh://{THEME}"),
        (f"ssh://{'a' * 33}@{THEME}", f"ssh://{THEME}"),
        ("ghs_s3cr3t@github.com:acme-corp/acme-theme.git", "github.com:acme-corp/acme-theme.git"),
        ("deploy_bot@github.com:acme-corp/acme-theme.git", "deploy_bot@github.com:acme-corp/acme-theme.git"),
        (f"https://{THEME}?access_token=s3cr3t", f"https://{THEME}"),
        (f"https://{THEME}#s3cr3t", f"https://{THEME}"),
        (f"https://{THEME}", f"https://{THEME}"),
        (f"HTTPS://{THEME}", f"HTTPS://{THEME}"),
        (f"ssh://git@{THEME}", f"ssh://git@{THEME}"),
        (f"git+ssh://git@{THEME}", f"git+ssh://git@{THEME}"),
        (f"ssh://git:s3cr3t@{THEME}", f"ssh://{THEME}"),
        ("git@github.com:acme-corp/acme-theme.git", "git@github.com:acme-corp/acme-theme.git"),
        ("user:s3cr3t@github.com:acme-corp/acme-theme.git", "github.com:acme-corp/acme-theme.git"),
        (f"oauth2:s3cr3t@{THEME}", THEME),
        (f"https:user:s3cr3t@{THEME}", THEME),
        (f"user:s3cr3t://x@{THEME}", ""),
        ("github.com:acme-corp/acme-theme.git?s3cr3t", "github.com:acme-corp/acme-theme.git"),
    ],
)
def test_a_submodule_url_is_read_without_its_credentials_query_or_fragment(client, upstream, url, read):
    result(upstream)["submodules"] = [{**SUBMODULE, "name": url}]

    assert client.project_settings("acme-shop").submodules[0].url == read


@pytest.mark.parametrize(
    ("body", "key", "field"),
    [
        (repo, key, f"result.repository.{key}")
        for key in (
            "project_name",
            "block_odoo_domain",
            "private",
            "ci_suspended",
            "deploy_key_writable",
            "pays_dedicated",
            "demo_data",
            "ip_whitelist",
            "used_storage",
        )
    ]
    + [(result, key, f"result.{key}") for key in ("session_lifetime", "dedicated_limits")]
    + [(limit, key, f"result.dedicated_limits.limit_real_time.{key}") for key in ("value", "unit_conversion")],
)
@pytest.mark.parametrize("change", ["missing", "null", "list"])
def test_names_the_field_that_changed_shape(client, upstream, body, key, field, change):
    fields = body(upstream)

    if change == "missing":
        del fields[key]
    else:
        fields[key] = {"null": None, "list": [fields[key]]}[change]

    with pytest.raises(UpstreamChangedError) as raised:
        client.project_settings("acme-shop")

    assert raised.value.field == field


@pytest.mark.parametrize(
    ("value", "field"), [(None, "result.submodules"), ({}, "result.submodules"), ([[]], "result.submodules[0]")]
)
def test_submodules_that_are_no_list_of_objects_are_named(client, upstream, value, field):
    result(upstream)["submodules"] = value

    with pytest.raises(UpstreamChangedError) as raised:
        client.project_settings("acme-shop")

    assert raised.value.field == field


@pytest.mark.parametrize("key", ["id", "name", "deploy_key_public_fingerprint", "deploy_key_public"])
def test_names_the_field_of_a_submodule_that_changed_shape(client, upstream, key):
    result(upstream)["submodules"] = [SUBMODULE, {**SUBMODULE, key: None}]

    with pytest.raises(UpstreamChangedError) as raised:
        client.project_settings("acme-shop")

    assert raised.value.field == f"result.submodules[1].{key}"


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (INFO, lambda upstream: upstream.bodies[INFO]["result"]["active_repo"]),
        (SETTINGS, repo),
    ],
)
def test_another_project_answered_is_a_changed_shape(client, upstream, path, body):
    body(upstream)["project_name"] = "intranet"

    with pytest.raises(UpstreamChangedError) as raised:
        client.project_settings("acme-shop")

    assert raised.value.field.endswith(".project_name")
    assert paths(upstream)[-1] == path


@pytest.mark.parametrize("access", ["developer", "tester"])
def test_below_admin_it_is_denied_without_asking_for_the_settings(client, upstream, access):
    upstream.bodies[INFO]["result"]["user"]["access"] = access

    with pytest.raises(PermissionDeniedError, match="admins only") as raised:
        client.project_settings("acme-shop")

    assert raised.value.operation == "project settings"
    assert paths(upstream) == [INFO]


def test_refused_settings_are_denied(client, upstream):
    upstream.bodies[SETTINGS] = upstream.load("access_error.json")

    with pytest.raises(PermissionDeniedError) as raised:
        client.project_settings("acme-shop")

    assert raised.value.operation == "project settings"


def test_a_project_the_user_cannot_reach_is_not_found(client, upstream):
    upstream.bodies["/app/project/other/get_info"] = {"error": {"data": {"name": "builtins.Exception"}}}

    with pytest.raises(NotFoundError, match="'other'"):
        client.project_settings("other")


def test_no_token_or_code_reaches_the_settings_or_the_log(client, upstream, caplog):
    with_secrets(upstream)

    with caplog.at_level(logging.DEBUG):
        read = client.project_settings("acme-shop")

    shown = repr(read) + json.dumps(dataclasses.asdict(read), default=str) + caplog.text
    assert not [secret for secret in (*SECRETS, LINK) if secret in shown]


@pytest.mark.parametrize(
    ("body", "key"),
    [(repo, "block_odoo_domain"), (result, "session_lifetime"), (repo, "ip_whitelist")],
)
def test_a_changed_shape_holds_no_token_or_code(client, upstream, session, body, key):
    with_secrets(upstream)
    body(upstream)[key] = None

    with pytest.raises(UpstreamChangedError) as raised:
        client.project_settings("acme-shop")

    error = raised.value
    assert error.__traceback__ is not None
    # From the client down: the test's own frame holds the session fixture.
    below = traceback.TracebackException(type(error), error, error.__traceback__.tb_next, capture_locals=True)
    shown = "".join(below.format())
    assert f"key = {key!r}" in shown
    assert not [secret for secret in (*SECRETS, LINK, session) if secret in shown]


def test_the_settings_are_read_without_their_token_codes_and_upsells(upstream, session):
    with_secrets(upstream)

    answer = projects.settings_answer(upstream.connect(Secret(session)), "acme-corp-odoo-addons-4217")
    read = answer.child("repository")
    assert [read.has(key) for key in ("ci_token", "subscription_code", "subscription_code_display")] == [False] * 3
    assert (answer.has("upsells"), answer.has("session_lifetime"), read.has("ip_whitelist")) == (False, True, True)
    assert PASSWORD not in answer.items("submodules")[0].text("name")


def test_the_name_odoo_sh_gives_cannot_change_the_address(client, upstream):
    upstream.bodies[INFO]["result"]["active_repo"]["technical_name"] = "../branch/1/rebuild?x="
    upstream.bodies["/app/project/../branch/1/rebuild?x=/get_settings"] = upstream.bodies[SETTINGS]

    client.project_settings("acme-shop")

    assert upstream.requests[1].url.raw_path == b"/app/project/%2E%2E%2Fbranch%2F1%2Frebuild%3Fx%3D/get_settings"


def test_the_settings_are_frozen_and_named_as_documented(client):
    read = client.project_settings("acme-shop")

    with pytest.raises(dataclasses.FrozenInstanceError):
        read.public = True  # pyright: ignore[reportAttributeAccessIssue]

    assert [field.name for field in dataclasses.fields(read)] == [
        "name",
        "odoo_domain_blocked",
        "session_lifetime",
        "public",
        "commit_statuses_suspended",
        "deploy_key_writable",
        "submodules",
        "hosting",
        "dedicated",
        "http_timeout_seconds",
        "cron_timeout_seconds",
        "module_install",
        "modules",
        "tests",
        "test_tags",
        "demo_data",
        "ai_agent",
        "ip_allow_list",
    ]
