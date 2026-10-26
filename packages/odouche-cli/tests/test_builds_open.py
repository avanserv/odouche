import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Self

import click
import pytest
from typer.testing import CliRunner, Result

import odouche
from odouche import Branch, Build, BuildResult, BuildStatus, Commit, Stage
from odouche_cli import builds
from odouche_cli.app import app


NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
SESSION = "s3ss10n-v4lu3"

ACME = odouche.Project(id=1, name="acme", repository="acme/odoo", url="https://www.odoo.sh/project/acme")
STAGING = Branch(id=2, name="staging", stage=Stage.STAGING, stage_name="staging")
FEATURE = Branch(id=4, name="feature-x", stage=Stage.DEVELOPMENT, stage_name="dev")
MONITOR = "https://www.odoo.sh/project/acme/branches/staging/monitor"


def build(number: int, branch: Branch = STAGING) -> Build:
    return Build(
        id=number,
        name=f"acme-{branch.name}-{number}",
        branch_id=branch.id,
        branch_name=branch.name,
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
        url=f"https://acme-{branch.name}-{number}.dev.odoo.com",
    )


WAITING = replace(
    build(105), status=BuildStatus.PROGRESS, status_name="progress", result=None, result_name=None, started_at=None
)

runner = CliRunner()


class StubClient:
    """Stands in for `odouche.Client`: answers with the branches and their builds, and builds URLs as the library does."""

    built: tuple[Build, ...] = (build(104), build(103))
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
        return [ACME]

    # The library's own, over `branches`.
    branch = odouche.Client.branch

    def branches(self, project: str) -> list[Branch]:
        self.calls.append(f"branches {project}")
        return [STAGING, FEATURE]

    def builds(self, branch: Branch, *, limit: int = 4) -> list[Build]:
        self.calls.append(f"builds {branch.name}")
        if branch == FEATURE:
            return [build(99, FEATURE)]
        return list(self.built)[:limit]

    def latest_build(self, branch: Branch) -> Build | None:
        self.calls.append(f"latest {branch.name}")
        return next(iter(self.builds(branch, limit=1)), None)

    # The library's own, which asks nothing.
    panel_url = odouche.Client.panel_url


@pytest.fixture(autouse=True)
def client(monkeypatch: pytest.MonkeyPatch) -> type[StubClient]:
    class Client(StubClient):
        modes: list[bool] = []
        calls: list[str] = []

    monkeypatch.setattr(odouche, "Client", Client)
    return Client


class Browser:
    """Stands in for the user's browser: records each URL with the session it inherits, and answers `opens`."""

    def __init__(self) -> None:
        self.opened: list[tuple[str, str | None]] = []
        self.opens = True

    def __call__(self, url: str) -> bool:
        self.opened.append((url, os.environ.get(odouche.SESSION_ENV)))
        return self.opens


@pytest.fixture
def browser(monkeypatch: pytest.MonkeyPatch) -> Browser:
    browser = Browser()
    monkeypatch.setattr(builds, "_browse", browser)
    return browser


def run(*args: str) -> Result:
    return runner.invoke(app, ["builds", "open", *args, "--project", "acme", "--branch", "staging"])


def test_the_monitor_url_alone_is_printed_and_no_browser_starts(client: type[StubClient]):
    result = run("monitor")

    assert result.exit_code == 0, result.output
    assert result.stdout == f"{MONITOR}\n"
    assert result.stderr == ""
    assert client.modes == [True]


@pytest.mark.parametrize(
    ("panel", "url"),
    [
        ("shell", "https://acme-staging-104.dev.odoo.com/odoo-sh/webshell"),
        ("editor", "https://acme-staging-104.dev.odoo.com/odoo-sh/editor"),
    ],
)
def test_the_shell_and_the_editor_are_on_the_latest_build_s_host(client: type[StubClient], panel: str, url: str):
    result = run(panel)

    assert result.exit_code == 0, result.output
    assert result.stdout == f"{url}\n"
    assert client.calls == ["branches acme", "latest staging", "builds staging"]


def test_a_build_is_named_by_its_number(client: type[StubClient]):
    result = run("shell", "103")

    assert result.exit_code == 0, result.output
    assert result.stdout == "https://acme-staging-103.dev.odoo.com/odoo-sh/webshell\n"
    assert client.calls == ["branches acme", "builds staging"]


def test_as_json_the_url_is_a_string():
    result = runner.invoke(
        app, ["--format", "json", "builds", "open", "monitor", "--project", "acme", "--branch", "staging"]
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == MONITOR


def test_open_hands_the_url_to_the_browser_without_the_session(monkeypatch: pytest.MonkeyPatch, browser: Browser):
    monkeypatch.setenv(odouche.SESSION_ENV, SESSION)

    result = run("shell", "--open")

    assert result.exit_code == 0, result.output
    assert browser.opened == [("https://acme-staging-104.dev.odoo.com/odoo-sh/webshell", None)]
    assert result.stdout == ""
    assert result.stderr == "Sent the shell of build 104 to your browser.\n"


def test_with_no_browser_the_url_is_printed_for_the_user_to_open(browser: Browser):
    browser.opens = False

    result = run("monitor", "--open")

    assert result.exit_code == 14
    assert result.stdout == f"{MONITOR}\n"
    assert result.stderr == "No browser could be started. Open this URL yourself:\n"


def test_a_build_waiting_for_a_worker_exits_4_and_opens_nothing(client: type[StubClient], browser: Browser):
    client.built = (WAITING, build(104))

    result = run("editor", "--open")

    assert result.exit_code == 4
    assert result.stdout == ""
    assert result.stderr == "Build 105 is waiting for a worker: it has no panels yet.\n"
    assert browser.opened == []


def test_the_monitor_of_a_development_branch_exits_4():
    result = runner.invoke(app, ["builds", "open", "monitor", "--project", "acme", "--branch", "feature-x"])

    assert result.exit_code == 4
    assert result.stderr.startswith("Branch feature-x has no monitor:")


@pytest.mark.parametrize(("args", "said"), [(("bogus",), "bogus"), (("monitor", "104"), "takes no BUILD_ID")])
def test_a_usage_error_exits_2_and_builds_no_client(client: type[StubClient], args: tuple[str, ...], said: str):
    result = run(*args)

    assert result.exit_code == 2
    assert said in " ".join(click.unstyle(result.stderr).split())
    assert client.modes == []
