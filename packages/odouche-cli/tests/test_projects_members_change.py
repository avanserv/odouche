import json
import re
from dataclasses import replace
from typing import Self

import click
import pytest
from typer.testing import CliRunner, Result

import odouche
from odouche import MemberRole, ProjectMember
from odouche_cli import _terminal
from odouche_cli.app import app


ACME = odouche.Project(id=1, name="acme", repository="acme/odoo", url="https://www.odoo.sh/project/acme")
SESSION = odouche.SessionInfo(odouche.SessionSource.KEYRING, None, None)
OCTO = ProjectMember(61001, "octo-dev", "octo-dev", MemberRole.ADMIN, 1000001, pending_login=False)
JANE = ProjectMember(61002, "jane-doe", "jane-doe", MemberRole.TESTER, 1000002, pending_login=False)
BOT = ProjectMember(61003, "build-bot1", "build-bot1", MemberRole.DEVELOPER, 1000003, pending_login=True)
ADD = ("projects", "members", "add", "--project", "acme")
ROLE = ("projects", "members", "role", "--project", "acme")
ESCAPE = "\x1b[2J\x1b]0;owned\x07"
REACH = {
    "admin": "An admin reaches production: its database, shell and logs, and the project's settings.",
    "tester": "A tester reaches staging, not production.",
    "developer": "A developer reaches development branches only.",
}
NO_INVITATION = "Odoo.sh sends them no invitation, and push access to the repository is given on GitHub."

runner = CliRunner()


class StubClient:
    """Stands in for `odouche.Client`: changes the members as the library does, and records the calls."""

    listed: tuple[ProjectMember, ...] = (OCTO, JANE, BOT)
    caller: str = "octo-dev"
    lost: Exception | None = None
    modes: list[bool]
    calls: list[str]

    def __init__(self, *, read_only: bool = False) -> None:
        self.modes.append(read_only)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def projects(self) -> list[odouche.Project]:
        return [ACME]

    def identity(self) -> odouche.Identity:
        self.calls.append("identity")
        return odouche.Identity(user_id=7301, name=None, username=self.caller, email=None, session=SESSION)

    def members(self, project: str) -> list[ProjectMember]:
        self.calls.append(f"members {project}")
        return list(self.listed)

    # The library's own, which ask nothing.
    check_add_member = staticmethod(odouche.Client.check_add_member)
    check_member_role = odouche.Client.check_member_role

    def add_member(self, project: str, login: str, role: MemberRole) -> ProjectMember:
        self.calls.append(f"add {login} {role.value}")

        if self.lost is not None:
            raise self.lost

        return ProjectMember(61004, "Octo-Cat", "Octo-Cat", role, 1000004, pending_login=True)

    def set_member_role(self, project: str, member: ProjectMember, role: MemberRole) -> ProjectMember:
        self.calls.append(f"role {member.login} {role.value}")

        if self.lost is not None:
            raise self.lost

        return replace(member, role=role)


@pytest.fixture(autouse=True)
def read_only_clients() -> None:
    """Replace the shared check: the commands of this file are ones that write."""


@pytest.fixture(autouse=True)
def client(monkeypatch: pytest.MonkeyPatch) -> type[StubClient]:
    class Client(StubClient):
        modes: list[bool] = []
        calls: list[str] = []

    monkeypatch.setattr(odouche, "Client", Client)
    monkeypatch.setattr(_terminal, "stdin_is_terminal", lambda: True)
    monkeypatch.setattr(_terminal, "stderr_is_terminal", lambda: True)

    return Client


def run(*args: str, stdin: str | None = None) -> Result:
    return runner.invoke(app, list(args), input=stdin)


def sends(client: type[StubClient]) -> list[str]:
    return [call for call in client.calls if call.startswith(("add", "role"))]


def rows(result: Result) -> dict[str, str]:
    return dict(re.split(r"\s{2,}", line.strip(), maxsplit=1) for line in result.stdout.splitlines())


@pytest.mark.parametrize("role", ["developer", "tester", "admin"])
def test_a_yes_adds_the_user_once_with_the_role_and_prints_them(client: type[StubClient], role: str):
    result = run(*ADD, "octo-cat", "--role", role, stdin="y\n")

    assert result.exit_code == 0
    assert client.calls == ["members acme", f"add octo-cat {role}"]
    assert client.modes == [False]
    assert result.stderr.splitlines() == [
        "Project: acme",
        "Member: octo-cat",
        f"Role: {role}",
        REACH[role],
        NO_INVITATION,
        f"Add octo-cat to acme as {role}? [y/N]: Octo-Cat is now a member of acme, as {role}.",
    ]
    assert rows(result) == {"Login": "Octo-Cat", "Name": "Octo-Cat", "Role": role, "Logged in": "no"}


def test_the_role_of_an_addition_is_developer_unless_given(client: type[StubClient]):
    result = run(*ADD, "octo-cat", "--yes")

    assert result.exit_code == 0
    assert sends(client) == ["add octo-cat developer"]
    assert "[y/N]" not in result.stderr


def test_only_the_admin_is_said_to_reach_production(client: type[StubClient]):
    said = {role: run(*ADD, "octo-cat", "--role", role, "--yes").stderr for role in REACH}

    assert [role for role, stderr in said.items() if "reaches production" in stderr] == ["admin"]


@pytest.mark.parametrize("answer", ["n\n", "\n", "no\n", ""], ids=repr)
def test_anything_but_a_yes_adds_nothing_and_exits_1(client: type[StubClient], answer: str):
    result = run(*ADD, "octo-cat", stdin=answer)

    assert result.exit_code == 1
    assert sends(client) == []
    assert result.stdout == ""
    assert result.stderr.endswith("Add octo-cat to acme as developer? [y/N]: Nothing was sent.\n")


@pytest.mark.parametrize("login", ["-octo", "octo--cat", "octo_cat", "a" * 40, "é"])
def test_a_login_github_would_refuse_is_a_usage_error_before_any_client(client: type[StubClient], login: str):
    result = run(*ADD, "--yes", "--", login)

    assert result.exit_code == 2
    assert client.modes == []
    assert "is not a GitHub login" in " ".join(click.unstyle(result.stderr).replace("│", " ").split())


@pytest.mark.parametrize("command", [(*ADD, "octo-cat", "--role"), (*ROLE, "jane-doe")])
@pytest.mark.parametrize("role", ["owner", "Admin", ""])
def test_a_role_that_is_not_one_is_a_usage_error_before_any_client(
    client: type[StubClient], command: tuple[str, ...], role: str
):
    result = run(*command, role, "--yes")

    assert result.exit_code == 2
    assert client.modes == []
    assert "developer" in click.unstyle(result.stderr)


@pytest.mark.parametrize("command", [(*ADD, "octo-cat"), (*ROLE, "jane-doe", "developer")])
@pytest.mark.parametrize("name", ["stdin_is_terminal", "stderr_is_terminal"])
def test_a_run_nobody_attends_is_refused_before_a_client_is_opened(
    client: type[StubClient], monkeypatch: pytest.MonkeyPatch, command: tuple[str, ...], name: str
):
    monkeypatch.setattr(_terminal, name, lambda: False)

    result = run(*command, stdin="y\n")

    assert result.exit_code == 2
    assert client.modes == []
    assert "Stdin or stderr is not a terminal" in click.unstyle(result.stderr)


@pytest.mark.parametrize("login", ["jane-doe", "Jane-Doe"])
def test_a_member_added_again_exits_9_before_the_question(client: type[StubClient], login: str):
    result = run(*ADD, login, stdin="y\n")

    assert result.exit_code == 9
    assert sends(client) == []
    assert "[y/N]" not in result.stderr
    assert "jane-doe is already a member, with the role tester" in result.stderr


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (odouche.NotFoundError("GitHub has no user octo-cat that Odoo.sh finds."), 4),
        (odouche.PermissionDeniedError("Odoo.sh's grant on GitHub does not cover this."), 5),
        (odouche.MemberRefusedError("Octo-Cat is already a member, as jane-doe, with the role tester."), 9),
    ],
)
def test_a_refusal_after_the_question_exits_with_its_code(
    client: type[StubClient], error: odouche.OdoucheError, code: int
):
    client.lost = error
    result = run(*ADD, "octo-cat", "--yes")

    assert result.exit_code == code
    assert result.stdout == ""
    assert "is now a member" not in result.stderr
    assert str(error) in result.stderr


@pytest.mark.parametrize(
    ("command", "operation", "hint"),
    [
        (
            (*ADD, "octo-cat"),
            "member addition",
            (
                "`osh projects members list` shows whether they were added. Adding them again is refused once they "
                "are a member."
            ),
        ),
        (
            (*ROLE, "jane-doe", "developer"),
            "member role change",
            "`osh projects members list` shows their role. Setting the same role again sends nothing.",
        ),
    ],
)
def test_an_unknown_outcome_exits_10_and_says_where_to_look(
    client: type[StubClient], command: tuple[str, ...], operation: str, hint: str
):
    client.lost = odouche.OutcomeUnknownError("It was sent. Look before trying again.", operation=operation)
    result = run(*command, "--yes")

    assert result.exit_code == 10
    assert len(sends(client)) == 1
    assert result.stdout == ""
    assert result.stderr.splitlines()[-2:] == ["It was sent. Look before trying again.", hint]


@pytest.mark.parametrize("login", ["jane-doe", "JANE-DOE"])
def test_a_yes_changes_a_role_once_and_prints_the_member(client: type[StubClient], login: str):
    result = run(*ROLE, login, "developer", stdin="y\n")

    assert result.exit_code == 0
    assert client.calls == ["members acme", "role jane-doe developer"]
    assert client.modes == [False]
    assert result.stderr.splitlines() == [
        "Project: acme",
        "Member: jane-doe",
        "Role: tester → developer",
        REACH["developer"],
        "Change jane-doe's role on acme to developer? [y/N]: jane-doe is now developer on acme.",
    ]
    assert rows(result)["Role"] == "developer"


@pytest.mark.parametrize("answer", ["n\n", ""], ids=repr)
def test_anything_but_a_yes_changes_no_role_and_exits_1(client: type[StubClient], answer: str):
    result = run(*ROLE, "jane-doe", "admin", stdin=answer)

    assert result.exit_code == 1
    assert sends(client) == []
    assert result.stderr.endswith("Change jane-doe's role on acme to admin? [y/N]: Nothing was sent.\n")


def test_the_role_a_member_has_already_exits_0_with_nothing_sent_and_no_question(client: type[StubClient]):
    result = run(*ROLE, "jane-doe", "tester", stdin="y\n")

    assert result.exit_code == 0
    assert client.calls == ["members acme"]
    assert result.stderr == "jane-doe is already tester on acme. Nothing was sent.\n"
    assert rows(result)["Role"] == "tester"


def test_a_login_that_is_not_a_member_exits_4_with_nothing_sent(client: type[StubClient]):
    result = run(*ROLE, "octo-cat", "developer", stdin="y\n")

    assert result.exit_code == 4
    assert sends(client) == []
    assert "[y/N]" not in result.stderr
    assert "octo-cat is not a member of the project." in result.stderr


@pytest.mark.parametrize("role", ["tester", "developer"])
def test_the_last_admin_lowered_exits_9_before_the_question(client: type[StubClient], role: str):
    result = run(*ROLE, "octo-dev", role, stdin="y\n")

    assert result.exit_code == 9
    assert sends(client) == []
    assert "[y/N]" not in result.stderr
    assert "octo-dev is the last admin of the project" in result.stderr


def test_an_admin_lowering_themselves_is_told_they_cannot_change_it_back(client: type[StubClient]):
    client.listed = (OCTO, replace(JANE, role=MemberRole.ADMIN), BOT)
    result = run(*ROLE, "octo-dev", "tester", "--yes")

    assert result.exit_code == 0
    assert sends(client) == ["role octo-dev tester"]
    assert "This is you: you will not be able to change it back." in result.stderr.splitlines()


def test_lowering_another_admin_does_not_say_it_is_you(client: type[StubClient]):
    client.listed = (OCTO, replace(JANE, role=MemberRole.ADMIN), BOT)
    result = run(*ROLE, "jane-doe", "tester", "--yes")

    assert result.exit_code == 0
    assert "identity" in client.calls
    assert "This is you" not in result.stderr


def test_raising_a_member_asks_nobody_who_they_are(client: type[StubClient]):
    result = run(*ROLE, "build-bot1", "admin", "--yes")

    assert result.exit_code == 0
    assert "identity" not in client.calls
    assert REACH["admin"] in result.stderr


def test_an_escape_sequence_in_a_login_read_from_odoo_sh_is_not_emitted(client: type[StubClient]):
    client.listed = (OCTO, replace(JANE, login=f"jane{ESCAPE}"), BOT)
    result = run(*ROLE, f"jane{ESCAPE}", "developer", stdin="y\n")

    assert result.exit_code == 0
    assert not re.search(r"[\x00-\x09\x0b-\x1f\x7f-\x9f]", result.stderr + result.stdout)
    assert "Member: jane[2J]0;owned" in result.stderr


@pytest.mark.parametrize(
    ("command", "login"), [((*ADD, "octo-cat"), "Octo-Cat"), ((*ROLE, "jane-doe", "admin"), "jane-doe")]
)
def test_json_is_the_member(client: type[StubClient], command: tuple[str, ...], login: str):
    result = run("--format", "json", *command, "--yes")

    assert json.loads(result.stdout)["login"] == login


@pytest.mark.parametrize("command", ["add", "role"])
def test_help_opens_no_client_and_its_first_line_says_it_changes_state(client: type[StubClient], command: str):
    result = run("projects", "members", command, "--help")

    assert result.exit_code == 0
    lines = [line.strip() for line in click.unstyle(result.output).splitlines() if line.strip()]
    assert lines[1].startswith("Change state on Odoo.sh:")
    assert client.modes == []
