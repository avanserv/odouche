import json
import re
from dataclasses import replace
from typing import Self

import click
import pytest
from typer.testing import CliRunner, Result

import odouche
from odouche import MemberRole, ProjectMember
from odouche_cli.app import app


def member(login: str, role: MemberRole, *, pending_login: bool = False, number: int = 1) -> ProjectMember:
    return ProjectMember(
        id=61000 + number,
        login=login,
        name=login,
        role=role,
        github_id=1000000 + number,
        pending_login=pending_login,
    )


# In the order Odoo.sh answers them, which is by none of the columns.
MEMBERS = (
    member("jane-doe", MemberRole.TESTER, number=2),
    member("build-bot1", MemberRole.DEVELOPER, pending_login=True, number=3),
    member("octo-dev", MemberRole.ADMIN, number=1),
    member("Ada-Dev", MemberRole.DEVELOPER, number=4),
)

runner = CliRunner()


class StubClient:
    """Stands in for `odouche.Client`: lists the members, or raises."""

    found: tuple[ProjectMember, ...] = MEMBERS
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

    def members(self, project: str) -> list[ProjectMember]:
        self.calls.append(f"members {project}")

        if self.error is not None:
            raise self.error

        return list(self.found)


@pytest.fixture(autouse=True)
def client(monkeypatch: pytest.MonkeyPatch) -> type[StubClient]:
    class Client(StubClient):
        modes: list[bool] = []
        calls: list[str] = []

    monkeypatch.setattr(odouche, "Client", Client)

    return Client


def run(*args: str) -> Result:
    return runner.invoke(app, [*args, "projects", "members", "list", "--project", "acme"])


def rows(result: Result) -> list[list[str]]:
    """Split each line into its cells, which two spaces or more separate."""
    return [re.split(r"\s{2,}", line.strip()) for line in result.stdout.splitlines()]


def test_lists_the_members_highest_role_first_then_by_login(client: type[StubClient]):
    result = run()

    assert result.exit_code == 0
    assert client.calls == ["members acme"]
    assert client.modes == [True]
    assert rows(result) == [
        ["Login", "Name", "Role", "Logged in"],
        ["octo-dev", "octo-dev", "admin", "yes"],
        ["jane-doe", "jane-doe", "tester", "yes"],
        ["Ada-Dev", "Ada-Dev", "developer", "yes"],
        ["build-bot1", "build-bot1", "developer", "no"],
    ]


def test_as_json_is_the_list_of_members_in_the_same_order():
    result = run("--format", "json")
    read = json.loads(result.stdout)
    assert result.exit_code == 0
    assert [entry["login"] for entry in read] == ["octo-dev", "jane-doe", "Ada-Dev", "build-bot1"]
    assert read[0] == {
        "id": 61001,
        "login": "octo-dev",
        "name": "octo-dev",
        "role": "admin",
        "github_id": 1000001,
        "pending_login": False,
    }


@pytest.mark.parametrize(("args", "stdout", "stderr"), [((), "", "No members.\n"), (("json",), "[]\n", "")])
def test_no_member_is_a_line_on_stderr_or_an_empty_list(
    client: type[StubClient], args: tuple[str, ...], stdout: str, stderr: str
):
    client.found = ()
    result = run("--format", "json") if args else run()

    assert result.exit_code == 0
    assert (result.stdout, result.stderr) == (stdout, stderr)


def test_a_login_and_a_name_are_printed_on_one_line_without_their_control_characters(client: type[StubClient]):
    client.found = (
        replace(
            MEMBERS[0],
            login="jane\x1b]8;;https://example.com\x07-doe\u202e",
            name="Jane\nDoe\x1b[2J",
        ),
    )

    result = run()

    assert rows(result)[1] == ["jane-doe", "Jane Doe", "tester", "yes"]

    for control in ("\x1b", "\u202e", "]8;;", "[2J"):
        assert control not in result.stdout


def test_a_user_who_is_not_an_admin_exits_5_with_the_message(client: type[StubClient]):
    client.error = odouche.PermissionDeniedError("Odoo.sh shows a project's members to its admins only.")
    result = run()

    assert result.exit_code == 5
    assert str(client.error) in " ".join(click.unstyle(result.stderr).split())
    assert result.stdout == ""


def test_help_says_who_may_list_them_and_names_the_example():
    result = runner.invoke(app, ["projects", "members", "list", "--help"])
    shown = " ".join(click.unstyle(result.output).split())
    assert result.exit_code == 0
    assert "admin of the project only" in shown
    assert "Example: osh projects members list --project acme-shop" in shown
