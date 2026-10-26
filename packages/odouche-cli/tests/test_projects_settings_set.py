import ipaddress
import json
import re
from dataclasses import fields, replace
from typing import Self

import click
import pytest
from typer.testing import CliRunner, Result

import odouche
from odouche import AiAgent, BuildTests, ModuleInstall, ProjectSettings, ProjectSettingsChange, SessionLifetime
from odouche_cli import _terminal
from odouche_cli.app import app


ACME = odouche.Project(id=1, name="acme", repository="acme/odoo", url="https://www.odoo.sh/project/acme")
OFFICE = ipaddress.IPv4Address("198.51.100.42")
HOME = ipaddress.IPv4Address("203.0.113.10")
VPN = ipaddress.IPv4Address("192.0.2.7")
OWN = ProjectSettings(
    name="acme",
    odoo_domain_blocked=False,
    session_lifetime=SessionLifetime.AUTO,
    public=False,
    commit_statuses_suspended=False,
    deploy_key_writable=False,
    submodules=(),
    hosting=odouche.ProjectHosting(0, 0, 1, 1),
    dedicated=False,
    http_timeout_seconds=900,
    cron_timeout_seconds=900,
    module_install=ModuleInstall.REPOSITORY,
    modules=(),
    tests=BuildTests.MODULES,
    test_tags=None,
    demo_data=True,
    ai_agent=AiAgent.CLAUDE,
    ip_allow_list=(OFFICE, HOME),
)
SET = ("projects", "settings", "set", "--project", "acme")
LOST = odouche.OutcomeUnknownError(
    "The change of project acme's settings was sent, and the settings could not be read back. Look before trying "
    "again.",
    operation="project settings change",
)

runner = CliRunner()


class StubClient:
    """Stands in for `odouche.Client`: changes settings as the library does, and records the calls."""

    found: ProjectSettings = OWN
    failure: Exception | None = None
    modes: list[bool]
    calls: list[str]
    sent: list[ProjectSettingsChange]

    def __init__(self, *, read_only: bool = False) -> None:
        self.modes.append(read_only)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def projects(self) -> list[odouche.Project]:
        return [ACME]

    def project_settings(self, project: str) -> ProjectSettings:
        self.calls.append(f"settings {project}")
        return self.found

    # The library's own, which asks nothing.
    check_project_settings_change = odouche.Client.check_project_settings_change

    def change_project_settings(
        self, project: str, change: ProjectSettingsChange
    ) -> odouche.SettingsOutcome[ProjectSettings]:
        self.calls.append(f"change {project}")
        self.sent.append(change)

        if self.failure is not None:
            raise self.failure

        given = {name: value for name, value in change.given().items() if name not in {"allow_ips", "disallow_ips"}}
        removed = change.disallow_ips or ()
        listed = (*(entry for entry in self.found.ip_allow_list if entry not in removed), *(change.allow_ips or ()))
        after = replace(self.found, **given, ip_allow_list=listed)  # pyright: ignore[reportArgumentType]
        moved: tuple[str, ...] = ()

        # As the page says Odoo.sh does: installing every module turns the test suite off.
        if after.module_install is ModuleInstall.ALL and after.tests is not BuildTests.OFF:
            after, moved = replace(after, tests=BuildTests.OFF), ("tests",)

        return odouche.SettingsOutcome(self.found, after, moved)


@pytest.fixture(autouse=True)
def read_only_clients() -> None:
    """Replace the shared check: the command of this file is one that writes."""


@pytest.fixture(autouse=True)
def client(monkeypatch: pytest.MonkeyPatch) -> type[StubClient]:
    class Client(StubClient):
        modes: list[bool] = []
        calls: list[str] = []
        sent: list[ProjectSettingsChange] = []

    monkeypatch.setattr(odouche, "Client", Client)
    monkeypatch.setattr(_terminal, "stdin_is_terminal", lambda: True)
    monkeypatch.setattr(_terminal, "stderr_is_terminal", lambda: True)

    return Client


def run(*args: str, stdin: str | None = None) -> Result:
    return runner.invoke(app, list(args), input=stdin)


def changes(client: type[StubClient]) -> list[str]:
    return [call for call in client.calls if call.startswith("change")]


def pairs(result: Result) -> dict[str, str]:
    found = [re.split(r"\s{2,}", line.strip(), maxsplit=1) for line in result.stdout.splitlines()]
    return {row[0]: row[1] if len(row) > 1 else "" for row in found}


def said(result: Result) -> str:
    """Return stderr on one line, without the box a usage error is drawn in."""
    return " ".join(click.unstyle(result.stderr).replace("│", "").split())


def test_a_yes_sends_the_change_on_a_client_that_writes_and_prints_the_settings_after(client: type[StubClient]):
    result = run(*SET, "ai_agent=opencode", stdin="y\n")

    assert result.exit_code == 0
    assert client.calls == ["settings acme", "change acme"]
    assert client.sent == [ProjectSettingsChange(ai_agent=AiAgent.OPENCODE)]
    assert client.modes == [False]
    assert result.stderr.splitlines() == [
        "Project: acme",
        "ai_agent: claude → opencode",
        "Change these settings of this project? [y/N]: The settings were changed.",
    ]
    assert pairs(result)["Dev AI agent"] == "opencode"


@pytest.mark.parametrize("answer", ["n\n", "\n", "no\n", ""], ids=repr)
def test_anything_but_a_yes_sends_nothing_and_exits_1(client: type[StubClient], answer: str):
    result = run(*SET, "--add-ip", str(VPN), stdin=answer)

    assert result.exit_code == 1
    assert changes(client) == []
    assert result.stdout == ""
    assert result.stderr.endswith("Change these settings of this project, including access? [y/N]: Nothing was sent.\n")


def test_yes_sends_without_asking(client: type[StubClient]):
    result = run(*SET, "--yes", "public=yes")

    assert result.exit_code == 0
    assert changes(client) == ["change acme"]
    assert "[y/N]" not in result.stderr


@pytest.mark.parametrize("name", ["stdin_is_terminal", "stderr_is_terminal"])
def test_a_run_nobody_attends_is_refused_before_a_client_is_opened(
    client: type[StubClient], monkeypatch: pytest.MonkeyPatch, name: str
):
    monkeypatch.setattr(_terminal, name, lambda: False)

    result = run(*SET, "--add-ip", str(VPN), stdin="y\n")

    assert result.exit_code == 2
    assert client.modes == []
    assert "Stdin or stderr is not a terminal" in said(result)


def test_an_address_is_added_after_those_listed_and_access_is_named(client: type[StubClient]):
    result = run(*SET, "--add-ip", str(VPN), stdin="y\n")

    assert result.exit_code == 0
    assert client.sent == [ProjectSettingsChange(allow_ips=(VPN,))]
    assert result.stderr.splitlines()[:3] == [
        "Project: acme",
        f"ip_allow_list: {OFFICE}, {HOME} → {OFFICE}, {HOME}, {VPN}",
        "This changes who can reach the project: ip_allow_list.",
    ]
    assert "including access? [y/N]" in result.stderr
    assert pairs(result)["IP allow list"] == f"{OFFICE}, {HOME}, {VPN}"


def test_a_removed_entry_is_said_to_need_the_one_hour_rule(client: type[StubClient]):
    result = run(*SET, "--remove-ip", str(HOME), stdin="y\n")

    assert result.exit_code == 0
    assert client.sent == [ProjectSettingsChange(disallow_ips=(HOME,))]
    assert result.stderr.splitlines()[1:4] == [
        f"ip_allow_list: {OFFICE}, {HOME} → {OFFICE}",
        "This changes who can reach the project: ip_allow_list.",
        (
            f"SSH to production and staging from {HOME} then needs the one-hour rule `osh ssh` asks for. "
            f"PostgreSQL on a dedicated server is then closed to {HOME}."
        ),
    ]


def test_a_network_is_removed_as_show_lists_it(client: type[StubClient]):
    network = ipaddress.ip_network("203.0.113.0/24")
    client.found = replace(OWN, ip_allow_list=(OFFICE, network))
    result = run(*SET, "--yes", "--remove-ip", "203.0.113.0/24")

    assert result.exit_code == 0
    assert client.sent == [ProjectSettingsChange(disallow_ips=(network,))]


def test_an_emptied_list_is_said_before_the_question(client: type[StubClient]):
    result = run(*SET, "--remove-ip", str(OFFICE), "--remove-ip", str(HOME), stdin="n\n")

    assert result.exit_code == 1
    assert "The allow list will be empty: no address keeps a permanent rule." in result.stderr.splitlines()


def test_public_access_and_the_lifetime_are_named_as_access(client: type[StubClient]):
    result = run(*SET, "public=yes", "session_lifetime=4h", "demo_data=no", stdin="y\n")

    assert result.exit_code == 0
    assert result.stderr.splitlines()[1:5] == [
        "session_lifetime: auto → 4h",
        "public: no → yes",
        "demo_data: yes → no",
        "This changes who can reach the project: session_lifetime, public.",
    ]
    assert "including access? [y/N]" in result.stderr


def test_an_address_already_allowed_and_an_entry_not_listed_send_nothing(client: type[StubClient]):
    result = run(*SET, "--add-ip", str(OFFICE), "--remove-ip", str(VPN), "ai_agent=claude")

    assert result.exit_code == 0
    assert changes(client) == []
    assert "[y/N]" not in result.stderr
    assert result.stderr.splitlines()[1:] == [
        "ai_agent is already claude.",
        f"{OFFICE} is already allowed.",
        f"{VPN} is not in the list.",
        "Nothing was sent: every setting already has that value.",
    ]
    assert pairs(result)["IP allow list"] == f"{OFFICE}, {HOME}"


def test_a_mix_sends_what_differs_and_names_access_once(client: type[StubClient]):
    result = run(*SET, "--add-ip", str(VPN), "--add-ip", str(OFFICE), "--remove-ip", str(HOME), "--yes")

    assert result.exit_code == 0
    assert client.sent == [ProjectSettingsChange(allow_ips=(VPN,), disallow_ips=(HOME,))]
    assert "This changes who can reach the project: ip_allow_list." in result.stderr.splitlines()


@pytest.mark.parametrize(
    ("given", "hint", "message"),
    [
        ((), "NAME=VALUE", "at least one setting"),
        (("ip_allow_list=198.51.100.1",), "NAME=VALUE", "--add-ip or --remove-ip"),
        (("name=shop",), "NAME=VALUE", "session_lifetime, public"),
        (("public",), "NAME=VALUE", "is not NAME=VALUE"),
        (("public=maybe",), "NAME=VALUE", "yes, no"),
        (("session_lifetime=3d",), "NAME=VALUE", "auto, 4h, 8h"),
        (("http_timeout_seconds=15m",), "NAME=VALUE", "a whole number of seconds"),
        (("http_timeout_seconds=0",), "NAME=VALUE", "over 0"),
        (("modules=sale;purchase",), "NAME=VALUE", "not a module name"),
        (("--add-ip", "office"), "--add-ip", "is not an IP address"),
        (("--add-ip", "2001:db8::1"), "--add-ip", "is not an IPv4 address"),
        (("--add-ip", "198.51.100.0/24"), "--add-ip", "is not an IP address"),
        (("--add-ip", "127.0.0.1"), "--add-ip", "not an address Odoo.sh sees"),
        (("--add-ip", "0.0.0.0"), "--add-ip", "not an address Odoo.sh sees"),  # noqa: S104
        (("--add-ip", str(VPN), "--add-ip", str(VPN)), "--add-ip", "twice"),
        (("--remove-ip", "office"), "--remove-ip", "not an address or a network"),
        (("--add-ip", str(VPN), "--remove-ip", str(VPN)), "--add-ip, --remove-ip", "both"),
        (
            ("http_timeout_seconds=0", "--add-ip", str(VPN), "--remove-ip", str(OFFICE)),
            "Invalid value for NAME=VALUE",
            "over 0",
        ),
    ],
)
def test_what_cannot_be_sent_is_a_usage_error_before_any_client(
    client: type[StubClient], given: tuple[str, ...], hint: str, message: str
):
    result = run(*SET, "--yes", *given)

    assert result.exit_code == 2
    assert client.modes == []
    assert hint in said(result)
    assert message in said(result)


def test_a_timeout_on_a_project_with_no_dedicated_server_is_a_usage_error_before_the_question(
    client: type[StubClient],
):
    result = run(*SET, "http_timeout_seconds=1800", stdin="y\n")

    assert result.exit_code == 2
    assert changes(client) == []
    assert "[y/N]" not in result.stderr
    assert "dedicated server only" in said(result)


def test_a_timeout_on_a_dedicated_server_is_sent_in_seconds(client: type[StubClient]):
    client.found = replace(OWN, dedicated=True)
    result = run(*SET, "--yes", "http_timeout_seconds=1800")

    assert result.exit_code == 0
    assert client.sent == [ProjectSettingsChange(http_timeout_seconds=1800)]
    assert result.stderr.splitlines()[1] == "http_timeout_seconds: 900 → 1800"
    assert pairs(result)["HTTP timeout"] == "30 minutes"


def test_a_setting_odoo_sh_moves_along_is_said_and_the_change_succeeds(client: type[StubClient]):
    result = run(*SET, "--yes", "module_install=all")

    assert result.exit_code == 0
    assert result.stderr.splitlines()[-2:] == [
        "The settings were changed.",
        "tests: modules → off, also changed by Odoo.sh.",
    ]


def test_a_conflict_odoo_sh_was_not_asked_about_is_a_usage_error(client: type[StubClient]):
    client.failure = odouche.SettingsConflictError("`http_timeout_seconds` is a multiple of 60 seconds.")
    client.found = replace(OWN, dedicated=True)
    result = run(*SET, "--yes", "http_timeout_seconds=1830")

    assert result.exit_code == 2
    assert "multiple of 60 seconds" in said(result)


def test_a_user_who_is_not_an_admin_exits_5(client: type[StubClient]):
    client.failure = odouche.PermissionDeniedError("Odoo.sh lets only a project's admins change its settings.")
    result = run(*SET, "--yes", "public=yes")

    assert result.exit_code == 5
    assert "admins" in result.stderr


def test_an_unknown_outcome_exits_10_and_says_where_to_look(client: type[StubClient]):
    client.failure = LOST
    result = run(*SET, "--yes", "public=yes")

    assert result.exit_code == 10
    assert result.stdout == ""
    assert result.stderr.splitlines()[-2:] == [
        str(LOST),
        (
            "`osh projects settings show` shows whether the settings were changed. Sending the same change again "
            "does no harm."
        ),
    ]


def test_json_is_the_settings_after(client: type[StubClient]):
    result = run("--format", "json", *SET, "--yes", "--add-ip", str(VPN))
    shown = json.loads(result.stdout)
    assert list(shown) == [field.name for field in fields(ProjectSettings)]
    assert shown["ip_allow_list"] == [str(OFFICE), str(HOME), str(VPN)]


def test_help_opens_no_client_and_its_first_line_says_it_changes_state(client: type[StubClient]):
    result = run("projects", "settings", "set", "--help")

    assert result.exit_code == 0
    lines = [line.strip() for line in click.unstyle(result.output).splitlines() if line.strip()]
    assert lines[1].startswith("Change state on Odoo.sh:")
    assert client.modes == []
