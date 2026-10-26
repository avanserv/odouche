import copy
import dataclasses
import json

import pytest

from odouche import (
    BuildRevision,
    Client,
    NotFoundError,
    OdooRef,
    OdooRevision,
    Secret,
    UpstreamChangedError,
)


BRANCH = 51044
BUILD = 88212
BUILDS = "/app/branch/51044/builds"
PROJECTS = "/app/projects"
PROJECT = "acme-shop"
LATEST = "/app/branch/51044/revision"
PINNED = "/app/revision/2206"
HASH = "3f2a9c1e5b7d4f608192a3b4c5d6e7f801234567"
REFS = (
    OdooRef("odoo", "4f0c2a7d9be31e58a6c0d2f97b1e4a3c5d8e6f01", "https://github.com/odoo/odoo"),
    OdooRef("enterprise", "a83d5e1f0c7b29d64e1a5f3b8c2d7e9f0a1b4c62", "https://github.com/odoo/enterprise"),
    OdooRef("themes", "0d9e8f7a6b5c4d3e2f1a0b9c8d7e6f5a4b3c2d13", "https://github.com/odoo/design-themes"),
)


def branch_info(upstream):
    return upstream.bodies[BUILDS]["result"][0]["branch_info"]


def listed(upstream):
    return next(build for build in upstream.bodies[BUILDS]["result"][0]["builds"] if build["id"] == BUILD)


def answer(upstream, path=LATEST):
    """Replace the answer of `path` with a copy, and return its result to change."""
    upstream.bodies[path] = copy.deepcopy(upstream.bodies[path])

    return upstream.bodies[path]["result"]


def asked(upstream):
    return [(request.url.path, json.loads(request.content)["params"]) for request in upstream.requests]


def revision(client):
    return client.build_revision(PROJECT, client.build(BRANCH, BUILD))


def test_reads_the_head_commit_and_the_latest_revision_the_branch_follows(client, upstream):
    build = client.build(BRANCH, BUILD)
    upstream.requests.clear()

    read = client.build_revision(PROJECT, build)

    assert asked(upstream) == [(BUILDS, {"build_limit": 4}), (PROJECTS, {}), (LATEST, {"odoo_branch": "19.0"})]
    assert read == BuildRevision(
        build_id=BUILD,
        build_name="acme-shop-feature-invoicing-88212",
        branch_name="feature-invoicing",
        commit=build.commit,
        odoo_version="19.0",
        branch_odoo_revision=OdooRevision(id=2210, version="19.0", pinned=False, refs=REFS),
    )
    assert read.commit.hash == HASH


def test_a_pinned_revision_is_asked_by_its_number(client, upstream):
    branch_info(upstream)["odoo_revision_id"] = 2206
    build = client.build(BRANCH, BUILD)
    upstream.requests.clear()

    selected = client.build_revision(PROJECT, build).branch_odoo_revision

    assert asked(upstream) == [(BUILDS, {"build_limit": 4}), (PINNED, {})]
    assert selected is not None
    assert (selected.id, selected.version, selected.pinned) == (2206, "19.0", True)
    assert [ref.repository for ref in selected.refs] == ["odoo", "enterprise", "themes"]
    assert {ref.commit_hash for ref in selected.refs}.isdisjoint(ref.commit_hash for ref in REFS)


def test_the_branch_s_own_version_is_the_one_asked_for(client, upstream):
    branch_info(upstream)["odoo_branch"] = "18.0"
    answer(upstream)["branch"] = "18.0"
    read = revision(client)

    assert asked(upstream)[-2:] == [(BUILDS, {"build_limit": 4}), (LATEST, {"odoo_branch": "18.0"})]
    assert read.odoo_version == "19.0"
    assert read.branch_odoo_revision is not None
    assert read.branch_odoo_revision.version == "18.0"


def test_a_branch_without_a_version_follows_the_project_s_not_the_build_s(client, upstream):
    next(repo for repo in upstream.bodies[PROJECTS]["result"]["repos"] if repo["project_name"] == PROJECT)[
        "odoo_branch"
    ] = "20.0"
    answer(upstream)["branch"] = "20.0"
    read = revision(client)

    assert asked(upstream)[-1] == (LATEST, {"odoo_branch": "20.0"})
    assert read.odoo_version == "19.0"
    assert read.branch_odoo_revision is not None
    assert read.branch_odoo_revision.version == "20.0"


def test_a_project_out_of_reach_is_not_found(client, upstream):
    build = client.build(BRANCH, BUILD)
    upstream.requests.clear()

    with pytest.raises(NotFoundError, match="no project named 'nope'") as raised:
        client.build_revision("nope", build)

    assert raised.value.operation == "build revision"
    assert [request.url.path for request in upstream.requests] == [BUILDS, PROJECTS]


@pytest.mark.parametrize("value", [False, None])
def test_no_revision_is_none(client, upstream, value):
    upstream.bodies[LATEST] = {"jsonrpc": "2.0", "id": 34, "result": value}

    assert revision(client).branch_odoo_revision is None


def pinned(upstream):
    """Pin revision 2206 on the branch, and return the result of its answer to change."""
    branch_info(upstream)["odoo_revision_id"] = 2206

    return answer(upstream, PINNED)


def ref(upstream, **changes):
    answer(upstream)["refs"][1].update(changes)


@pytest.mark.parametrize(
    ("change", "field"),
    [
        (lambda upstream: ref(upstream, ref="a83d5e1"), "result.refs[1].ref"),
        (lambda upstream: ref(upstream, ref="A83D5E1F0C7B29D64E1A5F3B8C2D7E9F0A1B4C62"), "result.refs[1].ref"),
        (lambda upstream: ref(upstream, url="http://github.com/odoo/enterprise"), "result.refs[1].url"),
        (lambda upstream: ref(upstream, url="https://github.com/odoo/enter prise"), "result.refs[1].url"),
        (lambda upstream: ref(upstream, repository=""), "result.refs[1].repository"),
        (lambda upstream: answer(upstream)["refs"][1].pop("repository"), "result.refs[1].repository"),
        (lambda upstream: answer(upstream).update(refs=[]), "result.refs"),
        (lambda upstream: answer(upstream).update(branch="18.0"), "result.branch"),
        (lambda upstream: answer(upstream).update(id="2210"), "result.id"),
        (lambda upstream: pinned(upstream).update(id=2207), "result.id"),
        (
            lambda upstream: upstream.bodies[PROJECTS]["result"]["repos"][0].pop("odoo_branch"),
            "result.repos[0].odoo_branch",
        ),
        (lambda upstream: listed(upstream).update(odoo_branch=False), "result[0].builds[1].odoo_branch"),
        (
            lambda upstream: branch_info(upstream).update(odoo_revision_id="2206"),
            "result[0].branch_info.odoo_revision_id",
        ),
    ],
)
def test_a_changed_shape_names_its_field(client, upstream, change, field):
    build = client.build(BRANCH, BUILD)
    change(upstream)

    with pytest.raises(UpstreamChangedError) as raised:
        client.build_revision(PROJECT, build)

    assert raised.value.field == field


def test_a_build_no_longer_among_the_latest_is_not_found(client, upstream):
    build = client.build(BRANCH, BUILD)
    upstream.bodies[BUILDS]["result"][0]["builds"].remove(listed(upstream))

    with pytest.raises(NotFoundError, match=f"Build {BUILD} is not among the latest builds of branch {BRANCH}"):
        client.build_revision(PROJECT, build)

    assert [request.url.path for request in upstream.requests][-1] == BUILDS


def test_a_read_only_client_reads_it_the_same(client, upstream, session):
    with Client(Secret(session), read_only=True) as reader:
        assert revision(reader) == revision(client)


def test_the_revision_holds_these_fields_and_no_other():
    # A field added here, such as an empty list of linked repositories, could read as "none found".
    assert [field.name for field in dataclasses.fields(BuildRevision)] == [
        "build_id",
        "build_name",
        "branch_name",
        "commit",
        "odoo_version",
        "branch_odoo_revision",
    ]
