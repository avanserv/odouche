import json
import re
from collections.abc import Callable
from dataclasses import fields, replace
from typing import Self

import click
import pytest
from typer.testing import CliRunner, Result

import odouche
from odouche import AiAgent, Branch, BranchSettings, BuildTests, ModuleInstall, PushBehavior, Stage
from odouche_cli._context import BRANCH_ENV
from odouche_cli.app import app


ACME = odouche.Project(id=1, name="acme", repository="acme/odoo", url="https://www.odoo.sh/project/acme")
MAIN = Branch(id=1, name="main", stage=Stage.PRODUCTION, stage_name="production")
FEATURE = Branch(id=4, name="feature-x", stage=Stage.DEVELOPMENT, stage_name="dev")
DEVELOPMENT = BranchSettings(
    push_behavior=PushBehavior.NEW_BUILD,
    project_defaults=True,
    module_install=ModuleInstall.REPOSITORY,
    modules=(),
    tests=BuildTests.MODULES,
    test_tags=None,
    demo_data=False,
    ai_agent=AiAgent.CLAUDE,
    odoo_version=None,
    odoo_revision_id=None,
    machine="ubuntu-24.04",
    recommended_machine="ubuntu-24.04",
    next_machine=None,
    domains=(),
    dns_target="acme-feature-x-104.dev.odoo.com",
)

runner = CliRunner()


class StubClient:
    """Stands in for `odouche.Client`: answers with the branches and a branch's settings, and records the calls."""

    found: BranchSettings = DEVELOPMENT
    refused: odouche.OdoucheError | None = None
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

    def branches(self, project: str) -> list[Branch]:
        self.calls.append(f"branches {project}")
        return [MAIN, FEATURE]

    def branch_settings(self, branch: Branch) -> BranchSettings:
        self.calls.append(f"settings {branch.name}")
        if self.refused is not None:
            raise self.refused
        return self.found


@pytest.fixture(autouse=True)
def client(monkeypatch: pytest.MonkeyPatch) -> type[StubClient]:
    class Client(StubClient):
        modes: list[bool] = []
        calls: list[str] = []

    monkeypatch.setattr(odouche, "Client", Client)
    return Client


def run(*args: str) -> Result:
    return runner.invoke(app, ["branches", "settings", *args])


def pairs(result: Result) -> dict[str, str]:
    """Read each line as a header and its value, which two spaces or more separate."""
    found = [re.split(r"\s{2,}", line.strip(), maxsplit=1) for line in result.stdout.splitlines()]
    return {row[0]: row[1] if len(row) > 1 else "" for row in found}


def test_each_setting_is_on_a_line_with_its_value(client: type[StubClient]):
    result = run("--project", "acme", "--branch", "feature-x")

    assert result.exit_code == 0
    assert client.calls == ["branches acme", "settings feature-x"]
    assert client.modes == [True]
    assert pairs(result) == {
        "On new commit": "new_build",
        "Project defaults": "yes",
        "Install": "repository",
        "Modules": "",
        "Tests": "modules",
        "Test tags": "",
        "Demo data": "no",
        "AI agent": "claude",
        "Odoo version": "the project's",
        "Revision id": "latest",
        "OS": "ubuntu-24.04",
        "Recommended OS": "ubuntu-24.04",
        "OS on next commit": "",
        "Domains": "",
        "DNS target": "acme-feature-x-104.dev.odoo.com",
    }


def test_a_branch_of_its_own_shows_its_values(client: type[StubClient]):
    client.found = replace(
        DEVELOPMENT,
        push_behavior=PushBehavior.UPDATE,
        project_defaults=False,
        module_install=ModuleInstall.LISTED,
        modules=("sale", "purchase"),
        tests=BuildTests.TAGS,
        test_tags="/sale",
        odoo_version="18.0",
        odoo_revision_id=4021,
        next_machine="ubuntu-26.04",
        domains=("www.example.com", "shop.example.com"),
    )

    shown = pairs(run("--project", "acme", "--branch", "main"))

    assert shown["On new commit"] == "update"
    assert shown["Project defaults"] == "no"
    assert (shown["Install"], shown["Modules"]) == ("listed", "sale, purchase")
    assert (shown["Tests"], shown["Test tags"]) == ("tags", "/sale")
    assert (shown["Odoo version"], shown["Revision id"]) == ("18.0", "4021")
    assert shown["OS on next commit"] == "ubuntu-26.04"
    assert shown["Domains"] == "www.example.com, shop.example.com"


def test_as_json_is_the_whole_model_with_the_library_values():
    result = runner.invoke(
        app, ["--format", "json", "branches", "settings", "--project", "acme", "--branch", "feature-x"]
    )

    shown = json.loads(result.stdout)
    assert list(shown) == [field.name for field in fields(BranchSettings)]
    assert (shown["push_behavior"], shown["module_install"], shown["tests"]) == ("new_build", "repository", "modules")
    assert (shown["odoo_version"], shown["odoo_revision_id"], shown["domains"]) == (None, None, [])


def test_the_project_and_the_branch_come_from_the_checkout(client: type[StubClient], checkout: Callable[..., None]):
    checkout("feature-x", origin="git@github.com:acme/odoo.git")

    result = run()

    assert result.exit_code == 0
    assert client.calls == ["projects", "branches acme", "settings feature-x"]


def test_the_variable_names_the_branch(client: type[StubClient], monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(BRANCH_ENV, "main")

    result = run("--project", "acme")

    assert result.exit_code == 0
    assert client.calls == ["branches acme", "settings main"]


def test_a_branch_the_project_does_not_have_exits_4(client: type[StubClient]):
    result = run("--project", "acme", "--branch", "feature-y")

    assert result.exit_code == 4
    assert result.stdout == ""
    assert result.stderr == "Project acme has no branch feature-y.\n"
    assert client.calls == ["branches acme"]


def test_a_setting_odoo_sh_changed_exits_6(client: type[StubClient]):
    client.refused = odouche.UpstreamChangedError("branch settings", "result.test_mode")

    result = run("--project", "acme", "--branch", "feature-x")

    assert result.exit_code == 6
    assert result.stdout == ""
    assert "result.test_mode" in result.stderr


def test_help_names_the_example():
    result = runner.invoke(app, ["branches", "settings", "--help"])

    assert result.exit_code == 0
    assert "Example: osh branches settings" in click.unstyle(result.output)
