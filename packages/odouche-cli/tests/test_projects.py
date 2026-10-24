import dataclasses
import json
from collections.abc import Callable
from typing import Self

import click
import pytest
from typer.testing import CliRunner, Result

import odouche
from odouche_cli.app import app


ACME = odouche.Project(id=1, name="acme", repository="acme/odoo", url="https://www.odoo.sh/project/acme")
GLOBEX = odouche.Project(id=2, name="globex", repository="globex/erp", url="https://www.odoo.sh/project/globex")

OVERVIEW = odouche.ProjectOverview(
    id=1,
    name="acme",
    repository="acme/odoo",
    subscription=odouche.Subscription.VALID,
    subscription_name="valid",
    trial_days_left=None,
    odoo_version="19.0",
    region="Europe",
    dedicated=False,
    production_build=odouche.ProductionBuild(id=88001, branch_name="19.0", url="https://acme.odoo.com"),
    access_level="admin",
    hosting=odouche.ProjectHosting(
        storage_used_bytes=438272000,
        storage_quota_bytes=1073741824,
        workers=1,
        staging_branches=1,
    ),
    stages=(
        odouche.StageCount(odouche.Stage.PRODUCTION, "production", 1),
        odouche.StageCount(odouche.Stage.STAGING, "staging", 1),
        odouche.StageCount(odouche.Stage.DEVELOPMENT, "dev", 1),
    ),
    branches=(
        odouche.BranchSummary(
            odouche.Branch(51001, "19.0", odouche.Stage.PRODUCTION, "production"),
            odouche.TrackedBuild(88001, odouche.BuildStatus.DONE, "done", odouche.BuildResult.SUCCESS, "success"),
        ),
        odouche.BranchSummary(odouche.Branch(51044, "feature-x", odouche.Stage.DEVELOPMENT, "dev"), None),
    ),
)

runner = CliRunner()


class StubClient:
    """Stands in for `odouche.Client`: answers with projects or raises."""

    found: tuple[odouche.Project, ...] = (ACME, GLOBEX)
    overview: odouche.ProjectOverview = OVERVIEW
    error: odouche.OdoucheError | None = None
    modes: list[bool]
    """The `read_only` each client was built with."""
    calls: list[str]

    def __init__(self, *, read_only: bool = False) -> None:
        self.modes.append(read_only)
        if self.error is not None:
            raise self.error

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def projects(self) -> list[odouche.Project]:
        self.calls.append("projects")
        return list(self.found)

    def project_overview(self, project: odouche.Project | str) -> odouche.ProjectOverview:
        self.calls.append(f"project_overview {project}")
        return self.overview


@pytest.fixture(autouse=True)
def client(monkeypatch: pytest.MonkeyPatch) -> type[StubClient]:
    class Client(StubClient):
        modes: list[bool] = []
        calls: list[str] = []

    monkeypatch.setattr(odouche, "Client", Client)
    return Client


def run(*args: str) -> Result:
    return runner.invoke(app, list(args))


def test_list_shows_the_name_the_repository_and_the_address():
    result = run("projects", "list")

    assert result.exit_code == 0
    assert [line.split() for line in result.stdout.splitlines()] == [
        ["Name", "Repository", "URL"],
        ["acme", "acme/odoo", "https://www.odoo.sh/project/acme"],
        ["globex", "globex/erp", "https://www.odoo.sh/project/globex"],
    ]


def test_list_as_json_is_the_whole_model():
    result = run("--format", "json", "projects", "list")

    assert json.loads(result.stdout) == [
        {"id": 1, "name": "acme", "repository": "acme/odoo", "url": "https://www.odoo.sh/project/acme"},
        {"id": 2, "name": "globex", "repository": "globex/erp", "url": "https://www.odoo.sh/project/globex"},
    ]


def test_no_projects_is_a_line_on_stderr(client: type[StubClient]):
    client.found = ()

    result = run("projects", "list")

    assert result.exit_code == 0
    assert result.stdout == ""
    assert result.stderr == "No projects.\n"


def test_no_projects_as_json_is_an_empty_list(client: type[StubClient]):
    client.found = ()

    result = run("--format", "json", "projects", "list")

    assert result.exit_code == 0
    assert json.loads(result.stdout) == []


def test_logged_out_exits_3_and_names_the_login(client: type[StubClient]):
    client.error = odouche.NoSessionError("Not logged in.")

    result = run("projects", "list")

    assert result.exit_code == 3
    assert result.stdout == ""
    assert "osh auth login" in result.stderr


@pytest.mark.parametrize(
    ("command", "example"),
    [
        (("projects", "--help"), "Example: osh projects list"),
        (("projects", "list", "--help"), "Example: osh projects list"),
        (("projects", "show", "--help"), "Example: osh projects show --project acme-shop"),
    ],
)
def test_help_opens_neither_the_keyring_nor_the_network(
    client: type[StubClient], command: tuple[str, ...], example: str
):
    client.error = odouche.KeyringUnavailableError()

    result = run(*command)

    assert result.exit_code == 0
    assert example in click.unstyle(result.output)


def rows(result: Result) -> list[list[str]]:
    return [line.split() for line in result.stdout.splitlines()]


def test_show_prints_the_overview_one_fact_per_line(client: type[StubClient]):
    result = run("projects", "show", "--project", "acme")

    assert result.exit_code == 0
    assert client.calls == ["project_overview acme"]
    assert rows(result) == [
        ["Name", "acme"],
        ["Repository", "acme/odoo"],
        ["Subscription", "valid"],
        ["Odoo", "version", "19.0"],
        ["Region", "Europe"],
        ["Storage", "418.0", "MiB", "of", "1.0", "GiB,", "41%"],
        ["Workers", "1"],
        ["Staging", "branches", "1"],
        ["Dedicated", "no"],
        ["Production", "build", "88001", "on", "19.0"],
        ["Production", "URL", "https://acme.odoo.com"],
        ["Branches", "1", "production,", "1", "staging,", "1", "development"],
        ["Your", "access", "admin"],
    ]


def test_show_below_admin_prints_admins_only_for_the_hosting(client: type[StubClient]):
    client.overview = dataclasses.replace(OVERVIEW, access_level="developer", hosting=None)

    result = run("projects", "show", "--project", "acme")

    assert result.exit_code == 0
    shown = {" ".join(row[:-2]): " ".join(row[-2:]) for row in rows(result) if row[-2:] == ["admins", "only"]}
    assert ["Region", "Europe"] in rows(result)
    assert shown == {
        "Storage": "admins only",
        "Workers": "admins only",
        "Staging branches": "admins only",
    }


def test_show_names_an_unknown_subscription_its_trial_and_unknown_stages(client: type[StubClient]):
    client.overview = dataclasses.replace(
        OVERVIEW,
        subscription=odouche.Subscription.UNKNOWN,
        subscription_name="suspended",
        trial_days_left=12,
        production_build=None,
        dedicated=True,
        stages=(*OVERVIEW.stages, odouche.StageCount(odouche.Stage.UNKNOWN, "qa", 2)),
    )

    result = run("projects", "show", "--project", "acme")

    shown = rows(result)
    assert ["Subscription", "suspended,", "12", "days", "left"] in shown
    assert ["Dedicated", "yes"] in shown
    assert ["Production", "build", "none"] in shown
    assert ["Production", "URL"] in shown
    assert ["Branches", "1", "production,", "1", "staging,", "1", "development,", "2", "qa"] in shown


@pytest.mark.usefixtures("terminal")
@pytest.mark.parametrize(
    ("subscription", "colour"),
    [
        (odouche.Subscription.VALID, "\x1b[32m"),
        (odouche.Subscription.TRIAL, "\x1b[33m"),
        (odouche.Subscription.NON_STANDARD, "\x1b[33m"),
        (odouche.Subscription.EXPIRED, "\x1b[31m"),
    ],
)
def test_show_colours_the_subscription_on_a_terminal(
    client: type[StubClient], subscription: odouche.Subscription, colour: str
):
    client.overview = dataclasses.replace(OVERVIEW, subscription=subscription, subscription_name=subscription.value)

    result = run("projects", "show", "--project", "acme")

    assert f"{colour}{subscription.value}" in result.stdout


def test_show_as_json_is_exactly_the_model():
    result = run("--format", "json", "projects", "show", "--project", "acme")

    assert json.loads(result.stdout) == {
        "id": 1,
        "name": "acme",
        "repository": "acme/odoo",
        "subscription": "valid",
        "subscription_name": "valid",
        "trial_days_left": None,
        "odoo_version": "19.0",
        "region": "Europe",
        "dedicated": False,
        "production_build": {"id": 88001, "branch_name": "19.0", "url": "https://acme.odoo.com"},
        "access_level": "admin",
        "hosting": {
            "storage_used_bytes": 438272000,
            "storage_quota_bytes": 1073741824,
            "workers": 1,
            "staging_branches": 1,
        },
        "stages": [
            {"stage": "production", "stage_name": "production", "count": 1},
            {"stage": "staging", "stage_name": "staging", "count": 1},
            {"stage": "development", "stage_name": "dev", "count": 1},
        ],
        "branches": [
            {
                "branch": {"id": 51001, "name": "19.0", "stage": "production", "stage_name": "production"},
                "last_build": {
                    "id": 88001,
                    "status": "done",
                    "status_name": "done",
                    "result": "success",
                    "result_name": "success",
                },
            },
            {
                "branch": {"id": 51044, "name": "feature-x", "stage": "development", "stage_name": "dev"},
                "last_build": None,
            },
        ],
    }


def test_show_from_a_checkout_is_the_project_that_builds_it(client: type[StubClient], checkout: Callable[..., None]):
    checkout("feature-x", origin="git@github.com:globex/erp.git")

    result = run("projects", "show")

    assert result.exit_code == 0
    assert client.calls == ["projects", "project_overview globex"]


def test_show_gives_no_share_of_a_quota_of_nothing(client: type[StubClient]):
    assert OVERVIEW.hosting is not None
    hosting = dataclasses.replace(OVERVIEW.hosting, storage_used_bytes=512, storage_quota_bytes=0)
    client.overview = dataclasses.replace(OVERVIEW, hosting=hosting)

    result = run("projects", "show", "--project", "acme")

    assert ["Storage", "512", "B", "of", "0", "B"] in rows(result)
