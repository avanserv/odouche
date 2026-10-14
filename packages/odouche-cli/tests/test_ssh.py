import ipaddress
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from typing import Self

import click
import pytest
from typer.testing import CliRunner

import odouche
from odouche import Branch, Build, BuildStatus, Commit, SshTarget, Stage
from odouche_cli import _terminal, ssh
from odouche_cli.app import app


ACME = odouche.Project(id=1, name="acme", repository="acme/odoo", url="https://www.odoo.sh/project/acme")
FEATURE = Branch(id=4, name="feature-x", stage=Stage.DEVELOPMENT, stage_name="dev")
BUILD = Build(
    id=104,
    name="acme-feature-x-104",
    branch_id=FEATURE.id,
    branch_name=FEATURE.name,
    commit=Commit(hash="a" * 40, message="Start", author="Ann Example", timestamp=None, url=""),  # pyright: ignore[reportArgumentType]
    status=BuildStatus.DONE,
    status_name="done",
    result=None,
    result_name=None,
    status_info=None,
    started_at=None,
    url="https://acme-feature-x-104.dev.odoo.com",
)
HOST = "acme-feature-x-104.dev.odoo.com"
ADDRESS = ipaddress.IPv4Address("203.0.113.7")
PROGRAM = "/usr/bin/ssh"
SESSION = "s3ss10n-v4lu3"

runner = CliRunner()


class StubClient:
    """Stands in for `odouche.Client`: answers with one branch, its build and the build's target."""

    latest: Build | None = BUILD
    refused: odouche.OdoucheError | None = None
    denied: odouche.OdoucheError | None = None
    """What allowing the address raises."""
    modes: list[bool]
    """The `read_only` each client was built with."""
    events: list[object]

    def __init__(self, *, read_only: bool = False) -> None:
        self.modes.append(read_only)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.events.append("closed")

    def projects(self) -> list[odouche.Project]:
        return [ACME]

    def branches(self, project: str) -> list[Branch]:
        assert project == ACME.name
        return [FEATURE]

    def latest_build(self, branch: Branch) -> Build | None:
        assert branch == FEATURE
        return self.latest

    def ssh_target(self, build: Build) -> SshTarget:
        assert build == BUILD
        if self.refused is not None:
            raise self.refused
        return SshTarget(user=str(build.id), host=HOST)

    def allow_ip(self, branch: Branch) -> ipaddress.IPv4Address:
        assert branch == FEATURE
        assert self.modes[-1] is False
        self.events.append("allowed")
        if self.denied is not None:
            raise self.denied
        return ADDRESS


@pytest.fixture(autouse=True)
def client(monkeypatch: pytest.MonkeyPatch) -> type[StubClient]:
    made = type("Made", (StubClient,), {"modes": [], "events": []})
    monkeypatch.setattr(odouche, "Client", made)
    return made


@pytest.fixture(autouse=True)
def read_only_clients(unreached: object, client: type[StubClient]) -> Iterator[None]:
    """Replace the shared check: a client that writes is built only for a build that did not let this machine in."""
    yield
    assert all(client.modes) or "allowed" in client.events, "A client that writes was built and nothing was allowed."


class Ssh:
    """Stands in for the runs of `ssh` that try to get in, and for the clock of the wait between them."""

    def __init__(self, events: list[object]) -> None:
        self.events = events
        self.outcomes: list[str | None] = [None]
        """What each try prints on stderr when it fails, or `None` when it gets in. The last stands for every try after it."""
        self.now = 0.0

    def run(self, command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        assert command == [PROGRAM, *ssh._TRY, "-l", "104", HOST, "true"]
        assert options["stdin"] is options["stdout"] is subprocess.DEVNULL
        assert (options["stderr"], options["text"]) == (subprocess.PIPE, True)
        self.events.append(("tried", os.environ.get(odouche.SESSION_ENV)))
        said = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        return subprocess.CompletedProcess(command, 255 if said is not None else 0, stderr=said or "")

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture(autouse=True)
def tries(monkeypatch: pytest.MonkeyPatch, client: type[StubClient]) -> Ssh:
    tries = Ssh(client.events)
    monkeypatch.setattr(ssh, "_run", tries.run)
    monkeypatch.setattr(ssh, "_monotonic", lambda: tries.now)
    monkeypatch.setattr(ssh, "_sleep", tries.sleep)
    return tries


TRIED = ("tried", None)
REFUSED = f"ssh: connect to host {HOST} port 22: Connection refused\n"
CLOSED = "Warning: Permanently added the host.\nConnection closed by 203.0.113.9 port 22\n"


@pytest.fixture(autouse=True)
def executed(monkeypatch: pytest.MonkeyPatch, client: type[StubClient], tries: Ssh) -> list[object]:
    """Stand in for the exec, and return the client's events, where each exec is kept with the session it saw."""

    def record(program: str, command: list[str]) -> None:
        client.events.append((program, command, os.environ.get(odouche.SESSION_ENV)))

    monkeypatch.setattr(ssh, "_exec", record)
    monkeypatch.setattr(shutil, "which", lambda name: PROGRAM if name == "ssh" else None)
    return client.events


def unboxed(text: str) -> str:
    """Return a usage error's words on one line: it is boxed and wrapped to the terminal's width."""
    return " ".join(word for word in click.unstyle(text).split() if word not in {"│", "╰", "╭"})


def run(*args: str, input: str | None = None):  # noqa: A002 - the runner's own name
    return runner.invoke(app, ["ssh", "--project", "acme", "--branch", "feature-x", *args], input=input)


def test_the_users_ssh_is_executed_with_the_user_and_the_host_of_the_build_and_no_change(
    client: type[StubClient], executed: list[object]
):
    result = run()

    assert (result.exit_code, result.output) == (0, "")
    assert client.modes == [True]
    # No key and no option but the user: the rest is the user's own configuration.
    assert executed == ["closed", TRIED, (PROGRAM, ["ssh", "-l", "104", HOST], None)]


def test_a_target_odoo_sh_gives_that_is_no_host_executes_nothing(client: type[StubClient], executed: list[object]):
    client.refused = odouche.UpstreamChangedError("ssh target", "url")

    result = run()

    assert result.exit_code == 6
    assert executed == ["closed"]


@pytest.mark.parametrize(
    "args",
    [
        ["ls", "-la"],
        ["odoo-bin", "--help"],
        ["ls", "--branch", "other"],
        ["--", "-L", "8069:localhost:8069"],
        ["--", "-N", "-v"],
        ["--", "odoo-bin", "shell", "--", "-x"],
    ],
)
def test_the_arguments_are_given_to_ssh_after_the_host_as_they_are(executed: list[object], args: list[str]):
    result = run(*args)

    given = args[1:] if args[0] == "--" else args
    assert result.exit_code == 0
    assert executed[-1] == (PROGRAM, ["ssh", "-l", "104", HOST, *given], None)


def test_an_option_for_ssh_that_comes_first_and_not_after_two_dashes_is_a_usage_error(executed: list[object]):
    result = run("-L", "8069:localhost:8069")

    assert result.exit_code == 2
    assert executed == []


def test_the_session_is_not_left_in_the_environment_of_ssh(monkeypatch: pytest.MonkeyPatch, executed: list[object]):
    monkeypatch.setenv(odouche.SESSION_ENV, SESSION)

    result = run()

    assert result.exit_code == 0
    assert executed[-1] == (PROGRAM, ["ssh", "-l", "104", HOST], None)
    assert SESSION not in result.output


def test_the_branch_is_the_one_of_the_checkout_when_none_is_given(checkout, executed: list[object]):
    checkout("feature-x")

    result = runner.invoke(app, ["ssh", "--project", "acme"])

    assert result.exit_code == 0
    assert executed[-1] == (PROGRAM, ["ssh", "-l", "104", HOST], None)


def test_a_branch_with_no_build_executes_nothing(client: type[StubClient], executed: list[object]):
    client.latest = None

    result = run()

    assert result.exit_code == 4
    assert "has no build" in result.output
    assert executed == ["closed"]


def test_without_ssh_the_command_to_run_is_shown_and_nothing_is_executed(
    monkeypatch: pytest.MonkeyPatch, executed: list[object]
):
    monkeypatch.setattr(shutil, "which", lambda _: None)

    result = run("--", "echo", "a b")

    assert result.exit_code == 14
    assert f"ssh -l 104 {HOST} echo 'a b'" in result.output
    assert executed == ["closed"]


def test_on_windows_the_command_to_run_is_shown_and_nothing_is_executed(
    monkeypatch: pytest.MonkeyPatch, executed: list[object]
):
    monkeypatch.setattr(sys, "platform", "win32")

    result = run("--", "echo", "a b")

    assert result.exit_code == 14
    assert f'on Windows. Run it yourself: ssh -l 104 {HOST} echo "a b"' in result.output
    assert executed == ["closed"]


@pytest.fixture
def blocked(tries: Ssh, monkeypatch: pytest.MonkeyPatch) -> Ssh:
    """The address keeps `ssh` out until a rule is added and two tries have passed, asked from a terminal."""
    tries.outcomes = [REFUSED, REFUSED, REFUSED, None]
    monkeypatch.setattr(_terminal, "stdin_is_terminal", lambda: True)
    monkeypatch.setattr(_terminal, "stderr_is_terminal", lambda: True)
    return tries


def test_the_session_is_not_in_the_environment_of_a_try(monkeypatch: pytest.MonkeyPatch, executed: list[object]):
    monkeypatch.setenv(odouche.SESSION_ENV, SESSION)

    run()

    assert TRIED in executed


@pytest.mark.usefixtures("blocked")
def test_a_yes_allows_the_address_once_waits_for_ssh_to_get_in_then_executes_it(
    client: type[StubClient], executed: list[object], tries: Ssh
):
    result = run(input="y\n")

    assert result.exit_code == 0, result.output
    assert client.modes == [True, False]
    command = (PROGRAM, ["ssh", "-l", "104", HOST], None)
    assert executed == ["closed", TRIED, "allowed", "closed", TRIED, TRIED, TRIED, command]
    assert tries.now == 30
    assert f"does not get into build 104 from this machine's address: {REFUSED}" in result.stderr
    assert "on branch feature-x, for one hour.\nAllow it? [y/N]: " in result.stderr
    assert "Odoo.sh allowed 203.0.113.7 for one hour." in result.stderr
    assert result.stdout == ""


@pytest.mark.usefixtures("blocked")
@pytest.mark.parametrize("flag", ["--yes", "-y"])
def test_yes_allows_without_asking(executed: list[object], flag: str):
    result = run(flag)

    assert result.exit_code == 0, result.output
    assert "Allow it?" not in result.stderr
    assert executed.count("allowed") == 1
    assert executed[-1] == (PROGRAM, ["ssh", "-l", "104", HOST], None)


@pytest.mark.usefixtures("blocked")
@pytest.mark.parametrize("answer", ["n\n", "\n", ""], ids=repr)
def test_a_declined_question_sends_nothing_and_executes_nothing(
    client: type[StubClient], executed: list[object], answer: str
):
    result = run(input=answer)

    assert result.exit_code == 1
    assert client.modes == [True]
    assert executed == ["closed", TRIED]
    assert result.stderr.endswith("Allow it? [y/N]: Nothing was sent.\n")


@pytest.mark.usefixtures("blocked")
@pytest.mark.parametrize("stream", ["stdin_is_terminal", "stderr_is_terminal"])
def test_with_no_terminal_and_no_yes_nothing_is_sent_or_executed(
    executed: list[object], monkeypatch: pytest.MonkeyPatch, stream: str
):
    monkeypatch.setattr(_terminal, stream, lambda: False)

    result = run()

    said = unboxed(result.stderr)
    assert result.exit_code == 2
    assert "Give --yes" in said
    assert "Allow my IP" in said
    assert executed == ["closed", TRIED]


def test_with_no_terminal_ssh_that_gets_in_needs_no_yes(executed: list[object], monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(_terminal, "stdin_is_terminal", lambda: False)

    result = run()

    assert result.exit_code == 0
    assert executed[-1] == (PROGRAM, ["ssh", "-l", "104", HOST], None)


@pytest.mark.usefixtures("blocked")
def test_ssh_the_address_keeps_out_to_the_end_exits_with_the_timeout_and_executes_nothing(
    executed: list[object], tries: Ssh
):
    tries.outcomes = [REFUSED, CLOSED]

    result = run("--yes")

    assert result.exit_code == 8
    assert tries.now == 600
    said = " ".join(result.stderr.split())
    assert "still does not get into build 104: Connection closed by 203.0.113.9 port 22." in said
    assert "run `osh ssh` again in a few minutes" in said
    assert executed.count(TRIED) == 1 + 60
    assert executed[-1] == TRIED


def test_a_try_that_outlasts_its_bound_does_not_get_in(
    client: type[StubClient], executed: list[object], monkeypatch: pytest.MonkeyPatch
):
    def hung(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        assert options["timeout"] == 45
        raise subprocess.TimeoutExpired(command, 45)

    monkeypatch.setattr(ssh, "_run", hung)

    result = run()

    assert result.exit_code == 2
    assert "address: no answer within 45 s" in unboxed(result.stderr)
    assert client.modes == [True]


@pytest.mark.usefixtures("blocked")
def test_a_wait_with_no_terminal_says_it_waits_once_a_minute(tries: Ssh, monkeypatch: pytest.MonkeyPatch):
    tries.outcomes = [REFUSED] * 14 + [None]
    monkeypatch.setattr(_terminal, "redraws", lambda _: False)

    result = run("--yes")

    assert result.exit_code == 0
    waiting = [line for line in result.stderr.splitlines() if line.startswith("Waiting")]
    assert waiting == [
        "Waiting for the rule to apply to build 104 (10 s).",
        "Waiting for the rule to apply to build 104 (70 s).",
        "Waiting for the rule to apply to build 104 (130 s).",
    ]


@pytest.mark.usefixtures("blocked")
def test_a_wait_on_a_terminal_redraws_one_line_then_executes_ssh(
    executed: list[object], monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(_terminal, "redraws", lambda _: True)

    result = run("--yes")

    assert result.exit_code == 0
    assert "Waiting for the rule to apply to build 104 (0 s).\n" not in click.unstyle(result.stderr)
    assert executed[-1] == (PROGRAM, ["ssh", "-l", "104", HOST], None)


@pytest.mark.usefixtures("blocked")
@pytest.mark.parametrize(
    ("error", "code"),
    [
        (odouche.PermissionDeniedError("Odoo.sh does not allow this to the session's user."), 5),
        (odouche.UpstreamChangedError("allow_ip", "result"), 6),
        (odouche.OutcomeUnknownError("Odoo.sh did not confirm the allow ip."), 10),
    ],
)
def test_an_allowing_odoo_sh_refuses_or_does_not_confirm_executes_nothing(
    client: type[StubClient], executed: list[object], error: odouche.OdoucheError, code: int
):
    client.denied = error

    result = run("--yes")

    assert result.exit_code == code
    assert "osh builds list" not in result.stderr
    assert executed == ["closed", TRIED, "allowed", "closed"]


@pytest.mark.parametrize(
    "said",
    [
        "104@host: Permission denied (publickey).\n",
        'Load key "/home/ann/.ssh/id_x": Permission denied\n104@host: Permission denied (publickey,password).\n',
    ],
)
def test_ssh_the_build_refuses_the_keys_of_is_executed_with_no_change(
    client: type[StubClient], executed: list[object], tries: Ssh, said: str
):
    tries.outcomes = [said]

    result = run()

    assert result.exit_code == 0
    assert client.modes == [True]
    assert executed == ["closed", TRIED, (PROGRAM, ["ssh", "-l", "104", HOST], None)]
    assert result.stderr == ""


@pytest.mark.usefixtures("blocked")
def test_a_wait_ends_once_only_the_keys_keep_ssh_out(executed: list[object], tries: Ssh):
    tries.outcomes = [REFUSED, REFUSED, "104@host: Permission denied (publickey).\n"]

    result = run("--yes")

    assert result.exit_code == 0
    assert executed.count(TRIED) == 3
    assert executed[-1] == (PROGRAM, ["ssh", "-l", "104", HOST], None)


@pytest.mark.usefixtures("blocked")
def test_a_failed_try_that_says_nothing_is_named_by_its_exit_code(tries: Ssh):
    tries.outcomes = [""]

    result = run(input="n\n")

    assert "address: `ssh` exited with 255" in result.stderr


def test_a_key_warning_before_the_gateway_closes_is_the_address(client: type[StubClient], tries: Ssh):
    tries.outcomes = ['Load key "/home/ann/.ssh/id_x": Permission denied\n' + CLOSED]

    result = run()

    assert result.exit_code == 2
    assert "address: Connection closed by 203.0.113.9 port 22" in unboxed(result.stderr)


def test_a_try_checks_no_host_key_records_none_and_forwards_nothing():
    options = dict(option.split("=", 1) for option in ssh._TRY if option != "-o")

    assert options["StrictHostKeyChecking"] == "no"
    assert options["UserKnownHostsFile"] == "/dev/null"
    assert options["BatchMode"] == options["ClearAllForwardings"] == "yes"
    assert options["ForwardAgent"] == options["ForwardX11"] == options["RequestTTY"] == "no"
    assert options["RemoteCommand"] == "none"
