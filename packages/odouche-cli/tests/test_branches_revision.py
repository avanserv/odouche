import json
import re
from collections.abc import Callable
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from typing import Self

import click
import pytest
from typer.testing import CliRunner, Result

import odouche
from odouche import Branch, Build, BuildResult, BuildRevision, BuildStatus, Commit, OdooRef, OdooRevision, Stage
from odouche_cli import _time
from odouche_cli.app import app


NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
SUBMODULES = "Submodule commits are not available: Odoo.sh does not give them.\n"
ACME = odouche.Project(id=1, name="acme", repository="acme/odoo", url="https://www.odoo.sh/project/acme")
MAIN = Branch(id=1, name="main", stage=Stage.PRODUCTION, stage_name="production")
FEATURE = Branch(id=4, name="feature-x", stage=Stage.DEVELOPMENT, stage_name="dev")
HEAD = "c0ffee1".ljust(40, "a")
ODOO, ENTERPRISE, THEMES = ("1" * 40, "2" * 40, "3" * 40)


def build(number: int) -> Build:
    return Build(
        id=number,
        name=f"acme-feature-x-{number}",
        branch_id=FEATURE.id,
        branch_name=FEATURE.name,
        commit=Commit(
            hash=HEAD,
            message="Add the report\n\nWith its tests.",
            author="Ann Example",
            timestamp=NOW - timedelta(hours=1),
            url=f"https://github.com/acme/odoo/commit/{HEAD}",
        ),
        status=BuildStatus.DONE,
        status_name="done",
        result=BuildResult.SUCCESS,
        result_name="success",
        status_info=None,
        started_at=NOW - timedelta(minutes=50),
        url=f"https://acme-feature-x-{number}.dev.odoo.com",
    )


LATEST = OdooRevision(
    id=2210,
    version="19.0",
    pinned=False,
    refs=(
        OdooRef("odoo", ODOO, "https://github.com/odoo/odoo"),
        OdooRef("enterprise", ENTERPRISE, "https://github.com/odoo/enterprise"),
        OdooRef("themes", THEMES, "https://github.com/odoo/design-themes"),
    ),
)

runner = CliRunner()


class StubClient:
    """Stands in for `odouche.Client`: answers with the branches, their builds and a build's revision, and records the calls."""

    built: tuple[Build, ...] = (build(104), build(103))
    selected: OdooRevision | None = LATEST
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
        return [MAIN, FEATURE]

    def builds(self, branch: Branch, *, limit: int = 4) -> list[Build]:
        self.calls.append(f"builds {branch.name}")
        return list(self.built)[:limit] if branch == FEATURE else []

    def latest_build(self, branch: Branch) -> Build | None:
        self.calls.append(f"latest {branch.name}")
        return next(iter(self.builds(branch, limit=1)), None)

    def build_revision(self, project: str, build: Build) -> BuildRevision:
        self.calls.append(f"revision {project} {build.id}")
        return BuildRevision(build.id, build.name, build.branch_name, build.commit, "19.0", self.selected)


@pytest.fixture(autouse=True)
def client(monkeypatch: pytest.MonkeyPatch) -> type[StubClient]:
    class Client(StubClient):
        modes: list[bool] = []
        calls: list[str] = []

    monkeypatch.setattr(odouche, "Client", Client)
    monkeypatch.setattr(_time, "_now", lambda: NOW)

    return Client


def run(*args: str) -> Result:
    return runner.invoke(app, ["branches", "revision", *args])


def pairs(result: Result) -> dict[str, str]:
    """Read each line as a header and its value, which two spaces or more separate."""
    found = [re.split(r"\s{2,}", line.strip(), maxsplit=1) for line in result.stdout.splitlines()]

    return {row[0]: row[1] if len(row) > 1 else "" for row in found}


def test_the_head_commit_and_the_branch_s_odoo_revision_are_on_a_line_each(client: type[StubClient]):
    result = run("--project", "acme", "--branch", "feature-x")

    assert result.exit_code == 0
    assert client.calls == ["branches acme", "latest feature-x", "builds feature-x", "revision acme 104"]
    assert client.modes == [True]
    assert pairs(result) == {
        "Build": "104",
        "Name": "acme-feature-x-104",
        "Branch": "feature-x",
        "Commit": HEAD,
        "Subject": "Add the report",
        "Author": "Ann Example",
        "Committed": "1 hour ago",
        "Commit URL": f"https://github.com/acme/odoo/commit/{HEAD}",
        "Odoo version": "19.0",
        "Branch's Odoo revision": "2210, latest of 19.0",
        "Branch's odoo": ODOO,
        "Branch's enterprise": ENTERPRISE,
        "Branch's themes": THEMES,
    }
    assert result.stderr == SUBMODULES


@pytest.mark.parametrize(
    ("selected", "shown"),
    [(replace(LATEST, id=2206, pinned=True, refs=LATEST.refs[:1]), "2206, pinned, 19.0"), (None, "none")],
)
def test_a_pinned_revision_or_none_is_said(client: type[StubClient], selected: OdooRevision | None, shown: str):
    client.selected = selected
    shown_pairs = pairs(run("--project", "acme", "--branch", "feature-x"))

    assert shown_pairs["Branch's Odoo revision"] == shown
    assert [
        header for header in shown_pairs if header.startswith("Branch's ") and header != "Branch's Odoo revision"
    ] == ([] if selected is None else ["Branch's odoo"])


def test_a_repository_s_name_is_printed_without_its_escape_sequences(client: type[StubClient]):
    client.selected = replace(LATEST, refs=(OdooRef("od\x1b[2Joo", ODOO, "https://github.com/odoo/odoo"),))
    result = run("--project", "acme", "--branch", "feature-x")

    assert "\x1b" not in result.stdout
    assert pairs(result)["Branch's od[2Joo"] == ODOO


def test_the_build_is_named_by_its_number(client: type[StubClient]):
    result = run("--project", "acme", "--branch", "feature-x", "--build", "103")

    assert result.exit_code == 0
    assert client.calls == ["branches acme", "builds feature-x", "revision acme 103"]
    assert pairs(result)["Build"] == "103"


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (
            ("--branch", "feature-x", "--build", "7"),
            "Build 7 is not among the latest builds of branch feature-x of acme.",
        ),
        (("--branch", "main"), "Branch main of acme has no build."),
    ],
)
def test_a_build_not_found_exits_4(client: type[StubClient], args: tuple[str, ...], message: str):
    result = run("--project", "acme", *args)

    assert result.exit_code == 4
    assert result.stdout == ""
    assert result.stderr == f"{message}\n"
    assert not any(call.startswith("revision") for call in client.calls)


def test_as_json_is_the_whole_model_with_full_hashes():
    result = runner.invoke(
        app, ["--format", "json", "branches", "revision", "--project", "acme", "--branch", "feature-x"]
    )

    assert result.exit_code == 0
    shown = json.loads(result.stdout)
    assert list(shown) == [field.name for field in fields(BuildRevision)]
    assert shown["commit"]["hash"] == HEAD
    assert shown["branch_odoo_revision"] == {
        "id": 2210,
        "version": "19.0",
        "pinned": False,
        "refs": [
            {"repository": "odoo", "commit_hash": ODOO, "url": "https://github.com/odoo/odoo"},
            {"repository": "enterprise", "commit_hash": ENTERPRISE, "url": "https://github.com/odoo/enterprise"},
            {"repository": "themes", "commit_hash": THEMES, "url": "https://github.com/odoo/design-themes"},
        ],
    }
    assert all(len(ref["commit_hash"]) == 40 for ref in shown["branch_odoo_revision"]["refs"])
    assert result.stderr == SUBMODULES


def test_the_project_and_the_branch_come_from_the_checkout(client: type[StubClient], checkout: Callable[..., None]):
    checkout("feature-x", origin="git@github.com:acme/odoo.git")

    result = run()

    assert result.exit_code == 0
    assert client.calls == ["projects", "branches acme", "latest feature-x", "builds feature-x", "revision acme 104"]


def test_help_names_the_example():
    result = runner.invoke(app, ["branches", "revision", "--help"])

    assert result.exit_code == 0
    assert "Example: osh branches revision" in click.unstyle(result.output)
