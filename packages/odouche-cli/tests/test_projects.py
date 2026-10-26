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
        (("projects", "check", "--help"), "Example: osh projects check --project acme-shop"),
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


PRODUCTION, FEATURE = OVERVIEW.branches


def tracked(build_id: int, result: odouche.BuildResult | None, name: str | None = None) -> odouche.TrackedBuild:
    status = odouche.BuildStatus.PROGRESS if result is None else odouche.BuildStatus.DONE
    return odouche.TrackedBuild(build_id, status, status.value, result, name or (result and result.value))


def with_production(build: odouche.TrackedBuild | None) -> odouche.ProjectOverview:
    return dataclasses.replace(OVERVIEW, branches=(dataclasses.replace(PRODUCTION, last_build=build), FEATURE))


def with_storage(used: int, quota: int = 1000) -> odouche.ProjectOverview:
    assert OVERVIEW.hosting is not None
    hosting = dataclasses.replace(OVERVIEW.hosting, storage_used_bytes=used, storage_quota_bytes=quota)

    return dataclasses.replace(OVERVIEW, hosting=hosting)


def checked(result: Result) -> dict[str, tuple[str, str]]:
    """Each check's result and fact, by its name."""
    found: dict[str, tuple[str, str]] = {}

    for line in result.stdout.splitlines()[1:]:
        name, verdict, fact = line.split(maxsplit=2)
        found[name] = (verdict, fact)

    return found


def test_check_of_a_healthy_project_passes_every_check(client: type[StubClient]):
    result = run("projects", "check", "--project", "acme")

    assert result.exit_code == 0
    assert result.stderr == ""
    assert client.modes == [True]
    assert client.calls == ["project_overview acme"]
    assert rows(result)[0] == ["Check", "Result", "Fact"]
    assert checked(result) == {
        "subscription": ("pass", "valid"),
        "production": ("pass", "build 88001 on 19.0 succeeded"),
        "storage": ("pass", "418.0 MiB of 1.0 GiB, 41%"),
        "branches": ("pass", "2 branches, none failed"),
    }


def test_check_of_a_failed_production_build_exits_30(client: type[StubClient]):
    client.overview = with_production(tracked(88002, odouche.BuildResult.FAILED))
    result = run("projects", "check", "--project", "acme")

    assert result.exit_code == 30
    assert result.stderr == ""
    assert checked(result)["production"] == ("fail", "build 88002 on 19.0 failed")
    assert checked(result)["branches"] == ("fail", "build 88002 on 19.0 failed")


@pytest.mark.parametrize(
    ("subscription", "days", "verdict", "fact", "code"),
    [
        (odouche.Subscription.VALID, None, "pass", "valid", 0),
        (odouche.Subscription.VALID, 3, "warn", "valid, 3 days left", 31),
        (odouche.Subscription.TRIAL, 1, "warn", "trial, 1 day left", 31),
        (odouche.Subscription.NON_STANDARD, None, "warn", "non_standard", 31),
        (odouche.Subscription.EXPIRED, None, "fail", "expired", 30),
        (odouche.Subscription.UNKNOWN, None, "fail", "suspended", 30),
    ],
)
def test_check_judges_the_subscription(
    client: type[StubClient], subscription: odouche.Subscription, days: int | None, verdict: str, fact: str, code: int
):
    named = "suspended" if subscription is odouche.Subscription.UNKNOWN else subscription.value
    client.overview = dataclasses.replace(
        OVERVIEW, subscription=subscription, subscription_name=named, trial_days_left=days
    )

    result = run("projects", "check", "--project", "acme")

    assert result.exit_code == code
    assert checked(result)["subscription"] == (verdict, fact)


@pytest.mark.parametrize(
    ("build", "verdict", "fact"),
    [
        (None, "warn", "19.0 has no build"),
        (tracked(88003, None), "warn", "build 88003 on 19.0 has no result yet (progress)"),
        (
            odouche.TrackedBuild(88003, odouche.BuildStatus.KILLED, "killed", None, None),
            "warn",
            "build 88003 on 19.0 ended without a result (killed)",
        ),
        (tracked(88003, odouche.BuildResult.WARNING), "warn", "build 88003 on 19.0 finished with warnings"),
        (tracked(88003, odouche.BuildResult.UNKNOWN, "flaky"), "warn", "build 88003 on 19.0 ended flaky"),
        (
            odouche.TrackedBuild(88003, odouche.BuildStatus.DROPPED, "dropped", odouche.BuildResult.SUCCESS, "success"),
            "pass",
            "build 88003 on 19.0 succeeded",
        ),
    ],
)
def test_check_judges_the_production_build_by_its_result(
    client: type[StubClient], build: odouche.TrackedBuild | None, verdict: str, fact: str
):
    client.overview = with_production(build)
    result = run("projects", "check", "--project", "acme")

    assert result.exit_code == (0 if verdict == "pass" else 31)
    assert checked(result)["production"] == (verdict, fact)


def test_check_with_no_production_branch_warns(client: type[StubClient]):
    client.overview = dataclasses.replace(OVERVIEW, branches=(FEATURE,))
    result = run("projects", "check", "--project", "acme")

    assert result.exit_code == 31
    assert checked(result)["production"] == ("warn", "no production branch")
    assert checked(result)["branches"] == ("pass", "1 branch, none failed")


def test_check_takes_the_worst_of_several_production_branches(client: type[StubClient]):
    other = odouche.BranchSummary(
        odouche.Branch(51002, "main", odouche.Stage.PRODUCTION, "production"),
        tracked(88004, odouche.BuildResult.FAILED),
    )
    client.overview = dataclasses.replace(OVERVIEW, branches=(PRODUCTION, other))
    result = run("projects", "check", "--project", "acme")

    assert result.exit_code == 30
    assert checked(result)["production"] == ("fail", "build 88001 on 19.0 succeeded; build 88004 on main failed")


@pytest.mark.parametrize(
    ("used", "options", "verdict", "code"),
    [
        (900, (), "pass", 0),
        (901, (), "warn", 31),
        (950, (), "warn", 31),
        (1000, (), "fail", 30),
        (1200, (), "fail", 30),
        (410, ("--storage-margin", "60"), "warn", 31),
        (950, ("--storage-margin", "0"), "pass", 0),
        (1000, ("--storage-margin", "0"), "fail", 30),
        (1, ("--storage-margin", "100"), "warn", 31),
        (0, ("--storage-margin", "100"), "pass", 0),
    ],
)
def test_check_judges_the_storage_against_the_margin(
    client: type[StubClient], used: int, options: tuple[str, ...], verdict: str, code: int
):
    client.overview = with_storage(used)
    result = run("projects", "check", "--project", "acme", *options)

    assert result.exit_code == code
    assert checked(result)["storage"][0] == verdict


@pytest.mark.parametrize("margin", ["101", "-1"])
def test_check_refuses_a_margin_out_of_range_before_asking(client: type[StubClient], margin: str):
    result = run("projects", "check", "--project", "acme", "--storage-margin", margin)

    assert result.exit_code == 2
    assert client.calls == []


def test_check_below_admin_skips_the_storage_and_exits_0(client: type[StubClient]):
    client.overview = dataclasses.replace(OVERVIEW, access_level="developer", hosting=None)
    result = run("projects", "check", "--project", "acme")

    assert result.exit_code == 0
    assert checked(result)["storage"] == ("skip", "admins only")


def test_check_skips_a_quota_of_nothing(client: type[StubClient]):
    client.overview = with_storage(512, quota=0)
    result = run("projects", "check", "--project", "acme")

    assert result.exit_code == 0
    assert checked(result)["storage"] == ("skip", "512 B of 0 B")


def test_check_fails_the_branches_on_a_failed_development_build(client: type[StubClient]):
    failed = dataclasses.replace(FEATURE, last_build=tracked(88010, odouche.BuildResult.FAILED))
    warned = odouche.BranchSummary(
        odouche.Branch(51045, "feature-y", odouche.Stage.DEVELOPMENT, "dev"),
        tracked(88011, odouche.BuildResult.WARNING),
    )
    client.overview = dataclasses.replace(OVERVIEW, branches=(PRODUCTION, failed, warned))
    result = run("projects", "check", "--project", "acme")

    assert result.exit_code == 30
    assert checked(result)["branches"] == ("fail", "build 88010 on feature-x failed")
    assert checked(result)["production"][0] == "pass"


def test_check_warns_on_a_development_build_whose_result_is_unknown(client: type[StubClient]):
    unknown = dataclasses.replace(FEATURE, last_build=tracked(88010, odouche.BuildResult.UNKNOWN, "flaky"))
    client.overview = dataclasses.replace(OVERVIEW, branches=(PRODUCTION, unknown))
    result = run("projects", "check", "--project", "acme")

    assert result.exit_code == 31
    assert checked(result)["branches"] == ("warn", "build 88010 on feature-x ended flaky")


def test_check_ignores_a_development_build_with_warnings(client: type[StubClient]):
    warned = dataclasses.replace(FEATURE, last_build=tracked(88010, odouche.BuildResult.WARNING))
    client.overview = dataclasses.replace(OVERVIEW, branches=(PRODUCTION, warned))
    result = run("projects", "check", "--project", "acme")

    assert result.exit_code == 0
    assert checked(result)["branches"] == ("pass", "2 branches, none failed")


@pytest.mark.parametrize(
    ("overview", "code"),
    [
        (dataclasses.replace(with_storage(950), subscription=odouche.Subscription.EXPIRED), 30),
        (with_storage(950), 31),
        (dataclasses.replace(OVERVIEW, hosting=None), 0),
    ],
)
def test_check_exits_with_the_worst_result(client: type[StubClient], overview: odouche.ProjectOverview, code: int):
    client.overview = overview
    result = run("projects", "check", "--project", "acme")

    assert result.exit_code == code


def test_check_as_json_is_the_checks():
    result = run("--format", "json", "projects", "check", "--project", "acme")

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [
        {"name": "subscription", "result": "pass", "fact": "valid"},
        {"name": "production", "result": "pass", "fact": "build 88001 on 19.0 succeeded"},
        {"name": "storage", "result": "pass", "fact": "418.0 MiB of 1.0 GiB, 41%"},
        {"name": "branches", "result": "pass", "fact": "2 branches, none failed"},
    ]


def test_check_as_json_keeps_the_exit_code(client: type[StubClient]):
    client.overview = with_production(tracked(88002, odouche.BuildResult.FAILED))
    result = run("--format", "json", "projects", "check", "--project", "acme")

    assert result.exit_code == 30
    assert result.stderr == ""
    assert json.loads(result.stdout)[1] == {
        "name": "production",
        "result": "fail",
        "fact": "build 88002 on 19.0 failed",
    }


@pytest.mark.parametrize(
    ("error", "code"),
    [(odouche.NoSessionError("Not logged in."), 3), (odouche.UpstreamChangedError("project", "name"), 6)],
)
def test_check_that_cannot_read_the_project_prints_nothing(
    client: type[StubClient], error: odouche.OdoucheError, code: int
):
    client.error = error
    result = run("projects", "check", "--project", "acme")

    assert result.exit_code == code
    assert result.stdout == ""


def test_check_strips_control_characters_from_a_branch_name(client: type[StubClient]):
    branch = odouche.Branch(51046, "evil\x1b[2Jname", odouche.Stage.DEVELOPMENT, "dev")
    failed = odouche.BranchSummary(branch, tracked(88012, odouche.BuildResult.FAILED))
    client.overview = dataclasses.replace(OVERVIEW, branches=(PRODUCTION, failed))
    result = run("projects", "check", "--project", "acme")

    assert "\x1b" not in result.stdout
    assert checked(result)["branches"] == ("fail", "build 88012 on evil[2Jname failed")


@pytest.mark.usefixtures("terminal")
@pytest.mark.parametrize(
    ("overview", "verdict", "colour"),
    [
        (OVERVIEW, "pass", "\x1b[32m"),
        (with_storage(950), "warn", "\x1b[33m"),
        (with_storage(1000), "fail", "\x1b[31m"),
    ],
)
def test_check_colours_the_result_on_a_terminal(
    client: type[StubClient], overview: odouche.ProjectOverview, verdict: str, colour: str
):
    client.overview = overview
    result = run("projects", "check", "--project", "acme")

    assert f"{colour}{verdict}" in result.stdout
