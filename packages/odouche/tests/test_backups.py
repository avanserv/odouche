import dataclasses
import logging
import traceback
from datetime import UTC, datetime

import pytest

from odouche import Backup, BackupKind, Client, NotFoundError, Secret, UpstreamChangedError


PROJECTS = "/app/projects"
PATH = "/app/project/acme-corp-odoo-addons-4217/backups"
PRODUCTION = "acme-corp-odoo-addons-19-0-88001"
PRODUCTION_COMMIT = "9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a09"


def test_lists_each_shape_newest_first(client, upstream, session):
    assert client.backups("acme-shop") == [
        Backup(
            kind=BackupKind.MANUAL,
            kind_name="manual",
            taken_at=datetime(2026, 10, 14, 12, 48, 50, tzinfo=UTC),
            build_name="acme-shop-staging-88124",
            branch_name="staging",
            commit_hash="4f1c2a9e8b7d6c5f4e3d2c1b0a9f8e7d6c5b4a39",
            downloadable=True,
            size=None,
        ),
        Backup(
            kind=BackupKind.DAILY,
            kind_name="daily",
            taken_at=datetime(2026, 10, 13, 18, 9, 37, tzinfo=UTC),
            build_name=PRODUCTION,
            branch_name="19.0",
            commit_hash=PRODUCTION_COMMIT,
            downloadable=True,
            size=None,
        ),
        Backup(
            kind=BackupKind.REMOTE,
            kind_name="remote",
            taken_at=datetime(2026, 10, 13, 18, 9, 37, tzinfo=UTC),
            build_name=PRODUCTION,
            branch_name="19.0",
            commit_hash=PRODUCTION_COMMIT,
            downloadable=False,
            size=1150662,
        ),
        Backup(
            kind=BackupKind.REMOTE,
            kind_name="remote",
            taken_at=datetime(2026, 10, 12, 18, 9, 59, tzinfo=UTC),
            build_name=PRODUCTION,
            branch_name="19.0",
            commit_hash=PRODUCTION_COMMIT,
            downloadable=False,
            size=1150574,
        ),
    ]
    assert [(request.method, request.url.path) for request in upstream.requests] == [
        ("POST", PROJECTS),
        ("POST", PATH),
    ]
    assert upstream.requests[1].headers["Cookie"] == f"session_id={session}"


def test_takes_a_project_or_its_name(client):
    project = client.projects()[0]

    assert client.backups(project) == client.backups(project.name)


def test_orders_by_time_whatever_the_order_of_the_answer(client, upstream):
    upstream.bodies[PATH]["result"].reverse()

    taken = [backup.taken_at for backup in client.backups("acme-shop")]

    assert taken == sorted(taken, reverse=True)


def test_a_backup_is_immutable_and_holds_no_id_nor_path(client):
    backup = client.backups("acme-shop")[2]

    assert [field.name for field in dataclasses.fields(backup)] == [
        "kind",
        "kind_name",
        "taken_at",
        "build_name",
        "branch_name",
        "commit_hash",
        "downloadable",
        "size",
    ]

    with pytest.raises(dataclasses.FrozenInstanceError):
        backup.size = 0


def test_a_read_only_client_lists_them(upstream, session):
    with Client(Secret(session), read_only=True) as client:
        assert len(client.backups("acme-shop")) == 4

    assert [request.url.path for request in upstream.requests] == [PROJECTS, PATH]


def test_an_unseen_kind_is_unknown_and_keeps_its_name(client, upstream, caplog):
    upstream.bodies[PATH]["result"][0]["type"] = "hourly"

    with caplog.at_level(logging.DEBUG, logger="odouche"):
        backup = client.backups("acme-shop")[0]

    assert (backup.kind, backup.kind_name) == (BackupKind.UNKNOWN, "hourly")
    assert "Unknown backup kind: 'hourly'" in caplog.messages


def test_a_size_given_as_an_integer_is_read(client, upstream):
    upstream.bodies[PATH]["result"][2]["size_sql_gz"] = 1150662

    assert client.backups("acme-shop")[2].size == 1150662


def test_no_backup_is_an_empty_list(client, upstream):
    upstream.bodies[PATH]["result"] = []

    assert client.backups("acme-shop") == []


def test_a_project_that_is_not_listed_is_not_found(client, upstream):
    with pytest.raises(NotFoundError) as raised:
        client.backups("no-such-project")

    assert raised.value.operation == "backups"
    assert [request.url.path for request in upstream.requests] == [PROJECTS]


@pytest.mark.parametrize(
    ("index", "field", "value"),
    [
        (0, "type", None),
        (0, "backup_datetime_utc", None),
        (0, "backup_datetime_utc", "2026-10-14T12:48:50Z"),
        (1, "name", False),
        (1, "branch", ["19.0"]),
        (1, "revision", None),
        (1, "downloadable", "true"),
        (1, "downloadable", None),
        (2, "size_sql_gz", "1150662"),
        (2, "size_sql_gz", True),
        (2, "size_sql_gz", -1.0),
        (2, "size_sql_gz", 1150662.5),
    ],
)
def test_names_the_field_that_changed_shape(client, upstream, index, field, value):
    backup = upstream.bodies[PATH]["result"][index]

    if value is None:
        del backup[field]
    else:
        backup[field] = value

    with pytest.raises(UpstreamChangedError) as raised:
        client.backups("acme-shop")

    assert raised.value.operation == "backups"
    assert raised.value.field == f"result[{index}].{field}"


def test_a_changed_shape_error_shows_nothing_of_the_answer(client, upstream, session):
    upstream.bodies[PATH]["result"][0]["backup_datetime_utc"] = "acme-shop-staging-88124"

    with pytest.raises(UpstreamChangedError) as raised:
        client.backups("acme-shop")

    text = "".join(traceback.format_exception(raised.value))

    for value in ("acme-shop-staging-88124", "acme-corp-odoo-addons-4217", session):
        assert value not in text
