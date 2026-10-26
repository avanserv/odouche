import json
from datetime import UTC, datetime, timedelta
from typing import Self

import click
import pytest
from typer.testing import CliRunner, Result

import odouche
from odouche import Branch, Build, BuildResult, BuildStatus, Commit, Mail, MailAttachment, MailContent, Stage
from odouche_cli import _output, _time
from odouche_cli.app import app


NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
ACME = odouche.Project(id=1, name="acme", repository="acme/odoo", url="https://www.odoo.sh/project/acme")
STAGING = Branch(id=2, name="staging", stage=Stage.STAGING, stage_name="staging")


def build(number: int) -> Build:
    return Build(
        id=number,
        name=f"acme-staging-{number}",
        branch_id=STAGING.id,
        branch_name=STAGING.name,
        commit=Commit(
            hash="c0ffee1".ljust(40, "a"),
            message="Add the report",
            author="Ann Example",
            timestamp=NOW - timedelta(hours=1),
            url="https://github.com/acme/odoo/commit/c0ffee1",
        ),
        status=BuildStatus.DONE,
        status_name="done",
        result=BuildResult.SUCCESS,
        result_name="success",
        status_info=None,
        started_at=NOW - timedelta(minutes=50),
        url=f"https://acme-staging-{number}.dev.odoo.com",
    )


RESET = Mail(
    id="m2",
    date=NOW - timedelta(minutes=5),
    date_text="Tue, 10 Mar 2026 11:55:00 +0000",
    sender="Acme <noreply@example.com>",
    recipients="ann@example.com",
    subject="Reset your password",
)
WELCOME = Mail(
    id="m1",
    date=None,
    date_text="yesterday",
    sender="Acme <noreply@example.com>",
    recipients="ann@example.com, bob@example.com",
    subject="Welcome",
)
CONTENT = MailContent(
    mail=RESET,
    cc="",
    body="Hello Ann,\n\tFollow the link.",
    attachments=(MailAttachment("invoice.pdf", 2048), MailAttachment("", 3)),
    truncated=False,
)

runner = CliRunner()


class StubClient:
    """Stands in for `odouche.Client`: one branch with builds 104 and 103, and the mails of `caught`."""

    caught: tuple[Mail, ...] = (RESET, WELCOME)
    content: MailContent = CONTENT
    failure: odouche.OdoucheError | None = None
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

    # The library's own, over `branches`.
    branch = odouche.Client.branch

    def branches(self, project: str) -> list[Branch]:
        return [STAGING]

    def builds(self, branch: Branch, *, limit: int = 4) -> list[Build]:
        return [build(104), build(103)][:limit]

    def latest_build(self, branch: Branch) -> Build | None:
        return build(104)

    def mails(self, project: str, branch: Branch, build: Build, *, limit: int = 20) -> list[Mail]:
        self.calls.append(f"mails {project} {branch.name} {build.id} {limit}")

        if self.failure is not None:
            raise self.failure

        return list(self.caught)[:limit]

    def mail(self, project: str, branch: Branch, build: Build, mail_id: str) -> MailContent:
        self.calls.append(f"mail {project} {branch.name} {build.id} {mail_id}")

        if self.failure is not None:
            raise self.failure

        return self.content


@pytest.fixture(autouse=True)
def client(monkeypatch: pytest.MonkeyPatch) -> type[StubClient]:
    class Client(StubClient):
        modes: list[bool] = []
        calls: list[str] = []

    monkeypatch.setattr(odouche, "Client", Client)
    monkeypatch.setattr(_time, "_now", lambda: NOW)

    return Client


def run(*args: str, json_format: bool = False) -> Result:
    head = ["--format", "json"] if json_format else []
    return runner.invoke(app, [*head, "builds", "mails", *args, "--project", "acme", "--branch", "staging"])


def test_lists_the_latest_build_s_mails_with_their_headers(client: type[StubClient]):
    result = run()

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == [
        "ID  Date           From                        To                                Subject",
        "m2  5 minutes ago  Acme <noreply@example.com>  ann@example.com                   Reset your password",
        "m1  yesterday      Acme <noreply@example.com>  ann@example.com, bob@example.com  Welcome",
    ]
    assert client.calls == ["mails acme staging 104 20"]
    assert client.modes == [True]


def test_lists_the_mails_of_a_build_by_its_number_up_to_the_limit(client: type[StubClient]):
    result = run("103", "--limit", "1")

    assert result.exit_code == 0, result.output
    assert len(result.stdout.splitlines()) == 2
    assert client.calls == ["mails acme staging 103 1"]


def test_a_build_that_caught_nothing_says_so_and_exits_0(client: type[StubClient]):
    client.caught = ()
    result = run()

    assert result.exit_code == 0
    assert result.stdout == ""
    assert result.stderr == "Build 104 caught no mail.\n"


def test_as_json_a_build_that_caught_nothing_is_an_empty_list(client: type[StubClient]):
    client.caught = ()
    result = run(json_format=True)

    assert result.exit_code == 0
    assert json.loads(result.stdout) == []


def test_as_json_each_mail_is_its_model():
    result = run(json_format=True)

    assert json.loads(result.stdout)[1] == {
        "id": "m1",
        "date": None,
        "date_text": "yesterday",
        "sender": "Acme <noreply@example.com>",
        "recipients": "ann@example.com, bob@example.com",
        "subject": "Welcome",
    }


def test_a_header_is_listed_without_its_escape_sequences(client: type[StubClient]):
    client.caught = (Mail("m3", None, "", "x", "y", "\x1b]0;owned\x07Hi\x1b[2J\nthere"),)
    result = run()

    assert "\x1b" not in result.stdout
    assert "\x07" not in result.stdout
    assert "Hi" in result.stdout


def test_shows_one_mail_with_its_headers_then_its_body(client: type[StubClient]):
    result = run("--mail", "m2")

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == [
        "ID           m2",
        "Date         5 minutes ago",
        "From         Acme <noreply@example.com>",
        "To           ann@example.com",
        "Cc",
        "Subject      Reset your password",
        "Attachments  invoice.pdf (2048 B), (no name) (3 B)",
        "",
        "Hello Ann,",
        "\tFollow the link.",
    ]
    assert result.stderr == ""
    assert client.calls == ["mail acme staging 104 m2"]
    assert client.modes == [True]


@pytest.mark.usefixtures("terminal")
@pytest.mark.parametrize("stdout", ["terminal", "pipe"])
def test_the_body_is_printed_without_escape_sequences_on_a_terminal_or_not(
    client: type[StubClient], monkeypatch: pytest.MonkeyPatch, stdout: str
):
    monkeypatch.setattr(_output, "_is_terminal", lambda: stdout == "terminal")
    client.content = MailContent(RESET, "", "\x1b]0;title\x07Click\x1b[2J here\x9b31m\x00", (), truncated=False)
    result = run("--mail", "m2")

    assert result.exit_code == 0, result.output
    assert result.stdout.endswith("\n\nClick here\n")
    assert "title" not in result.stdout


def test_a_mail_with_no_attachment_shows_none(client: type[StubClient]):
    client.content = MailContent(WELCOME, "cc@example.com", "", (), truncated=False)
    result = run("--mail", "m1")

    assert "Attachments" in result.stdout.splitlines()
    assert "Cc           cc@example.com" in result.stdout.splitlines()


def test_as_json_one_mail_is_its_model_and_nothing_else(client: type[StubClient]):
    result = run("--mail", "m2", json_format=True)

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "mail": {
            "id": "m2",
            "date": "2026-03-10T11:55:00+00:00",
            "date_text": "Tue, 10 Mar 2026 11:55:00 +0000",
            "sender": "Acme <noreply@example.com>",
            "recipients": "ann@example.com",
            "subject": "Reset your password",
        },
        "cc": "",
        "body": "Hello Ann,\n\tFollow the link.",
        "attachments": [{"name": "invoice.pdf", "size": 2048}, {"name": "", "size": 3}],
        "truncated": False,
    }


@pytest.mark.parametrize(
    ("body", "said"),
    [
        (
            "x" * 10,
            "The mail was cut: to 1 MiB of body, 65536 characters a header or 1000 MIME parts, containers included.\n",
        ),
        ("", "The mail is over 16 MiB or could not be read: its body and attachments are not shown.\n"),
    ],
)
def test_a_truncated_mail_says_so_on_stderr(client: type[StubClient], body: str, said: str):
    client.content = MailContent(RESET, "", body, (), truncated=True)

    for json_format in (False, True):
        result = run("--mail", "m2", json_format=json_format)

        assert result.exit_code == 0, result.output
        assert result.stderr == said


def test_a_limit_with_a_mail_is_a_usage_error(client: type[StubClient]):
    result = run("--mail", "m2", "--limit", "5")

    assert result.exit_code == 2
    assert "--limit goes without --mail" in " ".join(click.unstyle(result.stderr).split())
    assert client.modes == []


@pytest.mark.parametrize("args", [(), ("--mail", "m9")])
def test_what_is_not_found_exits_4(client: type[StubClient], args: tuple[str, ...]):
    client.failure = odouche.NotFoundError("Branch staging is production: no mail.")
    result = run(*args)

    assert result.exit_code == 4
    assert result.stderr == "Branch staging is production: no mail.\n"
