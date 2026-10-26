import inspect
import json
import traceback
from ipaddress import IPv4Address, ip_address, ip_network

import httpx2
import pytest

from odouche import (
    AiAgent,
    BuildTests,
    Client,
    ModuleInstall,
    OutcomeUnknownError,
    PermissionDeniedError,
    ProjectSettingsChange,
    ReadOnlyError,
    Secret,
    SessionLifetime,
    SettingsConflictError,
    SettingsOutcome,
    UpstreamChangedError,
    UpstreamUnavailableError,
)
from odouche._upstream import project_settings


INFO = "/app/project/acme-shop/get_info"
GET = "/app/project/acme-corp-odoo-addons-4217/get_settings"
SET = "/app/project/acme-corp-odoo-addons-4217/set_settings"
FLAGS = {"demo_data"}
LIMITS = {"limit_real_time", "limit_real_time_cron"}
OFFICE = IPv4Address("198.51.100.42")
HOME = IPv4Address("203.0.113.10")
VPN = IPv4Address("192.0.2.7")
REFUSAL = {"jsonrpc": "2.0", "id": None, "error": {"code": 200, "data": {"name": "builtins.Exception"}}}


def answer(upstream):
    return upstream.bodies[GET]["result"]


def repo(upstream):
    return answer(upstream)["repository"]


def paths(upstream):
    return [request.url.path for request in upstream.requests]


def params(upstream):
    """Return the parameters of each change sent."""
    return [json.loads(request.content)["params"] for request in upstream.requests if request.url.path == SET]


def store(upstream, sent):
    """Store each field sent as the page's script is taken to show Odoo.sh does."""
    for key, value in sent.items():
        if key == "session_lifetime":
            answer(upstream)["session_lifetime"] = list(answer(upstream)["session_lifetime_map"])[int(value)]
        elif key == "public":
            repo(upstream)["private"] = value == "off"
        elif key == "ip_whitelist":
            # The capture shows an empty list as an empty text.
            repo(upstream)[key] = value
        elif key in LIMITS:
            answer(upstream)["dedicated_limits"][key]["value"] = float(value)
        else:
            repo(upstream)[key] = value == "on" if key in FLAGS else value or False


@pytest.fixture(autouse=True)
def saves(upstream):
    def save(request):
        store(upstream, json.loads(request.content)["params"])
        return httpx2.Response(200, json=upstream.load("set_project_settings.json"))

    upstream.bodies[SET] = save


@pytest.fixture
def listed(upstream):
    """Give the allow list two entries, as an admin may have written them."""
    repo(upstream)["ip_whitelist"] = f"{OFFICE}\n  {HOME}  "


@pytest.fixture
def dedicated(upstream):
    repo(upstream)["pays_dedicated"] = True


@pytest.mark.parametrize(
    ("change", "sent"),
    [
        (ProjectSettingsChange(session_lifetime=SessionLifetime.FOUR_HOURS), {"session_lifetime": "1"}),
        (ProjectSettingsChange(session_lifetime=SessionLifetime.EIGHT_DAYS), {"session_lifetime": "6"}),
        (ProjectSettingsChange(public=True), {"public": "on"}),
        (ProjectSettingsChange(module_install=ModuleInstall.ALL), {"modules_auto": "all"}),
        (
            ProjectSettingsChange(module_install=ModuleInstall.LISTED, modules=("sale", "purchase")),
            {"modules_auto": "none", "modules": "sale,purchase"},
        ),
        (ProjectSettingsChange(tests=BuildTests.OFF), {"test_mode": "off"}),
        (
            ProjectSettingsChange(tests=BuildTests.TAGS, test_tags="/sale"),
            {"test_mode": "all", "test_tags": "/sale"},
        ),
        (ProjectSettingsChange(demo_data=False), {"demo_data": "off"}),
        (ProjectSettingsChange(ai_agent=AiAgent.OPENCODE), {"ai_agent": "opencode"}),
    ],
    ids=lambda value: ",".join(value.given()) if isinstance(value, ProjectSettingsChange) else "",
)
def test_sends_only_the_settings_given_once_and_reads_them_back(client, upstream, change, sent):
    outcome = client.change_project_settings("acme-shop", change)

    assert paths(upstream) == [INFO, GET, SET, GET]
    assert params(upstream) == [sent]
    assert all(getattr(outcome.after, name) == value for name, value in change.given().items())
    assert outcome.moved == ()


def test_the_lifetime_is_the_index_of_its_key_in_the_order_odoo_sh_answers_them(client, upstream):
    lifetimes = answer(upstream)["session_lifetime_map"]
    answer(upstream)["session_lifetime_map"] = dict(reversed(lifetimes.items()))

    client.change_project_settings("acme-shop", ProjectSettingsChange(session_lifetime=SessionLifetime.FOUR_HOURS))

    assert params(upstream) == [{"session_lifetime": "5"}]


@pytest.mark.usefixtures("dedicated")
def test_a_timeout_is_sent_in_the_unit_of_its_page(client, upstream):
    outcome = client.change_project_settings(
        "acme-shop", ProjectSettingsChange(http_timeout_seconds=1800, cron_timeout_seconds=3600)
    )

    assert params(upstream) == [{"limit_real_time": "30", "limit_real_time_cron": "60"}]
    assert (outcome.after.http_timeout_seconds, outcome.after.cron_timeout_seconds) == (1800, 3600)


@pytest.mark.usefixtures("dedicated")
def test_one_timeout_is_sent_with_the_other_at_its_value_as_read(client, upstream):
    answer(upstream)["dedicated_limits"]["limit_real_time_cron"]["value"] = 2.5
    outcome = client.change_project_settings("acme-shop", ProjectSettingsChange(http_timeout_seconds=1800))

    assert params(upstream) == [{"limit_real_time": "30", "limit_real_time_cron": "2.5"}]
    assert (outcome.after.cron_timeout_seconds, outcome.moved) == (150, ())


@pytest.mark.parametrize(
    ("key", "name"),
    [
        ("deploy_key_writable", "deploy_key_writable"),
        ("block_odoo_domain", "odoo_domain_blocked"),
        ("ci_suspended", "commit_statuses_suspended"),
    ],
)
def test_a_setting_the_change_cannot_send_that_moves_is_reported(client, upstream, key, name):
    repo(upstream)[key] = True

    def resets(request):
        store(upstream, json.loads(request.content)["params"])
        repo(upstream)[key] = False

        return httpx2.Response(200, json=upstream.load("set_project_settings.json"))

    upstream.bodies[SET] = resets
    outcome = client.change_project_settings("acme-shop", ProjectSettingsChange(ai_agent=AiAgent.OPENCODE))

    assert outcome.moved == (name,)
    assert (getattr(outcome.before, name), getattr(outcome.after, name)) == (True, False)


@pytest.mark.usefixtures("dedicated")
@pytest.mark.parametrize("seconds", [90, 30, 9060])
def test_a_timeout_off_its_unit_or_bounds_is_refused_before_the_request(client, upstream, seconds):
    with pytest.raises(SettingsConflictError, match="multiple of 60 seconds from 60 to 9000"):
        client.change_project_settings("acme-shop", ProjectSettingsChange(http_timeout_seconds=seconds))

    assert SET not in paths(upstream)


@pytest.mark.usefixtures("dedicated")
def test_the_bounds_are_the_page_s_input_rounded_down_to_the_unit(client, upstream):
    answer(upstream)["dedicated_limits"]["limit_real_time"].update(min=90, max=7230)
    client.change_project_settings("acme-shop", ProjectSettingsChange(http_timeout_seconds=7200))

    with pytest.raises(SettingsConflictError, match="from 60 to 7200"):
        client.change_project_settings("acme-shop", ProjectSettingsChange(http_timeout_seconds=7260))

    assert params(upstream) == [{"limit_real_time": "120", "limit_real_time_cron": "15"}]


def test_a_timeout_is_refused_on_a_project_with_no_dedicated_server(client, upstream):
    with pytest.raises(SettingsConflictError, match="dedicated server only"):
        client.change_project_settings("acme-shop", ProjectSettingsChange(cron_timeout_seconds=1800))

    assert SET not in paths(upstream)


@pytest.mark.usefixtures("listed")
def test_an_address_is_added_after_the_lines_kept_as_written(client, upstream):
    outcome = client.change_project_settings("acme-shop", ProjectSettingsChange(allow_ips=(VPN,)))

    assert params(upstream) == [{"ip_whitelist": f"{OFFICE}\n  {HOME}  \n{VPN}"}]
    assert outcome.after.ip_allow_list == (OFFICE, HOME, VPN)
    assert outcome.moved == ()


@pytest.mark.usefixtures("listed")
def test_an_entry_is_removed_and_the_others_kept(client, upstream):
    outcome = client.change_project_settings("acme-shop", ProjectSettingsChange(disallow_ips=(OFFICE,)))

    assert params(upstream) == [{"ip_whitelist": f"  {HOME}  "}]
    assert outcome.after.ip_allow_list == (HOME,)


def test_a_network_is_removed_by_the_entry_the_read_gives(client, upstream):
    repo(upstream)["ip_whitelist"] = f"203.0.113.7/24\n\n{OFFICE}"

    client.change_project_settings("acme-shop", ProjectSettingsChange(disallow_ips=(ip_network("203.0.113.0/24"),)))

    assert params(upstream) == [{"ip_whitelist": str(OFFICE)}]


@pytest.mark.usefixtures("listed")
def test_adding_and_removing_go_in_one_request_with_the_other_settings(client, upstream):
    client.change_project_settings(
        "acme-shop",
        ProjectSettingsChange(ai_agent=AiAgent.OPENCODE, public=True, allow_ips=(VPN,), disallow_ips=(HOME,)),
    )

    assert params(upstream) == [{"ai_agent": "opencode", "public": "on", "ip_whitelist": f"{OFFICE}\n{VPN}"}]


@pytest.mark.usefixtures("listed")
def test_an_address_already_allowed_and_an_entry_not_listed_are_left_out(client, upstream):
    outcome = client.change_project_settings(
        "acme-shop", ProjectSettingsChange(allow_ips=(OFFICE,), disallow_ips=(VPN,), demo_data=True)
    )

    assert outcome == SettingsOutcome(outcome.before, outcome.before, ())
    assert paths(upstream) == [INFO, GET]


@pytest.mark.usefixtures("listed")
def test_an_allow_list_over_ten_entries_is_refused(client, upstream):
    added = tuple(IPv4Address(f"192.0.2.{last}") for last in range(1, 10))

    with pytest.raises(SettingsConflictError, match="10 entries at most"):
        client.change_project_settings("acme-shop", ProjectSettingsChange(allow_ips=added))

    client.change_project_settings("acme-shop", ProjectSettingsChange(allow_ips=added, disallow_ips=(HOME,)))

    assert len(params(upstream)) == 1


def test_removing_from_a_list_over_ten_is_never_refused(client, upstream):
    repo(upstream)["ip_whitelist"] = "\n".join(f"192.0.2.{last}" for last in range(1, 13))

    outcome = client.change_project_settings(
        "acme-shop", ProjectSettingsChange(disallow_ips=(IPv4Address("192.0.2.1"),))
    )

    assert len(outcome.after.ip_allow_list) == 11


def test_the_list_emptied_is_sent_empty(client, upstream):
    repo(upstream)["ip_whitelist"] = str(OFFICE)

    assert (
        client.change_project_settings("acme-shop", ProjectSettingsChange(disallow_ips=(OFFICE,))).after.ip_allow_list
        == ()
    )
    assert params(upstream) == [{"ip_whitelist": ""}]


def test_a_change_with_nothing_new_sends_nothing_and_returns_the_settings(client, upstream):
    current = client.project_settings("acme-shop")
    upstream.requests.clear()

    outcome = client.change_project_settings(
        "acme-shop", ProjectSettingsChange(session_lifetime=SessionLifetime.AUTO, public=False, test_tags="")
    )

    assert outcome == SettingsOutcome(current, current, ())
    assert paths(upstream) == [INFO, GET]


def test_takes_a_project_or_its_name(client, upstream):
    project = client.projects()[0]

    client.change_project_settings(project, ProjectSettingsChange(public=True))

    assert paths(upstream).count(SET) == 1


@pytest.mark.parametrize(
    ("current", "change", "message"),
    [
        ({}, ProjectSettingsChange(modules=("sale",)), "`modules` applies only"),
        ({}, ProjectSettingsChange(module_install=ModuleInstall.LISTED), "names none"),
        ({"modules_auto": "all"}, ProjectSettingsChange(tests=BuildTests.OFF), "`module_install` is `all`"),
        ({}, ProjectSettingsChange(test_tags="/sale"), "`test_tags` applies only"),
    ],
)
def test_a_default_the_page_hides_is_refused_before_the_request(client, upstream, current, change, message):
    repo(upstream).update(current)

    with pytest.raises(SettingsConflictError, match=message):
        client.change_project_settings("acme-shop", change)

    assert SET not in paths(upstream)


@pytest.mark.parametrize("access", ["tester", "developer"])
def test_below_admin_it_is_denied_before_any_settings_request(client, upstream, access):
    upstream.bodies[INFO]["result"]["user"]["access"] = access

    with pytest.raises(PermissionDeniedError, match="admins") as raised:
        client.change_project_settings("acme-shop", ProjectSettingsChange(public=True))

    assert raised.value.operation == "project settings change"
    assert paths(upstream) == [INFO]


def test_a_read_only_client_sends_nothing_not_even_a_read(upstream, session):
    client = Client(Secret(session), read_only=True)

    with pytest.raises(ReadOnlyError) as raised:
        client.change_project_settings("acme-shop", ProjectSettingsChange(public=True))

    assert raised.value.operation == "change_settings"
    assert upstream.requests == []


def test_the_change_is_marked_as_state_changing():
    assert inspect.unwrap(project_settings.change_settings) is not project_settings.change_settings


@pytest.mark.parametrize("failure", [502, 500, httpx2.ReadTimeout, httpx2.RemoteProtocolError])
def test_a_change_that_is_not_confirmed_is_sent_once_and_its_outcome_is_unknown(client, upstream, failure):
    upstream.failures[SET] = failure

    with pytest.raises(OutcomeUnknownError, match="Look before trying again") as raised:
        client.change_project_settings("acme-shop", ProjectSettingsChange(public=True))

    assert raised.value.operation == "project settings change"
    assert paths(upstream) == [INFO, GET, SET]


def test_a_change_odoo_sh_refuses_without_a_reason_is_unknown(client, upstream):
    upstream.bodies[SET] = REFUSAL

    with pytest.raises(OutcomeUnknownError):
        client.change_project_settings("acme-shop", ProjectSettingsChange(public=True))

    assert paths(upstream) == [INFO, GET, SET]


def test_a_change_that_did_not_leave_is_not_repeated(client, upstream):
    upstream.failures[SET] = httpx2.ConnectError

    with pytest.raises(UpstreamUnavailableError):
        client.change_project_settings("acme-shop", ProjectSettingsChange(public=True))

    assert paths(upstream).count(SET) == 1


@pytest.mark.usefixtures("listed")
def test_a_list_read_back_without_the_address_is_unknown(client, upstream):
    upstream.bodies[SET] = upstream.load("set_project_settings.json")

    with pytest.raises(OutcomeUnknownError, match=r"show ip_allow_list not as sent\. Look") as raised:
        client.change_project_settings("acme-shop", ProjectSettingsChange(allow_ips=(VPN,)))

    assert str(raised.value).startswith("The change of project acme-shop's settings was sent")
    assert raised.value.__context__ is None


@pytest.mark.usefixtures("listed")
def test_a_list_read_back_in_another_order_is_as_sent(client, upstream):
    def sorts(request):
        sent = json.loads(request.content)["params"]["ip_whitelist"]
        repo(upstream)["ip_whitelist"] = "\n".join(sorted(line.strip() for line in sent.splitlines()))

        return httpx2.Response(200, json=upstream.load("set_project_settings.json"))

    upstream.bodies[SET] = sorts

    assert client.change_project_settings("acme-shop", ProjectSettingsChange(allow_ips=(VPN,))).after.ip_allow_list == (
        VPN,
        OFFICE,
        HOME,
    )


@pytest.mark.parametrize("read_back", [503, 403, {"result": []}, "unauthenticated.json"])
def test_settings_that_cannot_be_read_back_are_unknown(client, upstream, read_back):
    def save(_):
        if isinstance(read_back, int):
            upstream.failures[GET] = read_back
        else:
            upstream.bodies[GET] = upstream.load(read_back) if isinstance(read_back, str) else read_back

        return httpx2.Response(200, json=upstream.load("set_project_settings.json"))

    upstream.bodies[SET] = save

    with pytest.raises(OutcomeUnknownError, match="could not be read back") as raised:
        client.change_project_settings("acme-shop", ProjectSettingsChange(public=True))

    assert raised.value.__context__ is None
    assert paths(upstream).count(SET) == 1


def test_a_setting_odoo_sh_moves_along_is_reported_and_the_change_succeeds(client, upstream):
    def tests_off(request):
        store(upstream, json.loads(request.content)["params"])
        repo(upstream)["test_mode"] = "off"

        return httpx2.Response(200, json=upstream.load("set_project_settings.json"))

    upstream.bodies[SET] = tests_off
    outcome = client.change_project_settings("acme-shop", ProjectSettingsChange(module_install=ModuleInstall.ALL))

    assert outcome.moved == ("tests",)
    assert (outcome.before.tests, outcome.after.tests) == (BuildTests.MODULES, BuildTests.OFF)


@pytest.mark.parametrize(
    "lifetimes",
    [
        {"auto": {}, "4-hours": {}},
        {"auto": {}, "4-hours": {}, "8-hours": {}, "1-day": {}, "2-days": {}, "4-days": {}, "16-days": {}},
    ],
)
def test_a_lifetime_map_of_other_keys_is_a_changed_shape_before_the_request(client, upstream, lifetimes):
    answer(upstream)["session_lifetime_map"] = lifetimes

    with pytest.raises(UpstreamChangedError) as raised:
        client.change_project_settings("acme-shop", ProjectSettingsChange(public=True))

    assert raised.value.field == "result.session_lifetime_map"
    assert SET not in paths(upstream)


def test_the_lifetime_map_is_not_needed_to_read_the_settings(client, upstream):
    answer(upstream)["session_lifetime_map"] = {}

    assert client.project_settings("acme-shop").session_lifetime is SessionLifetime.AUTO


@pytest.mark.parametrize(
    ("limit", "field"), [({"unit_conversion": 0}, "unit_conversion"), ({"min": 600, "max": 60}, "max")]
)
def test_limits_odoo_sh_did_not_answer_as_seen_are_a_changed_shape(client, upstream, limit, field):
    answer(upstream)["dedicated_limits"]["limit_real_time_cron"].update(limit)

    with pytest.raises(UpstreamChangedError) as raised:
        client.change_project_settings("acme-shop", ProjectSettingsChange(public=True))

    assert raised.value.field == f"result.dedicated_limits.limit_real_time_cron.{field}"


def test_a_check_narrows_as_the_change_does_and_asks_nothing(upstream, session, listed):
    del listed
    client = Client(Secret(session), read_only=True)
    current = client.project_settings("acme-shop")
    upstream.requests.clear()

    narrowed = client.check_project_settings_change(
        current, ProjectSettingsChange(public=True, ai_agent=AiAgent.CLAUDE, allow_ips=(OFFICE, VPN))
    )
    unchanged = client.check_project_settings_change(current, ProjectSettingsChange(ai_agent=AiAgent.CLAUDE))

    with pytest.raises(SettingsConflictError, match="dedicated"):
        client.check_project_settings_change(current, ProjectSettingsChange(http_timeout_seconds=600))

    assert narrowed == ProjectSettingsChange(public=True, allow_ips=(VPN,))
    assert unchanged is None
    assert upstream.requests == []


def test_an_unknown_outcome_shows_nothing_of_the_session(client, upstream, session):
    upstream.failures[SET] = httpx2.ReadTimeout

    with pytest.raises(OutcomeUnknownError) as raised:
        client.change_project_settings("acme-shop", ProjectSettingsChange(public=True))

    assert raised.value.__context__ is None
    assert session not in "".join(traceback.format_exception(raised.value))


def test_a_change_names_at_least_one_setting():
    with pytest.raises(ValueError, match="at least one"):
        ProjectSettingsChange()


@pytest.mark.parametrize(
    ("given", "message"),
    [
        ({"http_timeout_seconds": 0}, "over 0"),
        ({"cron_timeout_seconds": -60}, "over 0"),
        ({"allow_ips": ()}, "at least one entry"),
        ({"disallow_ips": ()}, "at least one entry"),
        ({"allow_ips": (VPN, VPN)}, "twice"),
        ({"disallow_ips": (VPN, VPN)}, "twice"),
        ({"allow_ips": (VPN,), "disallow_ips": (VPN,)}, "both"),
        ({"allow_ips": (IPv4Address(0),)}, "not an address Odoo.sh sees"),
        ({"allow_ips": (IPv4Address("127.0.0.1"),)}, "not an address Odoo.sh sees"),
        ({"allow_ips": (IPv4Address("224.0.0.1"),)}, "not an address Odoo.sh sees"),
        ({"allow_ips": (IPv4Address("169.254.1.1"),)}, "not an address Odoo.sh sees"),
        ({"allow_ips": (IPv4Address("240.0.0.1"),)}, "not an address Odoo.sh sees"),
        ({"modules": ("sale,purchase",)}, "not a module name"),
        ({"test_tags": "/sale $(id)"}, "Test tags hold only"),
    ],
    ids=repr,
)
def test_a_value_that_cannot_be_sent_is_refused(given, message):
    with pytest.raises(ValueError, match=message):
        ProjectSettingsChange(**given)


@pytest.mark.parametrize(
    "given",
    [
        {"session_lifetime": "4h"},
        {"public": 1},
        {"http_timeout_seconds": True},
        {"http_timeout_seconds": 600.0},
        {"allow_ips": ["192.0.2.7"]},
        {"allow_ips": ("192.0.2.7",)},
        {"allow_ips": (ip_address("2001:db8::1"),)},
        {"allow_ips": (ip_network("192.0.2.0/24"),)},
        {"disallow_ips": ("192.0.2.7",)},
    ],
    ids=repr,
)
def test_a_value_of_another_type_is_refused(given):
    with pytest.raises(TypeError, match=next(iter(given))):
        ProjectSettingsChange(**given)


@pytest.mark.parametrize("address", ["10.0.0.1", "192.168.1.1", "192.0.2.7", "198.51.100.200"])
def test_private_and_documentation_addresses_are_taken(address):
    assert ProjectSettingsChange(allow_ips=(IPv4Address(address),)).allow_ips == (IPv4Address(address),)


def test_a_removal_takes_any_entry_the_list_reads():
    entries = (ip_address("2001:db8::1"), ip_network("203.0.113.0/24"), ip_network("2001:db8::/32"), VPN)

    assert ProjectSettingsChange(disallow_ips=entries).disallow_ips == entries


def test_access_names_the_fields_given_that_change_who_reaches_the_project():
    change = ProjectSettingsChange(
        ai_agent=AiAgent.CLAUDE, disallow_ips=(VPN,), public=False, session_lifetime=SessionLifetime.AUTO
    )

    assert change.access() == ("session_lifetime", "public", "disallow_ips")
    assert ProjectSettingsChange(demo_data=True).access() == ()
    assert {"session_lifetime", "public", "allow_ips", "disallow_ips"} == ProjectSettingsChange.ACCESS
