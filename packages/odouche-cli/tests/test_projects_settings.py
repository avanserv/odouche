import json
import re
from dataclasses import fields, replace
from ipaddress import ip_address, ip_network
from typing import Self

import click
import pytest
from typer.testing import CliRunner, Result

import odouche
from odouche import AiAgent, BuildTests, ModuleInstall, ProjectHosting, ProjectSettings, SessionLifetime, Submodule
from odouche_cli.app import app


PUBLIC_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEFjbWVJbnZlbnRlZEtleUZvclRlc3RzT25seTAwMDA= odoo.sh"
FINGERPRINT = "SHA256:aW52ZW50ZWQgZmluZ2VycHJpbnQgZm9yIHRlc3Rz"
THEME = Submodule(71001, "git@github.com:acme-corp/acme-theme.git", FINGERPRINT, PUBLIC_KEY)
SETTINGS = ProjectSettings(
    name="acme",
    odoo_domain_blocked=False,
    session_lifetime=SessionLifetime.FOUR_DAYS,
    public=True,
    commit_statuses_suspended=False,
    deploy_key_writable=True,
    submodules=(THEME,),
    hosting=ProjectHosting(
        storage_used_bytes=438272000,
        storage_quota_bytes=1073741824,
        workers=2,
        staging_branches=1,
    ),
    dedicated=False,
    http_timeout_seconds=900,
    cron_timeout_seconds=90,
    module_install=ModuleInstall.LISTED,
    modules=("sale", "stock"),
    tests=BuildTests.TAGS,
    test_tags="/sale:TestSale",
    demo_data=True,
    ai_agent=AiAgent.OPENCODE,
    ip_allow_list=(ip_address("198.51.100.42"), ip_network("2001:db8::/32")),
)

runner = CliRunner()


class StubClient:
    """Stands in for `odouche.Client`: answers with a project's settings, or raises, and records the calls."""

    found: ProjectSettings = SETTINGS
    error: odouche.OdoucheError | None = None
    modes: list[bool]
    calls: list[str]

    def __init__(self, *, read_only: bool = False) -> None:
        self.modes.append(read_only)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def projects(self) -> list[odouche.Project]:
        self.calls.append("projects")
        return []

    def project_settings(self, project: str) -> ProjectSettings:
        self.calls.append(f"project_settings {project}")

        if self.error is not None:
            raise self.error

        return self.found


@pytest.fixture(autouse=True)
def client(monkeypatch: pytest.MonkeyPatch) -> type[StubClient]:
    class Client(StubClient):
        modes: list[bool] = []
        calls: list[str] = []

    monkeypatch.setattr(odouche, "Client", Client)

    return Client


def run(*args: str) -> Result:
    return runner.invoke(app, ["projects", "settings", "show", "--project", "acme", *args])


def rows(result: Result) -> dict[str, str]:
    """Read each line as a label and its value, which two spaces or more separate."""
    return dict(re.split(r"\s{2,}", line.strip(), maxsplit=1) for line in result.stdout.splitlines())  # pyright: ignore[reportReturnType]


def test_shows_each_setting_on_its_own_line(client: type[StubClient]):
    result = run()

    assert result.exit_code == 0
    assert client.calls == ["project_settings acme"]
    assert client.modes == [True]
    assert rows(result) == {
        "Name": "acme",
        "odoo.com domain blocked": "no",
        "Session lifetime": "4d",
        "Public access": "yes",
        "Commit statuses suspended": "no",
        "Writable deploy key": "yes",
        "Submodules": f"git@github.com:acme-corp/acme-theme.git ({FINGERPRINT})",
        "Storage": "418.0 MiB of 1.0 GiB, 41%",
        "Workers": "2",
        "Staging branches": "1",
        "Dedicated": "no",
        "HTTP timeout": "15 minutes",
        "Scheduled actions timeout": "1.5 minutes",
        "Dev install": "listed",
        "Dev modules": "sale, stock",
        "Dev tests": "tags",
        "Dev test tags": "/sale:TestSale",
        "Dev demo data": "yes",
        "Dev AI agent": "opencode",
        "IP allow list": "198.51.100.42, 2001:db8::/32",
    }
    assert PUBLIC_KEY not in result.stdout


def test_what_is_empty_is_none_and_one_minute_is_singular(client: type[StubClient]):
    client.found = replace(
        SETTINGS, submodules=(), modules=(), test_tags=None, ip_allow_list=(), cron_timeout_seconds=60
    )

    shown = rows(run())

    assert [shown[label] for label in ("Submodules", "Dev modules", "Dev test tags", "IP allow list")] == ["none"] * 4
    assert shown["Scheduled actions timeout"] == "1 minute"


def test_as_json_is_the_model_whole_with_addresses_as_text():
    result = runner.invoke(app, ["--format", "json", "projects", "settings", "show", "--project", "acme"])

    assert result.exit_code == 0
    printed = json.loads(result.stdout)
    assert list(printed) == [field.name for field in fields(ProjectSettings)]
    assert printed["ip_allow_list"] == ["198.51.100.42", "2001:db8::/32"]
    assert printed["submodules"] == [
        {"id": 71001, "url": THEME.url, "fingerprint": FINGERPRINT, "public_key": PUBLIC_KEY}
    ]
    assert printed["hosting"]["workers"] == 2
    assert (printed["session_lifetime"], printed["http_timeout_seconds"]) == ("4d", 900)


def test_a_submodule_without_a_url_shows_none_for_it(client: type[StubClient]):
    client.found = replace(SETTINGS, submodules=(replace(THEME, url=""),))

    assert rows(run())["Submodules"] == f"none ({FINGERPRINT})"


def test_a_submodule_s_url_is_printed_without_its_control_characters(client: type[StubClient]):
    client.found = replace(
        SETTINGS, submodules=(replace(THEME, url="git@github.com:acme\x1b]8;;x\x07/\u202etheme\x1b[2J"),)
    )

    result = run()

    assert rows(result)["Submodules"] == f"git@github.com:acme/theme ({FINGERPRINT})"

    for control in ("\x1b", "\u202e", "]8;;", "[2J"):
        assert control not in result.stdout


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (odouche.PermissionDeniedError("Odoo.sh shows a project's settings to its admins only."), 5),
        (odouche.NotFoundError("The session's user can reach no project named 'acme'."), 4),
        (odouche.UpstreamChangedError("project settings", "result.repository.ip_whitelist"), 6),
    ],
)
def test_an_error_exits_with_its_code_and_message(client: type[StubClient], error: odouche.OdoucheError, code: int):
    client.error = error
    result = run()

    assert result.exit_code == code
    assert str(error) in " ".join(click.unstyle(result.stderr).split())
    assert result.stdout == ""


def test_help_names_the_group_and_the_example():
    group = runner.invoke(app, ["projects", "settings", "--help"])
    show = runner.invoke(app, ["projects", "settings", "show", "--help"])

    assert "show" in click.unstyle(group.output)
    assert "Example: osh projects settings show --project acme-shop" in click.unstyle(show.output)
